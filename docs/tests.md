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
