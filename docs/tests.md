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
