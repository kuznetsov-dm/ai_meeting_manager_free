# Core Free Installer Readiness

This checklist covers the remaining work required to move from the current
Python-based staged bundle to a real end-user Windows release that does not
require Python on the target machine.

## Current state

Already done:

- `core_free` release profile exists
- staged bundle includes only the allowed plugins and local runtimes
- staged bundle launches through `releases/core_free/Launch-Core-Free.*`
- bundled llama model is excluded
- bundled Whisper ASR model is excluded
- first-run docs exist for Whisper and llama model setup
- release defaults are protected from incompatible old user settings

Current limitation:

- the staged bundle still launches from source and therefore still needs Python
  3.11+ on the target Windows machine

## Release target

Target output should provide two deliverables:

1. Portable bundle
   - unzip and run
   - no Python installation required

2. Installer build
   - standard Windows install flow
   - Start Menu/Desktop shortcuts
   - uninstall entry

## P0: Freeze the app runtime

Goal: produce a standalone executable launch path.

Required work:

- choose the packaging toolchain for Windows
  - likely `PyInstaller` first because it is the shortest path for PySide6
  - `Nuitka` can be evaluated later if startup time or binary layout becomes a problem
- create a dedicated packaging entrypoint for `core_free`
  - release profile must always be set to `core_free`
  - `AIMN_HOME` behavior must stay deterministic
- verify frozen app includes:
  - PySide6 runtime
  - `src/aimn`
  - release overlay files under `releases/core_free`
  - bundled plugins
  - bundled `ffmpeg`, `whisper.cpp`, `llama.cpp`
  - Whisper VAD support model
- verify frozen app can still locate:
  - `config/`
  - `output/`
  - `models/whisper/`
  - `models/llama/`

Acceptance:

- the app starts on a clean Windows machine without Python installed
- `core_free` profile is active automatically

## P1: Freeze-safe path resolution

Goal: make runtime path lookup robust in a frozen executable layout.

Required work:

- audit all path resolution code that assumes repo/source layout
  - `run_ui.py`
  - `app_paths.py`
  - plugin runtime path helpers
  - launcher scripts
- introduce one canonical “bundle root” resolution rule for:
  - source mode
  - staged bundle mode
  - frozen executable mode
- verify bundled binaries are found through relative paths in frozen mode
- verify release overlay config is still resolved in frozen mode

Acceptance:

- no path in startup/runtime depends on `src` existing as a normal source tree

## P2: Windows installer packaging

Goal: turn the standalone bundle into a standard Windows installable package.

Required work:

- choose installer technology
  - Inno Setup is the pragmatic first choice
  - WiX is possible later if MSI becomes mandatory
- prepare installer payload layout
  - app files
  - release guide
  - local model directories
  - writable user data location strategy
- define install mode:
  - per-user install recommended first
  - machine-wide install only if needed later
- add shortcuts:
  - Start Menu
  - optional Desktop shortcut
- add uninstall path
- add versioned app metadata:
  - product name
  - version
  - publisher
  - icon

Acceptance:

- fresh install works from standard Windows UI
- uninstall removes app files cleanly without touching user data unexpectedly

## P3: Portable bundle hardening

Goal: keep a zip-distributed portable variant in addition to the installer.

Required work:

- decide whether portable mode writes inside bundle root or inside user profile
- document reset/cleanup flow for portable mode
- verify portable bundle survives moving to another folder/drive
- verify no absolute dev paths remain in shipped defaults

Acceptance:

- portable zip build can be unpacked anywhere and started immediately

## P4: First-run production polish

Goal: make first-run understandable on a real user machine.

Required work:

- replace developer-style launcher messaging with production copy
- show first-run guidance in the app itself, not only in markdown files
- clearly separate:
  - Whisper model setup
  - local LLM model setup
  - semantic fallback availability
- show actionable error states for:
  - no Whisper model downloaded
  - no llama model configured
  - missing DLL/binary runtime issues

Acceptance:

- first-time user can reach working transcription without reading internal docs

## P5: Signing and release trust

Goal: avoid SmartScreen and trust issues on Windows.

Required work:

- code-sign executable/binaries
- sign installer
- define release versioning and changelog process
- define checksum publication for portable archives

Acceptance:

- release artifacts are signed and traceable

## P6: Final release QA

Goal: run the last pass against the real packaged artifact.

Required work:

- test on a clean Windows machine without Python
- verify first run with no Whisper model
- verify Whisper model download and successful transcription
- verify first run with no llama model
- verify semantic processing still works before llama setup
- verify llama model download / custom URL / local file flow
- verify `Management` and `Service` compatibility empty states
- verify logs and crash handling
- verify uninstall / reinstall / upgrade behavior

Acceptance:

- QA sign-off on installer and portable bundle

## Recommended implementation order

1. Freeze the app runtime.
2. Make path resolution frozen-safe.
3. Produce a portable no-Python bundle.
4. Add installer packaging.
5. Run clean-machine QA.
6. Only after that, polish signing and public release packaging.

## Practical next step

The next concrete engineering task is:

- add the first standalone packaging script for `core_free`

That script should produce a no-Python portable Windows bundle first. The
installer should come only after the frozen portable build is stable.
