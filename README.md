# llama.cpp Instance Manager

A Windows installer and LAN dashboard for independent
[LLama-GUI](https://github.com/thomas9120/LLama-GUI) installations.

Choose how many **llama.cpp instances** to install, assign available control-panel
and inference ports, and optionally share a models folder. Each instance has its
own upstream checkout, runtime, environment, backend files, and updates.

The manager provides saved-preset startup, local and LAN start/stop/restart,
automatic LAN discovery, and a combined inference monitor. Detailed configuration,
backend/model installation, and chat remain in each original instance.

## Install on Windows

Download the `.exe` from [Releases](https://github.com/ThatMonitorCord/llama.cpp-Instance-Manager/releases/latest).
Run setup, then follow the first-run wizard to name your server, select an instance
count, choose folders, and review ports. Setup includes portable Python, Git, and
Node. Internet access is used to download upstream instances and their dependencies.

The manager starts at Windows login by default. Disable this in Settings if desired.
Windows Firewall setup is optional and asks Windows for approval to allow the
selected TCP ports and discovery UDP 5238 on private networks.

1. Choose **Open instance** to select a backend and model in the original GUI.
2. Save a full server preset in that instance.
3. Open **Startup & installation → Startup settings** in the manager, choose the
   saved preset, and optionally enable auto-start.

**Start** starts the control panel and selected saved model/server preset. **Stop**
stops both. **Restart** stops and starts both using the selected preset. **Open panel
only** is available while configuring an instance. Closing the manager browser tab
does not stop the manager or its instances.

Control panels bind to `0.0.0.0`. New instances include a normal **Manager defaults**
preset containing their assigned inference port; **Open instance** loads that preset
until another startup preset is selected. Saved presets retain their own ports.
If a preset's port is occupied, the manager reports the conflict instead of changing it.

Use **LAN servers** to discover and connect other running managers, or enter their
address manually. Connected servers expose the same lifecycle controls and loaded
preset/model display. Detailed controls open in the original remote instance.
Connections use plain HTTP without authentication or encryption.

The Monitor adds per-instance values directly for its combined and per-server cards.
Reset session counters resets the displayed baselines, without interrupting inference.
Monitor card order/visibility, themes, and navigation preferences are saved in the browser.

## Updates and removal

**Settings → Check for updates** links to this fork's latest Windows installer.
Run it to update the manager. Each independent LLama-GUI instance still updates
through its original upstream installer and app-update controls.

Manager settings are stored under `%LOCALAPPDATA%\llama.cpp Instance Manager`.
Instances default to its `instances` subfolder but can be installed elsewhere.
Removing an instance from the manager leaves its files on disk. Uninstalling the
manager preserves its settings, instances, and models. Each instance directory
includes an **Open instance.cmd** launcher alongside its upstream checkout.

## Build the Windows installer

```powershell
.venv\Scripts\python -m pip install pyinstaller==6.22.3
.\scripts\build.ps1
```

The build requires Inno Setup 6 (`-Iscc <path>` overrides its location), verifies
the pinned runtime checksums, and produces `dist/*-setup.exe` plus `SHA256SUMS.txt`.
GitHub Actions builds and publishes tagged `v*` releases.

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run_manager.py
```

Source runs also need Git and Node on PATH. Windows releases bundle their runtimes.
See [architecture](docs/directory.md) and [verification](docs/tests.md).

## Attribution

Based on the menus and monitoring of Thomas9120's LLama-GUI. Theme tokens,
inference-stat calculations, and logo assets are reused under GPL-3.0.
The original application's source remains available in this repository's history.
This manager is also GPL-3.0; see [LICENSE](LICENSE).
