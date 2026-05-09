# Core Free Portable Backlog

Scope: issues observed during the portable release install and first pipeline run.

Explicit non-goal: do not add a Whisper fallback that retries with `--no-gpu` or CPU-only mode.

## P0 - Release Blockers

- [x] Fix remaining portable embeddings/LLM issues from `logs (5)`.
  - [x] Move `text_processing.semantic_refiner` and `text_processing.minutes_heuristic_v2` back to the `text_processing` UI stage.
  - [x] Make `semantic_refiner` load without a top-level `huggingface_hub` import.
  - [x] Prevent cascading Hugging Face progress-bar errors after a certificate failure in the installer.
  - [x] Include embeddings runtime packages in the portable app PyInstaller bundle.
  - [x] Align release text-processing settings with the E5 embeddings model catalog.
  - [x] Increase portable llama context from `4096` to `32768` and keep single-pass processing without chunking.

- [x] Replace bundled Whisper runtime with the known-working `whisper_cpp` runtime set.
  - Source verified: `C:\Users\dmitry\Documents\GitHub\whisper_cpp`.
  - Files replaced: `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`, `ggml-vulkan.dll`, `mtmd.dll`, `whisper.dll`, `whisper-cli.exe`.
  - Rebuilt portable installer and verified payload hashes.

- [x] Fix installer wizard selection controls.
  - Settings choices must be single-select: UI language, theme, transcription language.
  - Model choices must support multi-select where useful: Whisper, embeddings, summary/LLM.

- [x] Normalize installer wizard language.
  - Remove mojibake and mixed Russian/English copy from the installer UI.
  - Keep all wizard text in one language per screen/session.
  - Ensure button labels, warnings, final status, and model download messages are readable.

- [x] Make optional model downloads non-fatal in the installer.
  - SSL/Hugging Face failures must not mark the whole installation as failed.
  - Final result should distinguish app installation from optional model download failures.
  - Keep enough error detail for troubleshooting certificate/proxy problems.

- [x] Preserve working app downloader behavior.
  - Compare installer downloader with in-app model download code.
  - Avoid changing the application download path unless required.
  - Scope kept to installer diagnostics and installer-only optional download handling.

- [x] Add release validation for Whisper runtime.
  - [x] Validate the 7 packaged Whisper files exist.
  - [x] Validate packaged file sizes are non-zero.
  - [x] Run `whisper-cli.exe --help`.
  - [x] Validate `--print-progress` is supported by the packaged CLI.
  - [x] Add a short real transcription smoke test with bundled tiny model.

## P1 - Installer UX

- [x] Add application icon to built executables.
  - `AI Meeting Manager Core Free.exe`
  - `AI Meeting Manager Free Portable Installer.exe`

- [x] Add desktop shortcut creation.
  - Shortcut should point to installed `AI Meeting Manager Core Free.exe`.
  - Shortcut should use the application icon.
  - Installer should expose a clear checkbox for creating the shortcut.

- [x] Improve installer completion state.
  - Show "Installed" even if optional downloads failed.
  - Show "Models can be downloaded later in Settings".
  - Launch app only after install succeeds.

## P1 - Application UX

- [x] Add embedding model management to semantic plugin settings.
  - Provide download/remove/select actions like Whisper and LLM settings.
  - Cover at least `intfloat/multilingual-e5-small` and `intfloat/multilingual-e5-base`.
  - Keep the implementation plugin-owned; core/UI must not branch on specific plugin IDs.

- [x] Change missing-plugin stage status copy.
  - Missing/unconfigured plugin stages should not read as hard failures.
  - Use motivational/neutral copy such as `Add plugin`, `Configure plugin`, or `Not configured`.
  - Preserve real runtime failures as `failed`.

- [x] Fix transcription progress reporting.
  - Investigate why percent progress does not move.
  - Use timestamp-based progress from `whisper-cli` output when available.
  - Show elapsed/working state when exact percent is unavailable.

- [x] Improve search exit UX.
  - Add an obvious way to return from search results to the previous non-search view.
  - Candidate controls: `Back`, `Clear search`, breadcrumb, or Esc handling.
  - Restore the previous meeting/result view after clearing global search.

## P2 - Hardening

- [x] Add release checklist documentation.
  - Installer wizard language pass.
  - Single/multi-select behavior pass.
  - Optional download failure pass with network/SSL failure simulation.
  - Desktop shortcut and icon pass.
  - Pipeline smoke pass with bundled models.

- [x] Improve installer download diagnostics.
  - Surface certificate/proxy hints for `CERTIFICATE_VERIFY_FAILED`.
  - Log exact model id, URL/repo id, target path, and whether install continued.

## Progress Log

- 2026-05-07: Replaced bundled Whisper runtime, rebuilt portable installer, verified payload file hashes.
- 2026-05-07: Started P0 installer wizard and download-flow fixes.
- 2026-05-07: Fixed installer single-select settings, multi-select model choices, English wizard copy, and non-fatal optional model download errors.
- 2026-05-07: Added `.ico` asset, wired PyInstaller icons, and added optional desktop shortcut creation.
- 2026-05-08: Fixed portable Whisper progress by explicitly passing `--print-progress` when progress callbacks are active.
- 2026-05-08: Added explicit `Back to text` global-search exit control.
- 2026-05-08: Changed missing-plugin UI state to neutral `Add plugin` copy without masking runtime failures.
- 2026-05-08: Added semantic embedding model management via plugin-owned actions and metadata.
- 2026-05-08: Added release validation for required Whisper runtime files and `--print-progress` CLI support.
- 2026-05-08: Added tiny-model Whisper CLI smoke validation, release checklist docs, and richer installer download diagnostics.
- 2026-05-09: Reviewed `logs (5)`: Whisper transcription succeeded; remaining failures were embeddings runtime/download issues and llama `ctx_size=4096`.
- 2026-05-09: Fixed text plugin stage metadata, hardened Hugging Face installer downloads, bundled embeddings runtime dependencies, and raised portable llama context to 32768 without chunking.
