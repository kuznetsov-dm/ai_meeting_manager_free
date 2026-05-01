# Distribution And Monetization Backlog

Date: 2026-03-09

## Completed foundation

- Added local product policy files for plugin distribution and entitlements.
- Added second local install root `config/plugins_installed/`.
- Added access-state resolution for bundled vs optional plugins.
- Exposed monetization metadata in plugin catalog, UI, and CLI.
- Documented product model, UX, API contracts, and compatibility audit.
- Added local plugin package install/update/remove backend.
- Added desktop Plugins-tab actions for local package install, update, and remove.

## Next implementation steps

### Phase 1: local installer/runtime hardening

- Add checksum verification before activation.
- Add package manifest schema beyond raw `plugin.json`.
- Add uninstall safety checks for plugins still referenced by active presets/config.
- Add atomic package extraction and rollback.
- Add `plugin_runtime_state.json` if per-plugin runtime downgrade state becomes necessary.

### Phase 2: remote catalog integration

- Add remote catalog client with cache and offline fallback.
- Add update check scheduler on app startup.
- Add compatibility filtering by app version and platform.
- Add UI actions for install/update/remove.

### Phase 3: entitlements and billing

- Replace local entitlement snapshot with backend sync.
- Add login/session model for platform edition.
- Add one-time and subscription purchase flows.
- Add grace period and revocation refresh logic.

### Phase 4: marketplace

- Add curated third-party submission flow.
- Add package signing pipeline.
- Add moderation/review status in catalog.
- Add publisher metadata and revenue-share reporting.

### Phase 5: fallback UX

- Add explicit fallback recommendations when an optional plugin loses access.
- Add safe migration flow for future state-owning plugins.
- Add baseline reset action in UI.
