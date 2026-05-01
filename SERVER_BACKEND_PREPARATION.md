# Server Backend Preparation For Plugin Catalog And PRO Entitlements

## Purpose

This document describes how to prepare the server side for the plugin catalog, signed package
distribution, and signed PRO unlock flow already implemented on the desktop client.

It is intentionally aligned with the current local contracts in the app:

- `config/plugin_catalog.json`
- `config/plugin_entitlements.json`
- `config/plugin_trust_policy.json`
- `config/plugin_sync.json`
- `config/installed_plugins.json`

The goal is to replace manual/local JSON exchange with controlled backend services without changing
the client-side runtime model.

## Current Client Assumptions

The desktop application already supports:

- syncing a remote catalog snapshot into `plugin_catalog.json`
- importing or syncing signed entitlement bundles into `plugin_entitlements.json`
- verifying signed third-party packages before install
- verifying signed PRO entitlements before unlock
- enforcing trust levels and automatic isolation for untrusted plugins
- installing remote plugins from catalog `download_url`

That means the backend does not need to invent a new client protocol first. It should emit the same
contracts, but from managed services.

## Target Backend Scope

The server side should be split into 5 independent concerns.

### 1. Catalog API

Responsible for:

- publishing the current plugin catalog snapshot
- exposing metadata for install/update checks
- returning only plugins compatible with the requesting app version and channel

### 2. Entitlement API

Responsible for:

- resolving whether a user/device has `Platform Pro`
- resolving per-plugin entitlements
- returning a signed entitlement bundle consumable by the desktop client

### 3. Package Delivery

Responsible for:

- hosting signed plugin zip packages
- serving package manifests and checksums
- serving immutable versioned artifacts

This may be implemented via CDN/object storage behind signed URLs.

### 4. Publisher Trust / Signing Control Plane

Responsible for:

- managing signing keys
- rotating keys safely
- publishing public verification keys to the app distribution policy
- keeping an audit trail of who signed what and when

### 5. Billing / License Integration

Responsible for:

- mapping purchases/subscriptions to edition access and plugin access
- reflecting renewals, expiry, grace, refund, and revocation
- producing normalized entitlement state for the Entitlement API

Do not leak billing provider details directly into the desktop protocol.

## Minimal Service Topology

Recommended first production topology:

1. `catalog-api`
2. `entitlement-api`
3. `admin-console`
4. `package-storage` + CDN
5. `signing-worker`

You can physically collapse `catalog-api` and `entitlement-api` into one backend at MVP stage, but
keep the responsibilities separated in code and schema.

## Required API Endpoints

### Catalog

`GET /v1/catalog/plugins`

Query parameters:

- `app_id`
- `app_version`
- `release_profile`
- `platform`
- `arch`
- `locale`

Response:

- same shape as current `plugin_catalog.json`
- optionally filtered by compatibility
- should include `signature_algorithm` and `signing_key_id`

Recommended response headers:

- `ETag`
- `Cache-Control`
- `X-Catalog-Version`

### Entitlements

`GET /v1/entitlements/current`

Auth:

- bearer token, device token, or signed session token

Response:

- same shape as current `plugin_entitlements.json`
- must include `_meta.signature`
- must include `_meta.publisher_id`
- must include `_meta.signature_algorithm`
- should include `_meta.signing_key_id`

`POST /v1/entitlements/import`

Optional admin/support endpoint for converting external license proof into normalized entitlement
state. This is server-to-server or admin-only, not a desktop public endpoint.

### Packages

`GET /v1/packages/{plugin_id}/{version}`

Returns:

- redirect to immutable artifact URL
- or package metadata with signed download URL

`GET /v1/packages/{plugin_id}/{version}/manifest`

Returns:

- package file list
- checksum
- optional build metadata

### Admin

`POST /v1/admin/catalog/publish`

Creates a new catalog snapshot.

`POST /v1/admin/entitlements/recompute`

Rebuilds entitlement state for a user/account after billing events.

