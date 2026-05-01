# Plugin Distribution And Monetization

## Product model

AI Meeting Manager should be sold in three layers.

### 1. Core Free

Core Free is a fully usable application, not an empty shell.

It includes one bundled free plugin for each required pipeline role:

- transcription
- text processing
- llm processing
- management
- service

This baseline solves the "subscription expired" problem for most roles because the app can always
fall back to a bundled baseline path.

### 2. Platform Pro

Platform Pro is the monetized unlock for extensibility.

It enables:

- browsing remote plugin catalog
- installing additional plugins
- updating installed optional plugins
- advanced plugin topology and multi-provider scenarios

### 3. Plugin entitlements

Each optional plugin has its own entitlement.

Supported plugin business models:

- free optional plugin
- paid one-time plugin
- paid subscription plugin
- first-party plugin
- third-party marketplace plugin

## Core rules

- runtime only executes local plugins
- catalog service decides what exists
- entitlement service decides what the current user can use
- core runtime only consumes the resolved access state

This keeps billing logic out of pipeline orchestration.

## Bundled baseline policy

The repository should define a baseline bundle via config rather than hardcoded branches in code.

For the current project the default baseline bundle is:

- `transcription.whisperadvanced`
- `text_processing.minutes_heuristic_v2`
- `llm.ollama`
- `management.unified`
- `service.management_index`

These plugins remain usable even when `Platform Pro` is not active.

## Optional plugin policy

Non-baseline plugins are optional by default.

Recommended default:

- optional plugins require `Platform Pro`
- free optional plugins still need platform unlock
- paid optional plugins need both platform unlock and plugin entitlement

## Marketplace policy

Third-party plugins should be distributed through a curated marketplace only.

Recommended governance:

- author submits plugin package
- package goes through review
- catalog publishes signed metadata
- entitlement service grants access
- app installs only signed compatible packages

Do not allow arbitrary zip upload into runtime.

## Subscription expiry policy

Preferred product behavior:

- when a subscription expires, the optional plugin becomes unavailable
- UI offers fallback to bundled baseline plugin for that role
- already produced artifacts stay intact
- runtime never deletes user data automatically

For sensitive state-owning roles, switching must be explicit and migration-aware.

## Distribution architecture

The platform should be split into separate concerns.

### Catalog service

Stores:

- plugin ids
- versions
- compatibility
- publisher metadata
- price model
- install/update URLs

### Entitlement service

Stores:

- edition access
- purchased plugins
- subscription state
- grace/revocation state

### Package delivery service

Delivers signed plugin packages. The physical backend may be:

- CDN
- object storage
- private registry
- GitHub Releases
- any equivalent package source

The app must not depend on GitHub specifically.

## Implementation stance for this repository

This repository should keep:

- bundled baseline plugins in `plugins/`
- locally installed optional plugins in `config/plugins_installed/`
- local install metadata in `config/installed_plugins.json`
- local product policy in `config/plugin_distribution.json`
- local entitlement snapshot in `config/plugin_entitlements.json`

That gives the application a stable local contract even before the remote marketplace backend exists.
