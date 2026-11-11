# Instance Manager

This repository packages independent, unmodified installations of
thomas9120/LLama-GUI. Do not patch those installations or redirect their updates.
Only the manager and installer update from this fork.

Read docs/directory.md and docs/tests.md before substantial changes.
Keep the manager small. LAN discovery and control use plain HTTP without auth.
Reuse upstream theme tokens and menu interactions. No fact-checking disclaimers
in product UI. Instance-facing labels say "llama.cpp instance".

Run backend tests with the project venv, `node --check` on changed JavaScript,
and `npm test` for UI changes. CI targets Windows and Linux, not macOS.
Keep upstream attribution and GPL license with reused UI assets.
