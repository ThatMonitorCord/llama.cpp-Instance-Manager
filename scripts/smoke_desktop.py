"""Exercise the actual Windows window, tray activation and persisted WebView2 UI.

Uses a fresh test profile; does not change login startup, instances or firewall.
"""
import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manager.config import Store, next_port
from manager.platform import hidden_process
from manager.transport import request


def wait_for(check, message, timeout=40):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise AssertionError(message)


def main():
    if os.name != "nt":
        raise RuntimeError("Windows desktop test")
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=ROOT / "dist/LlamaInstanceManager/LlamaInstanceManager.exe")
    args = parser.parse_args()
    user = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.IsIconic.argtypes = [wintypes.HWND]

    def windows(pid, tray=False):
        found = []
        @callback_type
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                title = ctypes.create_unicode_buffer(256)
                if tray:
                    user.GetClassNameW(hwnd, title, 256)
                    matches = title.value.startswith("LlamaCppInstanceManager") and title.value.endswith("SystemTrayIcon")
                else:
                    user.GetWindowTextW(hwnd, title, 256)
                    matches = title.value == "llama.cpp Instance Manager"
                if matches:
                    found.append(hwnd)
            return True
        user.EnumWindows(visit, 0)
        return found

    store = Store(ROOT / ".test-data" / ("desktop-" + uuid.uuid4().hex[:8]))
    port = next_port(16439)
    debug_port = next_port(port + 1)
    store.change(lambda data: data.update(port=port, configured=True, login_start=False, name="Desktop smoke test"))
    command = [str(args.exe.resolve()), "--data-dir", str(store.directory), "--no-discovery"]
    env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={debug_port}")
    node = shutil.which("node") or str(ROOT / "build/runtimes/node/node.exe")
    child = None
    try:
        for phase in ("save", "restore"):
            child = subprocess.Popen(command + (["--background"] if phase == "save" else []), env=env, **hidden_process())
            info = wait_for(lambda: request(f"http://127.0.0.1:{port}/api/info", timeout=1), "HTTP server did not start")
            assert info["pid"] == child.pid
            hwnd = wait_for(lambda: next(iter(windows(child.pid)), None), "Desktop window was not created")
            wait_for(lambda: request(f"http://127.0.0.1:{debug_port}/json/version", timeout=1), "WebView2 did not start")
            if phase == "save":
                assert not user.IsWindowVisible(hwnd), "Background startup opened a window"
            else:
                wait_for(lambda: user.IsWindowVisible(hwnd), "Normal startup did not open a window")
            subprocess.run(command, check=True, timeout=15, **hidden_process())
            wait_for(lambda: user.IsWindowVisible(hwnd), "Second launch did not open the existing window")
            assert windows(child.pid) == [hwnd], "Duplicate manager windows"
            subprocess.run([node, str(ROOT / "scripts/check_desktop.cjs"), f"http://127.0.0.1:{debug_port}", phase,
                            str(store.directory / f"{phase}.png")], check=True, timeout=45, **hidden_process())
            user.ShowWindow(hwnd, 6)  # Minimize, then verify shortcut activation restores it.
            subprocess.run(command, check=True, timeout=15, **hidden_process())
            wait_for(lambda: not user.IsIconic(hwnd), "Second launch did not restore the minimized window")
            user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE must hide rather than exit.
            wait_for(lambda: not user.IsWindowVisible(hwnd), "Close did not hide the window")
            assert child.poll() is None
            assert request(f"http://127.0.0.1:{port}/api/info")["pid"] == child.pid
            tray_handles = wait_for(lambda: windows(child.pid, tray=True), "Tray icon message window missing")
            # Deliver the same notification Explorer sends when the tray icon is clicked.
            for handle in tray_handles:
                user.PostMessageW(handle, 0x0400 + 11, 0, 0x0202)
            wait_for(lambda: user.IsWindowVisible(hwnd), "Tray Open manager did not reopen the window")
            user.PostMessageW(hwnd, 0x0010, 0, 0)
            wait_for(lambda: not user.IsWindowVisible(hwnd), "Second close did not hide the window")
            subprocess.run(command + ["--background"], check=True, timeout=15, **hidden_process())
            assert not user.IsWindowVisible(hwnd), "Repeated background launch opened a window"
            subprocess.run(command + ["--quit"], check=True, timeout=30, **hidden_process())
            child.wait(timeout=5)
            assert not windows(child.pid, tray=True), "Tray handles remained after quit"
            print("PASS: startup, single window, minimize/restore, close-to-tray, tray activation and graceful quit", flush=True)
        print(f"Desktop screenshots and logs: {store.directory}", flush=True)
    finally:
        if child and child.poll() is None:
            try:
                request(f"http://127.0.0.1:{port}/api/quit", {}, timeout=2)
                child.wait(timeout=15)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                child.terminate()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
