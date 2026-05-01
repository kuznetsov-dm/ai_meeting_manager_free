# Core Free Backlog

## P0

1. Introduce a release-profile mechanism in app code.
   - Add `core_free` as a first-class profile.
   - Make UI and CLI aware of profile-specific visibility rules.

2. Remove `transcription.whispernext` from the repository.
   - Delete plugin files.
   - Remove config, docs, and tests references.

3. Enforce the bundled plugin set for `core_free`.
   - Keep:
     - `transcription.whisperadvanced`
     - `llm.llama_cli`
     - `text_processing.minutes_heuristic_v2`
     - `text_processing.semantic_refiner`
   - Exclude:
     - all `management.*`
     - all `service.*`
     - all `integration.*`
     - cloud `llm.*` except `llm.llama_cli`

4. Hide free-release unsupported UI.
   - Keep the fixed `management` stage in pipeline compatibility paths.
   - Decide whether Management tab stays visible as an empty/no-op surface or is
     hidden only at the shell level.
   - Hide Plugins tab entirely or make it read-only.
   - Remove plugin package install/update/remove actions in `core_free`.

5. Make `llm.llama_cli` first-run ready without a bundled model.
   - Keep bundled binary/runtime.
   - Provide model download/select UX from Settings.
   - Support custom URL and local file path.
   - Do not require external programs.

## P1

1. Add release-specific packaging pipeline.
   - Build staging directory for `core_free`.
   - Copy release overlay config into staging.
   - Bundle only allowed plugins and binaries.

2. Add release validation.
   - Ensure no `whispernext` files are included.
   - Ensure `platform_pro_dev` is not present.
   - Ensure management/service plugins are not bundled.
   - Ensure `llm.llama_cli` remains configured with `gpu_layers = -1`.

3. Add smoke tests for `core_free`.
   - clean startup
   - transcription works
   - semantic processing works without llama model
   - llama settings UI offers model acquisition options
   - no Management UI

## P2

1. Refine first-run onboarding copy for free users.
2. Add a curated recommended-model list for llama.cpp in free UI.
3. Rework docs and screenshots for the free product shape.
