"""Download checksum-pinned Windows runtimes into build/runtimes."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "installer/runtimes.json").read_text())
    build = ROOT / "build"
    cache = build / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    for name, artifact in manifest.items():
        destination = build / "runtimes" / name
        marker = destination / ".artifact-sha256"
        if marker.exists() and marker.read_text() == artifact["sha256"]:
            print(f"{name}: already verified", flush=True)
            continue
        suffix = ".tar.gz" if artifact["url"].endswith(".tar.gz") else ".zip"
        archive = cache / (artifact["sha256"] + suffix)
        if not archive.exists():
            print(f"Downloading {name}...", flush=True)
            partial = archive.with_suffix(".partial")
            try:
                req = urllib.request.Request(artifact["url"], headers={"User-Agent": "llama.cpp-Instance-Manager-build"})
                with urllib.request.urlopen(req, timeout=120) as source, partial.open("wb") as target:
                    shutil.copyfileobj(source, target)
                partial.replace(archive)
            finally:
                partial.unlink(missing_ok=True)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        if checksum != artifact["sha256"]:
            raise ValueError(f"Checksum mismatch for {name}")
        extracted = build / "unpack" / name
        extracted.mkdir(parents=True, exist_ok=True)
        print(f"Extracting {name}...", flush=True)
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as handle:
                for member in handle.infolist():
                    if not (extracted / member.filename).resolve().is_relative_to(extracted.resolve()):
                        raise ValueError("Invalid archive path")
                handle.extractall(extracted)
        else:
            with tarfile.open(archive) as handle:
                handle.extractall(extracted, filter="data")
        source = extracted / artifact["prefix"] if artifact["prefix"] else extracted
        shutil.copytree(source, destination, dirs_exist_ok=True)
        marker.write_text(checksum)
        print(f"{name}: ready", flush=True)


if __name__ == "__main__":
    main()
