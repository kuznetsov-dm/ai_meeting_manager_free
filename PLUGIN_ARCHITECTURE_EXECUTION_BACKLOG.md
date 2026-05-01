# Plugin Architecture Execution Backlog

This backlog covers the current implementation iteration for plugin lifecycle hardening and
activation foundations. It is intentionally scoped to items that can be completed in the current
codebase without introducing a remote marketplace backend.

## Goals

- Harden plugin package install/load against malformed or malicious manifests/packages.
- Preserve plugin sandboxing guarantees for async actions.
- Separate user activation state from distribution/entitlement state.
- Introduce catalog/runtime lifecycle states needed for bundled hidden plugins and future paid
  unlock flows.

## Backlog

Status: completed for this iteration.

1. Runtime manifest validation
- Enforce plugin id and entrypoint validation in runtime manifest loading.
- Reject malformed manifests during install/load even when CLI schema validation is unavailable.

2. Package install safety
- Block path traversal through plugin ids used as install targets.
- Replace unsafe zip extraction with path-checked extraction.
- Keep installed plugin metadata consistent after safe install.

3. Secret namespace hardening
- Remove cross-plugin secret collisions caused by suffix-only secret prefixes.
- Preserve backward-compatible reads for existing secret/env names.

4. Async isolation correctness
- Ensure async actions still honor subprocess isolation for untrusted plugins.
- Add tests that prove isolated async execution bypass no longer happens.

5. Activation lifecycle foundation
- Add a dedicated activation store separate from registry/distribution/entitlements.
- Derive catalog/runtime states from presence + entitlement + activation.
- Default newly installed plugins to `available_inactive` instead of silently auto-activating.
- Wire Plugins UI toggles to activation state rather than mutating registry semantics directly.

6. Verification
- Add/extend unit tests for the cases above.
- Run focused test suites for package install, secret storage, activation/catalog state, and async
  plugin actions.

## Completed Verification

- `python -m pytest apps/ai_meeting_manager/tests/unit/test_plugin_package_service.py apps/ai_meeting_manager/tests/unit/test_secret_storage_encryption.py apps/ai_meeting_manager/tests/unit/test_plugin_manager_async_jobs.py apps/ai_meeting_manager/tests/unit/test_plugin_activation_service.py -q`
- `python -m pytest apps/ai_meeting_manager/tests/unit/test_plugin_distribution.py apps/ai_meeting_manager/tests/unit/test_plugin_catalog_options.py apps/ai_meeting_manager/tests/unit/test_plugin_manifest.py apps/ai_meeting_manager/tests/unit/test_plugin_policy.py apps/ai_meeting_manager/tests/unit/test_model_list_action_contract.py -q`
- `python -m pytest apps/ai_meeting_manager/tests/unit/test_global_search_controller.py apps/ai_meeting_manager/tests/unit/test_plugin_health_service.py -q`
- `python -m pytest apps/ai_meeting_manager/tests/unit/test_plugin_remote_catalog.py -q`
- `python -m ruff check --select I ...` on all modified files

## Additional Completed Work

- Added local remote-catalog snapshot support from `config/plugin_catalog.json`.
- Merged remote catalog entries into the Plugins catalog/UI as `remote_only` lifecycle entries.
- Added remote metadata overlay for installed plugins so the catalog can surface `update_available`.
- Extended Plugins UI lifecycle handling for `installable`, `installable_locked`, and `update_available`.
- Added checksum and detached `rsa-sha256` signature verification for installable third-party packages.
- Added `plugin_trust_policy.json` support with publisher trust levels (`first_party`,
  `trusted_third_party`, `untrusted_local`) and automatic runtime isolation for untrusted plugins.
- Persisted install-time verification metadata into `installed_plugins.json` and surfaced it into the
  catalog/runtime descriptors.
- Added signed entitlement validation for `plugin_entitlements.json`; unsigned or tampered PRO
  entitlements are stripped before distribution access is resolved.
- Hardened Core Free / locked release behavior so `plugin_distribution.json` and
  `plugin_trust_policy.json` prefer the bundled release config over mutable local overrides.
- Added direct catalog install/update flow from `download_url` into `PluginPackageService`,
  CLI (`aimn plugin install-remote`), and Plugins UI.
- Added publisher key rotation support via multiple `signature_keys` and `signing_key_id` for both
  remote package verification and signed entitlements.
- Added `PluginSyncService` with local/HTTP catalog sync and signed entitlement import/sync.
- Added Plugins UI controls for `Sync catalog` and `Import license` so PRO unlock no longer depends
  on hand-editing config files.

## Out Of Scope For This Iteration

- Full publisher PKI / rotation workflow and installer-side key provisioning UX.
- Signed remote catalog snapshot verification at the whole-catalog level.
- Per-user billing/account flows.
