# Verification

Create a project venv, then install `requirements.txt`.

* `.venv/Scripts/python.exe -m unittest discover -s tests -v` (Windows)
* `.venv/bin/python -m unittest discover -s tests -v` (Linux)
* `node --check manager/web/app.js`
* `node --check manager/web/monitor.js`
* `node --check manager/preset_bridge.cjs`
* `npm ci && npm test`: monitor arithmetic and browser interactions.

CI runs on Windows and Linux. Windows release builds bundle portable Python,
Git, and Node, freeze the manager, and compile the Inno Setup executable.
Native two-machine LAN discovery and GPU inference require physical hosts.

Opt-in real integration checks (Windows, with downloads):

* `python scripts/prepare_runtimes.py`
* `.venv/Scripts/python scripts/smoke_upstream.py`: two unmodified upstream copies,
  independent runtime files, clean Git status, CPU backend installation, a tiny
  test model, preset compilation, inference counters, and independent restart.
* After building: `.venv/Scripts/python scripts/smoke_packaged.py`: two packaged
  managers, auto-start, UDP discovery, direct federation, and remote lifecycle.

Integration artifacts stay under `.test-data`; test processes stop on exit.
These scripts do not configure Windows login startup or firewall rules.

* `.venv/Scripts/python scripts/smoke_installer.py`: silent clean setup, installed
  executable startup, upgrade, and uninstall in an isolated workspace directory.
  Refuses to overwrite an existing user installation. Runs in release CI.

## Initial release verification (2026-11-11)

* 17 backend tests, 3 monitor arithmetic tests, and 4 Playwright browser tests passed.
* Windows and Linux CI passed.
* Two independent upstream checkouts installed successfully, remained clean, and
  retained `https://github.com/thomas9120/LLama-GUI.git` as their origin.
* Two CPU llama-server processes ran `stories260K.gguf`, launched through saved
  presets using the original flag compiler. Inference, metrics, slots, and
  independent restart passed with upstream CPU build b12282.
* Two packaged manager processes passed automatic preset startup, local UDP
  discovery, direct federation, remote stop/start/restart, and preset identity
  recovery after restarting the manager while inference continued.
* The Windows setup installed, upgraded, started again, and uninstalled while
  preserving test settings and model files.

The LAN tests used two processes on one Windows host; separate physical hosts
and other GPU/driver combinations have not been exercised in this release run.
