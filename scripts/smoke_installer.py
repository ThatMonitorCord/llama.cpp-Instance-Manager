"""Install, upgrade, and uninstall the built setup in an isolated workspace folder."""
from pathlib import Path
import hashlib
import io
import os
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from manager.config import Store, next_port
from manager import VERSION
from manager.platform import hidden_process
from manager.transport import request
from manager.updates import UpdateChecker


def main():
    if os.name!="nt":
        raise RuntimeError("Windows installer test")
    import winreg
    destination=ROOT/".test-data/installed-app"
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5E8A15A3-7C9C-47A5-A577-16CE0B45B43B}_is1") as key:
            installed=winreg.QueryValueEx(key,"InstallLocation")[0]
            if Path(installed).resolve()!=destination.resolve():
                raise RuntimeError("An existing user installation is present; refusing to replace it during testing.")
    except FileNotFoundError:
        pass
    setup=ROOT/"dist"/f"llama-cpp-instance-manager-{VERSION}-windows-x64-setup.exe"
    args=[str(setup),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/NOICONS","/MERGETASKS=!desktopicon",f"/DIR={destination}",f"/LOG={ROOT/'.test-data/installer.log'}"]
    store=Store(ROOT/".test-data/installed-profile")
    # The installer's --quit child must target this isolated test profile too.
    env=dict(os.environ, LLAMA_MANAGER_DATA=str(store.directory))
    try:
        subprocess.run(args,env=env,check=True,timeout=180,**hidden_process())
    except subprocess.CalledProcessError:
        log=ROOT/".test-data/installer.log"
        if log.exists():
            print(log.read_text(encoding="utf-8",errors="replace")[-12000:],flush=True)
        raise
    exe=destination/"LlamaInstanceManager.exe"
    assert exe.is_file()
    for binary in ("runtimes/python/python.exe","runtimes/git/cmd/git.exe","runtimes/node/node.exe"):
        assert (destination/binary).is_file(),binary
    print("PASS: clean setup includes the manager and all portable prerequisites",flush=True)
    port=next_port(16239)
    store.change(lambda data:data.update(port=port,name="Upgrade persistence",configured=True,login_start=False))
    marker=store.directory/"models/keep.gguf"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text("preserve test data")
    child=None
    uninstalled=False
    try:
        for iteration in range(4):
            asset=destination/"_internal/manager/web/logo.png"
            if iteration==0:
                assert asset.is_file()
                asset.unlink()  # Reinstall must restore missing program files.
            elif iteration in (1,2):
                # Present an older registered version to exercise the Update choice.
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5E8A15A3-7C9C-47A5-A577-16CE0B45B43B}_is1",0,winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key,"DisplayVersion",0,winreg.REG_SZ,"0.2.0")
            child=subprocess.Popen([str(exe),"--background","--data-dir",str(store.directory),"--no-discovery"],**hidden_process())
            ready=False
            for _ in range(40):
                try:
                    info=request(f"http://127.0.0.1:{port}/api/info",timeout=1)
                    ready=info["name"]=="Upgrade persistence"
                    if ready:
                        break
                except (OSError,ValueError):
                    time.sleep(.25)
            assert ready,"Installed application did not start"
            assert "llama.cpp Instance Manager" in request(f"http://127.0.0.1:{port}/",text=True)
            if iteration<2:
                action="reinstall" if iteration==0 else "update"
                subprocess.run(args+[f"/ACTION={action}"],env=env,check=True,timeout=180,**hidden_process())
                child.wait(timeout=15)
                assert asset.is_file()
                assert f"Setup action: {action};" in (ROOT/".test-data/installer.log").read_text(encoding="utf-8",errors="replace")
                assert marker.read_text()=="preserve test data"
                assert Store(store.directory).read()["name"]=="Upgrade persistence"
            elif iteration==2:
                # Use the real staging/verification/launch path with this build
                # as the release fixture; no public GitHub release is required.
                checker=UpdateChecker(store)
                checksum=(hashlib.sha256(setup.read_bytes()).hexdigest()+"  "+setup.name).encode()
                update={"error":None,"latest":VERSION,"can_install":True,"checksum_url":"checksums","download":"setup"}
                def download(url, **kwargs):
                    return io.BytesIO(checksum) if url=="checksums" else setup.open("rb")
                with patch("manager.updates.installed_directory",return_value=destination), \
                     patch.object(checker,"check",return_value=update), \
                     patch("manager.updates.urllib.request.urlopen",side_effect=download):
                    checker.apply(VERSION,lambda message: print(message,flush=True) if message.startswith("Installing") else None)
                child.wait(timeout=15)
                restarted=False
                for _ in range(60):
                    try:
                        info=request(f"http://127.0.0.1:{port}/api/info",timeout=1)
                        restarted=info["pid"]!=child.pid and info["name"]=="Upgrade persistence"
                        if restarted: break
                    except (OSError,ValueError):
                        pass
                    time.sleep(.25)
                assert restarted,"Automatic update did not reopen the manager profile"
                assert marker.read_text()=="preserve test data"
                subprocess.run([str(exe),"--quit","--data-dir",str(store.directory)],check=True,timeout=30,**hidden_process())
                print("PASS: verified updater installs silently and automatically reopens the same manager profile",flush=True)
            else:
                subprocess.run([str(destination/"unins000.exe"),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART"],env=env,check=True,timeout=120,**hidden_process())
                uninstalled=True
                child.wait(timeout=15)
        print("PASS: explicit reinstall repairs missing files; explicit update preserves settings/models; app restarts",flush=True)
    finally:
        if exe.exists():
            subprocess.run([str(exe),"--quit","--data-dir",str(store.directory)],timeout=30,**hidden_process())
        if child and child.poll() is None:
            child.terminate();child.wait(timeout=15)
        uninstall=destination/"unins000.exe"
        if not uninstalled and uninstall.exists():
            subprocess.run([str(uninstall),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART"],env=env,check=True,timeout=120,**hidden_process())
    assert marker.exists()
    print("PASS: uninstall preserves instance data",flush=True)


if __name__=="__main__":
    main()
