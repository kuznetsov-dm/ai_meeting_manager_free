# Core Free Portable Release Checklist

Run this checklist before publishing a new portable installer.

## Installer

- [ ] Wizard text is readable and consistently localized.
- [ ] First-run settings are single-select: language, theme, transcription language.
- [ ] Model choices are multi-select where applicable: Whisper, embeddings, summary.
- [ ] Optional model download failures do not fail the installation.
- [ ] SSL/proxy failure report includes model id, source URL/repo, target path, and continuation status.
- [ ] Finish page says the app is installed when only optional downloads failed.
- [ ] Desktop shortcut is created when the checkbox is enabled.
- [ ] App and installer executables show the application icon.

## Runtime

- [ ] `validate_core_free.ps1 -StagingRoot output_build\core_free_release` passes.
- [ ] Packaged `bin\whisper_cpp` files match the approved runtime set.
- [ ] Packaged `whisper-cli.exe --help` succeeds and exposes `--print-progress`.
- [ ] Packaged `whisper-cli.exe` smoke test succeeds with bundled `ggml-tiny.bin`.
- [ ] Transcription progress moves in the portable build.
- [ ] Pipeline run succeeds with bundled tiny Whisper model and bundled/offline settings.

## Application UX

- [ ] Search results have an obvious return path back to transcript text.
- [ ] Missing/unconfigured plugin stages show neutral action copy such as `Add plugin`.
- [ ] Real runtime failures remain visible as failures.
- [ ] Whisper, LLM, and embedding model settings expose install/select/remove actions.
