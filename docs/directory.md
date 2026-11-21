# Architecture

The manager is a small Python HTTP server and a vanilla JavaScript browser UI.
Each instance is a separate upstream Git checkout with its own Python runtime,
virtual environment, Git runtime, presets, backend files, and optional models.
No application code is written into the upstream checkout.

* `manager/config.py`: registry persistence and available-port allocation.
* `manager/instances.py`: installation, owned-process detection, lifecycle, jobs, polling.
* `manager/preset_bridge.cjs`: executes the installed upstream flag compiler using bundled Node.
* `manager/app.py`: HTTP routes, setup, direct peer connections, update checks.
* `manager/discovery.py`: UDP broadcast discovery on port 5238.
* `manager/platform.py`: Windows user-login startup.
* `manager/desktop.py`: Windows WebView2 window, tray menu, and per-profile shortcut activation.
* `manager/updates.py`: cached release metadata, numeric version comparison, verified download, and silent Windows update handoff.
* `manager/web/`: manager UI. Load order: vendor inference-stats, monitor, app.
* `installer/`: Inno Setup and pinned runtime artifacts.
* `scripts/`: Windows release build.

Manager defaults to TCP 5239; instance GUIs start at TCP 5240 and inference at
9931. Actual available ports are allocated by bind probes. All GUIs bind
0.0.0.0. Inference launch settings live in upstream saved presets.

GET routes: `/api/info`, `/api/config`, `/api/fleet`, `/api/state`, `/api/jobs`,
`/api/discovery`, `/api/ports`, `/api/presets`, `/api/logs`, `/api/update`.
POST routes: `/api/setup`, `/api/settings`, `/api/action`, `/api/startup`,
`/api/connect`, `/api/install`, `/api/disconnect`, `/api/remove`, `/api/firewall`, `/api/quit`.
`POST /api/update/apply` starts an update job for the version chosen in the sidebar.
`/api/state` includes only local instances; peers never recursively aggregate.

Settings and logs live in `%LOCALAPPDATA%\llama.cpp Instance Manager` by default.
Instance folders are outside the manager application directory. Removing an
instance from the registry preserves its files. Upgrades replace only manager
files. Upstream updates continue to use thomas9120/LLama-GUI.

On Windows the desktop runs on the main thread and HTTP runs on a worker thread.
Closing the window hides it; quitting stops the manager HTTP server and tray, not
the upstream processes. Named Windows handles prevent duplicate desktop processes
for the same data directory and signal the existing window when a shortcut is
launched again. `--background` starts hidden; `--headless` skips the desktop entirely.
WebView2 preferences live in the profile's `webview/` directory. External instance
and release links continue opening in the default browser.

The sidebar checks the fork's latest stable release on load and every six hours.
Checks are cached for one hour across clients; manual checks bypass the cache.
Only newer versions are offered. On registered Windows installations, Update
downloads the setup and SHA256SUMS.txt from the fork, verifies the installer, and
runs setup silently with the existing installation path and profile. Setup closes
the manager via `--quit` and reopens it after installation. Upstream instances
remain independent. Manual setup keeps explicit Update and Reinstall choices.
