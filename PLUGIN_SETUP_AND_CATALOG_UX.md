# Plugin Setup And Catalog UX

## Goal

AI Meeting Manager should remain usable out of the box, while making the plugin platform
discoverable, installable, and monetizable without putting billing logic into core runtime code.

The UX model is:

- `Core Free` ships with one bundled baseline plugin for every required pipeline role.
- `Platform Pro` unlocks optional plugin installation and advanced topology.
- Extra plugins may be free, one-time, or subscription-based.
- The app always runs only locally installed plugins.
- A remote catalog may be used to discover and download plugins, but not to execute them directly.

## First-run experience

### 1. Welcome

The user sees:

- what ships in the free core bundle
- whether `Platform Pro` is active
- whether plugin updates are available

Actions:

- `Start with bundled core`
- `Sign in to unlock plugin catalog`
- `Review installed plugins`

### 2. Baseline pipeline review

The baseline bundle is shown as a complete runnable stack:

- `transcription.whisperadvanced`
- `text_processing.minutes_heuristic_v2`
- `llm.ollama`
- `management.unified`
- `service.management_index`

The user can start processing immediately without marketplace access.

### 3. Plugin catalog

When `Platform Pro` is active, the app shows a remote catalog with:

- installed plugins
- bundled baseline plugins
- free optional plugins
- paid one-time plugins
- subscription plugins
- updates for already installed plugins

Each plugin card must show:

- product name
- stage/role
- owner
- price model
- install state
- entitlement state
- compatibility with current app version

## Plugin card states

States visible in UI:

- `Core included`
- `Enabled`
- `Disabled`
- `Platform locked`
- `Purchase required`
- `Subscription required`
- `Grace period`
- `Access revoked`
- `Not installed`

These states are resolved from local install state plus entitlement state. Runtime must not invent
billing rules on its own.

## Install flow

### Install optional plugin

1. User opens catalog.
2. User selects plugin.
3. App checks:
   - app version compatibility
   - required edition
   - entitlement
   - package signature/checksum
4. App downloads the package.
5. App installs it into `config/plugins_installed/<plugin_id>/`.
6. App updates `config/installed_plugins.json`.
7. Plugin appears in the local plugin catalog after restart or live refresh.

## Re-run / periodic check

Every repeated app start may do a lightweight catalog sync:

- fetch updated plugin index
- compare installed versions
- detect new compatible plugins
- detect revoked/expired entitlements

The sync must not block normal startup. If catalog is unavailable, bundled and already installed
plugins remain usable.

## Subscription expiration

Normal behavior for most roles:

- if a paid optional plugin expires, the app disables it
- if a bundled baseline plugin exists for the same role, UI offers a switch back to that baseline

Sensitive exception:

- `primary canonical stores` or similar stateful ownership roles must not auto-switch silently
- the user must confirm any migration

For AI Meeting Manager this exception mostly matters for future externalized storage/services,
not for the current local pipeline stages.

## How new plugins appear

There are two discovery layers.

### 1. Local install roots

Already installed plugins appear automatically when their `plugin.json` is present in one of:

- bundled `plugins/`
- local `config/plugins_installed/`

The app scans these folders on every reload. No hardcoded plugin list is allowed in core/UI.

### 2. Remote catalog

New installable plugins appear when the remote catalog advertises them.

Recommended flow:

1. Catalog returns metadata only.
2. User chooses plugin in UI.
3. App downloads package from package delivery service or CDN.
4. Package is installed locally.
5. Local discovery picks it up as a normal plugin.

This keeps runtime deterministic and offline-tolerant.

## Why remote code must not run directly

The app must not import Python code from GitHub or any remote endpoint during normal runtime.

Reasons:

- reproducibility
- security
- signature verification
- offline resilience
- rollback support
- predictable support and debugging

Remote catalog is for discovery and delivery, not execution.
