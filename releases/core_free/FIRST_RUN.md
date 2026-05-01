# Core Free First Run

This guide is for a clean Windows machine and the staged `core_free` bundle.

## What is included

- local transcription via `transcription.whisperadvanced`
- local LLM runtime via `llm.llama_cli`
- semantic processing via:
  - `text_processing.minutes_heuristic_v2`
  - `text_processing.semantic_refiner`

## What is not included

- no bundled llama `.gguf` model
- no plugin marketplace/package install UI
- no bundled management/service plugins

## What is bundled for quick start

- `Whisper Tiny` ASR model is already included and ready to use
- the Whisper VAD support model is included
- no llama `.gguf` model is bundled, but two starter download options are preconfigured

## Before launch

This staged bundle still launches from Python source.

You need one of:

- `py -3.11`
- `py -3`
- `python`

If Python is not available on the machine yet, install Python 3.11+ first.

## Recommended launch

Use one of these files from `releases/core_free/`:

- `Launch-Core-Free.cmd`
- `Launch-Core-Free.ps1`

You can also launch `run_ui.py` directly if Python is already configured.

## What the user sees on first run

1. The app starts with the `core_free` release profile enabled.
2. `Settings > AI Processing` defaults to:
   - transcription: `transcription.whisperadvanced`
   - local LLM: `llm.llama_cli`
3. `Settings > Transcription` starts with bundled `Whisper Tiny` ready for a first transcription run.
4. The LLM section shows a setup card because no GGUF model is bundled.
5. The user can continue using semantic processing even before configuring llama.

## How to use Whisper on first run

The base release already includes the local whisper.cpp runtime and bundled `Whisper Tiny`.

On first use:

1. Open `Settings > Transcription`.
2. Keep `tiny` for the first smoke test or switch to another model later.
3. Run transcription immediately.
4. If better quality is needed later, download another Whisper model from the built-in list.

## How to configure llama.cpp

The product supports exactly three model setup paths:

1. Add a model from the built-in catalog and download it.
2. Add a custom direct `.gguf` URL.
3. Select an existing local `.gguf` file.

After model setup, rerun AI processing and the local LLM output should appear without changing the release profile.

## Expected fallback behavior before llama model setup

- the app must still start normally
- transcription must work immediately with bundled `Whisper Tiny`
- transcription settings must still show the Whisper model list and download path for upgrades
- semantic processing must still produce useful edited/minutes output

## Where data is stored

By default the staged bundle writes data inside the bundle root:

- `config/`
- `output/`
- `models/llama/`

If needed, you can override the app root with `AIMN_HOME`.

## Reset to a clean state

To simulate a fresh machine/user inside the staged bundle, remove these folders from the bundle root:

- `config/settings/`
- `output/`
- `models/llama/`

Do not remove these bundled runtime files unless you want to break the starter setup:

- `models/whisper/ggml-tiny.bin`
- `models/whisper/ggml-silero-v6.2.0.bin`

Do not remove `releases/core_free/config/`; that is the release overlay itself.
