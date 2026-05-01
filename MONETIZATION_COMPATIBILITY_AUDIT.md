# Monetization Compatibility Audit

Date: 2026-03-09

## Summary

The current AI Meeting Manager plugin architecture is strong enough to support a future commercial
plugin platform, but before this change set it lacked the distribution and entitlement layer needed
for productized delivery.

## What already matched the target model

- manifest-driven plugin discovery
- hook-based runtime with no hardcoded plugin list in core logic
- plugin UI metadata already stored in `plugin.json`
- plugin settings and health checks already centralized
- plugin catalog and plugin registry services already exist
- plugin validation CLI already exists

These are the right foundations for a catalog-driven marketplace.

## Main gaps before implementation

### 1. No distinction between bundled and installed plugins

All discovered plugins were effectively treated as `installed = true`, with a single local plugin
root. That prevented a clean split between:

- bundled baseline plugins
- locally installed optional plugins
- future catalog-only plugins

### 2. No entitlement model

The runtime had no concept of:

- platform edition
- plugin purchase/subscription state
- locked vs entitled plugins
- revocation or grace periods

### 3. No product policy file

There was no repository-level contract defining:

- which plugins belong to the free baseline bundle
- which plugins require platform unlock
- which plugins are paid/subscription candidates

### 4. No local install metadata

There was no canonical file describing optional plugin installations, versions, and runtime state.

### 5. UI could not represent product states

Plugin UI only knew:

- installed
- enabled
- disabled

It could not distinguish:

- core included
- platform locked
- purchase required
- subscription required
- grace period

## Implemented foundation in this change set

- added `distribution` section support in plugin manifests
- added `PluginDistributionResolver`
- added local product policy files:
  - `config/plugin_distribution.json`
  - `config/plugin_entitlements.json`
  - `config/installed_plugins.json`
- added separate `config/plugins_installed/` root for optional local installs
- updated discovery and runtime loader to scan multiple plugin roots
- surfaced access metadata in catalog/UI/CLI

## Remaining gaps after this change set

- no remote catalog client yet
- no package download/install/update commands yet
- no signature verification yet
- no signed third-party submission flow yet
- no edition login/account flow yet
- no automatic fallback orchestrator yet

## Conclusion

The plugin architecture itself was already compatible with monetization. The missing piece was not
the hook model; it was the product/distribution layer around it. This repository now has the local
contracts needed to build that layer without violating the core rule that `aimn.core` and
`aimn.ui` must not know specific plugins by hardcoded ids.
