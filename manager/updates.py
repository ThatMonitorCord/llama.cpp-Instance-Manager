"""Small, cached release check for the manager's own repository."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.parse

from . import VERSION
from .config import REPOSITORY
from .platform import hidden_process


def installed_directory():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5E8A15A3-7C9C-47A5-A577-16CE0B45B43B}_is1") as key:
            directory = Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve()
        return directory if Path(sys.executable).resolve().parent == directory else None
    except OSError:
        return None


def release_asset(url, tag, filename):
    parsed = urllib.parse.urlsplit(str(url))
    expected = f"/{REPOSITORY}/releases/download/{tag}/{filename}"
    if parsed.scheme != "https" or parsed.netloc != "github.com" or urllib.parse.unquote(parsed.path) != expected or parsed.query or parsed.fragment:
        raise ValueError("The update asset is not from this manager's release repository.")
    return url


def version_number(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value))
    if not match:
        raise ValueError("The release has an unsupported version number.")
    return tuple(int(part) for part in match.groups())


class UpdateChecker:
    def __init__(self, store=None):
        self.store = store
        self.lock = threading.Lock()
        self.result = None
        self.expires = 0

    def check(self, force=False):
        with self.lock:
            if not force and self.result is not None and time.monotonic() < self.expires:
                return dict(self.result)
            result = {"current": VERSION, "latest": None, "available": False,
                      "download": None, "url": None, "checked_at": time.time(), "error": None,
                      "notes": "", "can_install": False, "checksum_url": None, "tag": None}
            try:
                req = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                    headers={"User-Agent": "llama.cpp-Instance-Manager", "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    release = json.load(response)
                if not release.get("draft") and not release.get("prerelease"):
                    latest = release["tag_name"].removeprefix("v")
                    newer = version_number(latest) > version_number(VERSION)
                    name = f"llama-cpp-instance-manager-{latest}-windows-x64-setup.exe"
                    installer = next((asset for asset in release.get("assets", []) if asset["name"] == name), None)
                    checksums = next((asset for asset in release.get("assets", []) if asset["name"] == "SHA256SUMS.txt"), None)
                    download = release_asset(installer["browser_download_url"], release["tag_name"], name) if installer else None
                    checksum_url = release_asset(checksums["browser_download_url"], release["tag_name"], "SHA256SUMS.txt") if checksums else None
                    result.update(latest=latest, available=newer, url=release["html_url"], tag=release["tag_name"],
                                  notes=str(release.get("body") or "No changelog was provided for this release.")[:50000],
                                  download=download if newer else None, checksum_url=checksum_url,
                                  can_install=bool(newer and download and checksum_url and installed_directory()))
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    result["error"] = "Could not check for updates. Try again shortly."
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                result["error"] = "Could not check for updates. Check your connection and try again."
            self.result = result
            self.expires = time.monotonic() + (300 if result["error"] else 3600)
            return dict(result)

    def apply(self, expected_version, progress):
        directory = installed_directory()
        if directory is None or self.store is None:
            raise ValueError("Use the Windows setup to install this manager first.")
        update = self.check(force=True)
        if update["error"]:
            raise ValueError(update["error"])
        if not update["can_install"] or update["latest"] != expected_version:
            raise ValueError("Check for updates again before installing.")
        name = f"llama-cpp-instance-manager-{update['latest']}-windows-x64-setup.exe"
        folder = self.store.directory / "updates" / update["latest"]
        folder.mkdir(parents=True, exist_ok=True)
        target, partial = folder / name, folder / (name + ".partial")
        progress("Downloading update…")
        with urllib.request.urlopen(update["checksum_url"], timeout=30) as response:
            sums = response.read(65536).decode("utf-8-sig")
        checksum = next((line.split()[0].lower() for line in sums.splitlines()
                         if len(line.split()) == 2 and line.split()[1].lstrip("*") == name), "")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("The release does not include a valid installer checksum.")
        digest, size = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(update["download"], timeout=30) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise ValueError("The update download is larger than expected.")
                    digest.update(chunk)
                    output.write(chunk)
                    progress(f"Downloading update: {size // (1024 * 1024)} MB")
            if digest.hexdigest() != checksum:
                raise ValueError("The update download could not be verified. Try again.")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        progress("Installing update… The manager will reopen automatically.")
        env = dict(os.environ, LLAMA_MANAGER_DATA=str(self.store.directory))
        child = subprocess.Popen([str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
            "/ACTION=update", "/RESTARTMANAGER=1", f"/DIR={directory}",
            f"/LOG={self.store.directory / 'manager-update.log'}"], env=env, **hidden_process())
        # Setup closes this manager through --quit. If it fails before that, the
        # still-running manager can report the error and allow another attempt.
        if child.wait() != 0:
            raise ValueError("Setup could not finish. See manager-update.log in the manager data folder.")
        return {"ok": True}