`POST /v1/admin/signing/rotate-key`

Creates a new active signing key version and marks previous keys as retained for verification.

## Server-Side Data Model

Minimum relational model.

### `publishers`

Fields:

- `publisher_id`
- `display_name`
- `trust_level`
- `status`
- `created_at`
- `updated_at`

### `publisher_signing_keys`

Fields:

- `key_id`
- `publisher_id`
- `algorithm`
- `public_key`
- `private_key_ref`
- `status`
- `activated_at`
- `retired_at`

Do not store private keys in application DB plaintext. Use KMS/HSM or at minimum a dedicated
secret manager.

### `plugins`

Fields:

- `plugin_id`
- `publisher_id`
- `owner_type`
- `stage_id`
- `pricing_model`
- `requires_platform_edition`
- `catalog_enabled`
- `status`

### `plugin_versions`

Fields:

- `plugin_id`
- `version`
- `api_version`
- `app_compatibility`
- `download_url`
- `manifest_url`
- `checksum_sha256`
- `signature`
- `signature_algorithm`
- `signing_key_id`
- `published_at`
- `status`

### `subjects`

This may represent user, workspace, tenant, org, or device depending on commercial model.

Fields:

- `subject_id`
- `account_id`
- `status`
- `created_at`

### `entitlements`

Fields:

- `subject_id`
- `scope_type` (`platform` or `plugin`)
- `scope_id`
- `status`
- `starts_at`
- `expires_at`
- `grace_until`
- `revoked_at`
- `source_system`
- `source_reference`

### `catalog_snapshots`

Fields:

- `catalog_version`
- `payload_json`
- `signature`
- `signature_algorithm`
- `signing_key_id`
- `published_at`

### `audit_events`

Fields:

- `event_id`
- `event_type`
- `actor_id`
- `target_type`
- `target_id`
- `payload_json`
- `created_at`

## Signing Requirements

Two independent signing flows are required.

### 1. Package signing

Each package version must have:

- immutable artifact
- `sha256`
- detached signature over the canonical package verification message

Current client expectation:

- package checksum is verified first
- detached signature is then verified with `publisher_id` + `signing_key_id`

### 2. Entitlement signing

Each entitlement snapshot must be signed over canonical JSON payload bytes.

This signature is what prevents local/manual unlock of PRO functions.

Important:

- package signatures and entitlement signatures may use different key sets
- but operationally it is simpler to keep one publisher key hierarchy with separate usage labels

## Key Rotation Policy

The backend must support multi-key verification windows.

Required behavior:

1. New key is created as `active`.
2. New catalog entries and entitlement bundles start using the new `signing_key_id`.
3. Previous keys remain in verification set until all supported clients and published artifacts no
   longer need them.
4. Only then key status moves to `retired`.

Do not rotate by replacing one public key in place. Always version keys.

## Authentication And Subject Binding

The most important design decision is what a PRO unlock belongs to.

Choose one primary model:

- per-user
- per-workspace
- per-organization
- per-device

Recommended default:

- billing bound to account/user
- desktop sessions bound to user + device registration
- entitlement snapshot issued for a concrete `subject_id`

Minimum auth components:

- login/session API
- refresh token or long-lived device token
- device registration record
- server-side subject lookup

If login is postponed, an interim offline-license model is possible:

- support uploads of signed entitlement bundle files
- generate those bundles in admin/billing backend
- keep the same signed payload schema so future online sync is compatible

## Catalog Publication Workflow

Recommended pipeline:

1. Publisher uploads package candidate.
2. Validation worker checks manifest, package structure, checksum, compatibility, malware/policy
   rules.
3. Reviewer approves candidate.
4. Signing worker signs package metadata.
5. Catalog publisher writes a new snapshot.
6. Snapshot gets versioned and pushed to CDN/API cache.

Never let authors publish directly to the live catalog without validation.

## Entitlement Resolution Workflow

Recommended pipeline:

