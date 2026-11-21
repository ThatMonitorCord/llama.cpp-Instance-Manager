"""Small Windows window/tray shell around the existing HTTP dashboard."""
import ctypes
from ctypes import wintypes
import hashlib
import logging
import os
from pathlib import Path
import threading


TITLE = "llama.cpp Instance Manager"
ICON = Path(__file__).resolve().parents[1] / "assets" / "manager.ico"


class DesktopSession:
    """One desktop per data directory, with a Windows event for shortcut activation.

    Create the event before the mutex so an early second launch cannot lose its
    request while the first process is still starting WebView2.
    """
    def __init__(self, directory):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        identity = hashlib.sha256(os.path.normcase(str(Path(directory).resolve())).encode()).hexdigest()
        name = "Local\\LlamaCppInstanceManager-" + identity
        self.event = self.kernel.CreateEventW(None, False, False, name + "-show")
        self.mutex = self.kernel.CreateMutexW(None, False, name)
        self.primary = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
        if not self.event or not self.mutex:
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def activate(self):
        # A shortcut launch may transfer its foreground permission to the app.
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        if not self.kernel.SetEvent(self.event):
            raise ctypes.WinError(ctypes.get_last_error())

    def requested(self):
        return self.kernel.WaitForSingleObject(self.event, 0) == 0

    def close(self):
        for name in ("event", "mutex"):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


class Desktop:
    def __init__(self, app, session):
        self.app = app
        self.session = session
        self.window = None
        self.tray = None
        self.exiting = False

    def show(self, *_):
        if not self.exiting:
            self.window.restore()
            self.window.show()

    def closing(self):
        if self.exiting:
            return True
        self.window.hide()
        return False

    def quit(self, *_):
        try:
            self.app.quit()
        except ValueError as exc:
            self.tray.notify(str(exc), TITLE)

    def toggle_login(self, *_):
        try:
            self.app.settings({"login_start": not self.app.store.read()["login_start"]})
        except OSError as exc:
            logging.exception("Could not change login startup")
            self.tray.notify(str(exc), TITLE)

    def watch(self):
        while not self.app.stop_event.wait(0.2):
            if self.session.requested():
                self.show()
        self.exiting = True
        self.window.destroy()

    def run(self, background=False, debug_port=None):
        import webview
        import pystray
        from PIL import Image

        # Elevated Windows runners ignore WEBVIEW2_* environment overrides.
        # This explicit opt-in uses the supported WebView2 API; normally disabled.
        if debug_port is not None:
            webview.settings["REMOTE_DEBUGGING_PORT"] = debug_port
        self.window = webview.create_window(
            TITLE, f"http://127.0.0.1:{self.app.store.read()['port']}",
            width=1200, height=820, min_size=(680, 480), hidden=background,
            background_color="#14141f", text_select=True,
        )
        self.window.events.closing += self.closing
        self.tray = pystray.Icon("LlamaCppInstanceManager", Image.open(ICON), TITLE,
            menu=pystray.Menu(
                pystray.MenuItem("Open manager", self.show, default=True),
                pystray.MenuItem("Start at Windows login", self.toggle_login,
                    checked=lambda _: self.app.store.read()["login_start"]),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit manager", self.quit),
            ))
        tray_thread = threading.Thread(target=self.tray.run, daemon=True, name="manager-tray")
        tray_thread.start()
        try:
            webview.start(self.watch, gui="edgechromium", private_mode=False,
                storage_path=str(self.app.store.directory / "webview"), icon=str(ICON))
        finally:
            self.exiting = True
            self.tray.stop()
            tray_thread.join(timeout=3)
