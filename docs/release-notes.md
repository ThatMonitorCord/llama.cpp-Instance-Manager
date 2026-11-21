llama.cpp Instance Manager 0.2.0 adds a dedicated Windows window and system tray.

* Open the dashboard from its desktop/Start menu shortcut without a browser tab.
* Close the window to keep the manager running in the tray.
* Reopen the same window from the tray or by launching the shortcut again.
* Start quietly at Windows login, with a startup toggle in the tray menu.
* Quit the manager without stopping running llama.cpp instances.
* Keep desktop theme and menu preferences between launches.
* Setup checks for WebView2 and installs Microsoft's runtime when needed.

Existing features remain available:

* Install one or several independent upstream LLama-GUI copies.
* Name your server and choose available manager, control-panel, and inference ports.
* Optionally share a models folder.
* Start at Windows login and optionally launch each instance's saved server preset.
* Discover and connect other managers on the LAN.
* Start, stop, and restart local and connected instances.
* View a unified monitor with directly summed inference counters and per-machine hardware.

Download the Windows x64 setup executable. Python, Git, and Node runtimes are included;
an internet connection is used to download the original LLama-GUI instances and their dependencies.
Choose backends and models in each instance's original control panel.

Manager updates come from this repository. Instance updates continue to come from upstream LLama-GUI.