1. Billing/subscription event arrives.
2. Backend normalizes it into internal entitlement state.
3. Entitlement resolver computes effective access:
   - `platform_edition`
   - per-plugin states
   - expiry / grace / revoked
4. Resolver emits signed snapshot.
5. Desktop sync writes snapshot locally.
6. Runtime/UI consume the local signed snapshot only.

This preserves deterministic offline behavior after sync.

## Unlock Flow For PRO Features

Recommended desktop-visible flow:

1. User signs in or imports a signed license bundle.
2. Client requests/syncs entitlement snapshot.
3. Client verifies signature.
4. Client writes `plugin_entitlements.json`.
5. Catalog/runtime reevaluate access state.
6. Bundled hidden/full plugins become visible and installable plugins unlock where entitled.

Critical rule:

Local config edits must never be treated as sufficient proof of PRO access.

## Compatibility And Version Policy

The backend should reject or filter plugin versions by:

- client app version
- plugin `api_version`
- OS/platform
- CPU arch
- release profile
- optional capability flags

Do not send all catalog entries to every client and rely on client-side filtering only.

## Operational Requirements

### Logging

Log:

- catalog sync requests
- entitlement sync requests
- package download authorization
- signing operations
- key rotation events
- revocation and billing state changes

### Metrics

Track:

- catalog sync success rate
- entitlement sync success rate
- signature verification failures
- package install failures by reason
- active Pro subjects
- plugin adoption by plugin/version
- revocation events

### Alerts

Alert on:

- entitlement signing failures
- package signing failures
- unusual spike in invalid signature reports
- catalog publication failures
- key mismatch after rotation

## Security Requirements

Mandatory minimum:

- private keys in KMS/HSM/secret manager
- immutable package artifacts
- audit trail for signing and publication
- TLS everywhere
- least privilege between catalog, entitlement, and admin paths
- no client ability to mark itself `platform_edition.enabled = true`

Strongly recommended:

- malware scan / static scan for submitted packages
- separate signing worker from public API
- short-lived signed artifact URLs for private packages
- replay protection or timestamping for sensitive entitlement flows

## Suggested MVP Order

### Phase 1. Server-Compatible Contracts

- finalize catalog JSON schema
- finalize signed entitlement schema
- finalize signing key distribution policy

### Phase 2. Admin And Signing

- build package validation + approval path
- build signing worker
- build publisher + key management tables

### Phase 3. Read APIs

- implement `GET /v1/catalog/plugins`
- implement `GET /v1/entitlements/current`
- implement package redirect/download endpoint

### Phase 4. Billing Integration

- connect subscription/purchase provider
- map provider events into normalized entitlements
- generate signed entitlement snapshots automatically

### Phase 5. Desktop Online UX

- sign-in flow
- sync actions in UI
- retry and offline cache policy

## Recommended Non-Goals For First Backend Iteration

Do not include all of this in v1:

- full self-service marketplace for third-party authors
- arbitrary plugin upload from desktop client
- in-app payment orchestration
- per-plugin license migration UI
- multi-region package replication logic

## Concrete Deliverables Checklist

### Contracts

- catalog schema versioned
- entitlement schema versioned
- package manifest schema versioned
- signing key schema versioned

### Services

- catalog read endpoint
- entitlement read endpoint
- package delivery endpoint
- admin publication endpoint
- signing worker

### Security

- key storage strategy approved
- key rotation runbook written
- audit logging enabled
- revocation model approved

### Operations

- staging environment
- seed catalog snapshot
- seed test entitlements
- observability dashboard
- incident playbook for bad signature / bad catalog release

## Recommended Next Repository Step

After this document, the next useful local step is to codify the server contracts as JSON schemas and
sample payloads under a dedicated folder, for example:

- `server_contracts/catalog.schema.json`
- `server_contracts/entitlements.schema.json`
- `server_contracts/package_manifest.schema.json`
- `server_contracts/examples/*.json`

That will make backend and desktop development converge faster and reduce drift.
