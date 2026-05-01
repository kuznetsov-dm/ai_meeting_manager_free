# Current Status

## Purpose

This document fixes the implementation state of `ai_meeting_manager` as of March 9, 2026.

It is an execution-status document:

- what is already working;
- what is only foundational;
- what is missing for the next product step;
- what should be implemented next.

## Executive snapshot

`ai_meeting_manager` is currently:

- a working desktop application with a real pipeline runtime;
- already strongly plugin-oriented and manifest-driven;
- ready for further productization around plugin distribution and monetization;
- not yet finished as a full marketplace/catalog product.

## What is already implemented

### Core application

Implemented:

- desktop UI on `PySide6`;
- fixed pipeline runtime with plugin hooks;
- meeting storage, lineage, artifacts, and index;
- settings UI and plugin health checks;
- plugin validation CLI.

### Plugin architecture

Implemented:

- manifest-driven plugin discovery;
- hook registration and artifact contracts;
- plugin UI metadata from `plugin.json`;
- plugin settings schemas and health checks;
- local plugin registry/config.

### Distribution and monetization foundation

Implemented:

- documentation set for plugin distribution, monetization, and catalog UX;
- local product policy files:
  - `config/plugin_distribution.json`
  - `config/plugin_entitlements.json`
  - `config/installed_plugins.json`
- split between bundled plugins and locally installed plugins;
- second local install root:
  - `config/plugins_installed/`
- access-state resolution in plugin catalog:
  - core included
  - enabled/disabled
  - platform locked
  - purchase/subscription required
  - grace/revoked
- local install/update/remove backend for plugin packages;
- CLI commands for local install/update/remove;
- desktop Plugins-tab actions for local package install/update/remove.

## What is still incomplete

### Remote catalog and package delivery

Not implemented yet:

- remote plugin catalog client;
- update check against a server-side catalog;
- signed package verification;
- package manifest/checksum enforcement beyond local install basics.

### Entitlements and commercial flow

Not implemented yet:

- real backend entitlement sync;
- login/account/session model for edition access;
- subscription renewal/revocation flow from a backend;
- curated marketplace submission/review flow.

### Safer product UX

Still missing:

- uninstall safety checks against active presets/config usage;
- downgrade/fallback guidance when access is lost;
- richer plugin-card actions for catalog-driven install/update;
- compatibility filtering against remote app/plugin versions.

## Current risks

### 1. Product layer is local-only

The monetization/distribution model exists locally in config and code, but not yet in a live remote service.

### 2. Package validation is still lightweight

Local install/update works, but cryptographic verification and strict package manifests are still future work.

### 3. Plugin UX is ahead of backend commerce

The desktop UI can already manage local plugin packages, but marketplace-grade flows are not yet connected.

## Nearest development steps

The next recommended implementation order is:

1. Add package manifest + checksum/signature verification to local install/update.
2. Add uninstall/update safety checks when a plugin is referenced by active config.
3. Build remote plugin catalog client with cached index and compatibility filtering.
4. Add entitlement sync from backend into `plugin_entitlements.json` shape.
5. Connect Plugins tab to remote catalog actions, not only local package files.
6. Add curated marketplace workflow for third-party plugins.

## Definition of the current checkpoint

At this checkpoint, `ai_meeting_manager` already has the right plugin architecture and a real local
plugin distribution layer. The next phase is no longer core refactoring; it is remote catalog,
entitlement, and marketplace integration.
