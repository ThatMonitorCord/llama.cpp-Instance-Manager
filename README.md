# llama.cpp Instance Manager

A Windows installer and LAN dashboard for independent
[LLama-GUI](https://github.com/thomas9120/LLama-GUI) installations.

Choose how many **llama.cpp instances** to install, assign available control-panel
and inference ports, and optionally share a models folder. Each instance has its
own upstream checkout, runtime, environment, backend files, and updates.

The manager provides saved-preset startup, local and LAN start/stop/restart,
automatic LAN discovery, and a combined inference monitor. Detailed configuration,
backend/model installation, and chat remain in each original instance.

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
