# Plugin Catalog And Entitlement API

## Purpose

This document defines the minimal remote contracts required by AI Meeting Manager to support:

- plugin discovery
- install/update checks
- entitlement checks
- downgrade and revocation handling

The remote catalog is not part of runtime execution. It is only a discovery and delivery layer.

## Remote catalog response

Recommended response shape:

```json
{
  "catalog_version": "2026-03-09",
  "app_id": "ai_meeting_manager",
  "plugins": [
    {
      "plugin_id": "llm.openrouter",
      "version": "1.4.0",
      "api_version": "1",
      "stage_id": "llm_processing",
      "owner_type": "first_party",
      "pricing_model": "free",
      "requires_platform_edition": true,
      "compatible_app_versions": [">=0.1.0"],
      "download_url": "https://cdn.example/plugins/llm.openrouter-1.4.0.zip",
      "checksum_sha256": "abc123",
      "signature": "base64-signature",
      "signature_algorithm": "rsa-sha256",
      "signing_key_id": "primary",
      "manifest_url": "https://cdn.example/plugins/llm.openrouter-1.4.0-manifest.json"
    }
  ]
}
```

## Entitlement response

Recommended response shape:

```json
{
  "subject_id": "user_123",
  "edition": "platform_pro",
  "platform_edition": {
    "enabled": true,
    "status": "active"
  },
  "plugins": {
    "service.reference_webhook": {
      "status": "active",
      "expires_at": null
    },
    "service.prompt_manager": {
      "status": "grace",
      "expires_at": "2026-04-01T00:00:00Z"
    }
  },
  "_meta": {
    "publisher_id": "apogee",
    "signature_algorithm": "rsa-sha256",
    "signing_key_id": "primary",
    "signature": "base64-signature"
  }
}
```

Allowed plugin statuses:

- `active`
- `grace`
- `expired`
- `revoked`

## Package manifest

Each downloadable package should include a package manifest separate from the plugin runtime
manifest.

Recommended package manifest:

```json
{
  "plugin_id": "llm.openrouter",
  "version": "1.4.0",
  "api_version": "1",
  "entrypoint": "llm_openrouter.plugin:Plugin",
  "install_root": "config/plugins_installed/llm.openrouter",
  "files": [
    {
      "path": "plugin.json",
      "sha256": "abc123"
    }
  ]
}
```

## Local installed state

`config/installed_plugins.json` is the local truth for installed optional packages.

Recommended shape:

```json
{
  "version": "1",
  "plugins": {
    "llm.openrouter": {
      "installed_version": "1.4.0",
      "source": "catalog",
      "runtime_state": "active",
      "installed_at": "2026-03-09T10:00:00Z"
    }
  }
}
```

Allowed runtime states:

- `active`
- `grace`
- `revoked`
- `fallback_required`

## Local product policy

`config/plugin_distribution.json` defines repository-shipped defaults:

- bundled baseline plugin ids
- default platform gating for optional plugins
- pricing and ownership overrides
- whether a plugin is expected to appear in remote catalog

`config/plugin_entitlements.json` is the local entitlement snapshot consumed by runtime/UI.

In a future commercial build this file should be refreshed from a backend, but the file contract can
remain the same.

`config/plugin_sync.json` may define local sync endpoints:

```json
{
  "catalog_url": "https://api.example/catalog.json",
  "entitlements_url": "https://api.example/entitlements/user_123.json"
}
```

## Install flow

1. App fetches remote catalog.
2. User selects plugin.
3. App validates entitlement.
4. App downloads package.
5. App verifies checksum and signature.
6. App installs package into `config/plugins_installed/<plugin_id>/`.
7. App writes `installed_plugins.json`.
8. Local plugin discovery loads the plugin.

## Update flow

1. App compares local installed version to remote catalog version.
2. If compatible and entitled, app offers update.
3. App downloads and validates new package.
4. App replaces installed package atomically.
5. App updates `installed_plugins.json`.

## Revocation / expiry flow

1. Entitlement sync marks plugin as `expired` or `revoked`.
2. Runtime resolves plugin as unavailable.
3. UI offers fallback to bundled baseline plugin if one exists.
4. Existing artifacts remain untouched.

## Signing key rotation

Publisher trust policy can expose more than one active verification key:

```json
{
  "publishers": {
    "apogee": {
      "trust_level": "first_party",
      "require_signature": true,
      "signature_keys": [
        {
          "key_id": "primary",
          "algorithm": "rsa-sha256",
          "public_exponent": "65537",
          "modulus_hex": "..."
        },
        {
          "key_id": "rotated_2026",
          "algorithm": "rsa-sha256",
          "public_exponent": "65537",
          "modulus_hex": "..."
        }
      ]
    }
  }
}
```

Catalog entries and entitlement bundles should reference the active key via `signing_key_id`.
