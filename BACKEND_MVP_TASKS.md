# Backend MVP Tasks For Plugin Platform

## Goal

Deliver the minimum backend needed to replace manual/local plugin catalog and license exchange with:

- managed catalog publication
- signed entitlement delivery
- signed package delivery
- safe PRO unlock flow

This backlog is aligned with:

- [SERVER_BACKEND_PREPARATION.md](/C:/Project/apogee_ai_projects/apps/ai_meeting_manager/SERVER_BACKEND_PREPARATION.md)
- [PLUGIN_CATALOG_AND_ENTITLEMENT_API.md](/C:/Project/apogee_ai_projects/apps/ai_meeting_manager/PLUGIN_CATALOG_AND_ENTITLEMENT_API.md)
- [openapi.plugin_platform.yaml](/C:/Project/apogee_ai_projects/apps/ai_meeting_manager/server_contracts/openapi.plugin_platform.yaml)

## Delivery Strategy

Recommended order:

1. contracts and signing
2. read-only APIs
3. admin publication flow
4. entitlement generation
5. billing integration

Do not start with billing. First make catalog and signed entitlements technically real.

## Epic 1. Contracts And Governance

### Task 1.1

Freeze v1 contract set.

Deliverables:

- review and approve `server_contracts/*`
- assign schema owners
- define versioning policy

Acceptance:

- backend and desktop teams agree on v1 fields
- no unresolved ambiguity around `publisher_id`, `signing_key_id`, `platform_edition`

### Task 1.2

Define trust and publisher governance policy.

Deliverables:

- publisher onboarding checklist
- review rules for third-party plugins
- trust level assignment rules

Acceptance:

- clear rule for when plugin is `first_party`, `trusted_third_party`, or rejected

## Epic 2. Signing Infrastructure

### Task 2.1

Provision signing key storage.

Deliverables:

- KMS/HSM or secret manager decision
- key generation procedure
- access control policy

Acceptance:

- private keys never stored in app DB plaintext

### Task 2.2

Implement signing worker.

Responsibilities:

- sign entitlement payloads
- sign package metadata
- emit `signature_algorithm`
- emit `signing_key_id`

Acceptance:

- deterministic signing output for canonical payloads
- audit event written for every signing action

### Task 2.3

Implement key rotation workflow.

Deliverables:

- create new key
- activate key
- retain previous verification keys
- retire old keys later

Acceptance:

- at least two active verification keys can coexist for one publisher

## Epic 3. Catalog Backend

### Task 3.1

Create catalog storage model.

Minimum tables:

- `publishers`
- `plugins`
- `plugin_versions`
- `catalog_snapshots`

Acceptance:

- server can store multiple versions per plugin
- metadata supports pricing, compatibility, and publisher identity

### Task 3.2

Implement catalog snapshot builder.

Responsibilities:

- filter by compatibility
- exclude unpublished plugin versions
- include `checksum_sha256`, `signature`, `signature_algorithm`, `signing_key_id`

Acceptance:

- output validates against `catalog.schema.json`

### Task 3.3

Implement `GET /v1/catalog/plugins`.

Acceptance:

- response matches OpenAPI
- supports `app_version` and `release_profile` filtering
- returns `ETag`

## Epic 4. Package Delivery

### Task 4.1

Create artifact publishing flow.

Responsibilities:

- upload immutable plugin zip
- compute package checksum
- generate package manifest
- bind package to plugin version

Acceptance:

- every published version has immutable artifact URL and checksum

### Task 4.2

Implement package resolve endpoint.

Endpoints:

- `GET /v1/packages/{plugin_id}/{version}`
- `GET /v1/packages/{plugin_id}/{version}/manifest`

Acceptance:

- desktop can install from returned metadata without custom per-plugin logic

### Task 4.3

Add package validation gate.

Checks:

- manifest present
- schema valid
- no forbidden structure
- no path traversal
- compatibility metadata present

Acceptance:

- invalid packages never reach published state

## Epic 5. Entitlement Backend

### Task 5.1

Create entitlement data model.

Minimum tables:

- `subjects`
- `entitlements`
- `audit_events`

Acceptance:

- platform and plugin entitlements can be represented independently

### Task 5.2

Implement entitlement resolver.

Responsibilities:

- compute effective platform edition
- compute per-plugin status
- apply `active` / `grace` / `expired` / `revoked`

Acceptance:

- output validates against `entitlements.schema.json`

### Task 5.3

Implement `GET /v1/entitlements/current`.

Acceptance:

- signed snapshot returned for authenticated subject
- desktop import/sync path can consume it unchanged

### Task 5.4

Implement support/admin import path.

Endpoint:

- `POST /v1/entitlements/import`

Acceptance:

- external license source can be normalized into server-side entitlement records
- import is audited

## Epic 6. Admin Workflows

### Task 6.1

Implement catalog publish endpoint.

Endpoint:

- `POST /v1/admin/catalog/publish`

Acceptance:

- new snapshot can be built and made active without direct DB edits

### Task 6.2

Implement entitlement recompute endpoint.

Endpoint:

- `POST /v1/admin/entitlements/recompute`

Acceptance:

- support can force refresh after billing correction or manual override

### Task 6.3

Implement signing key rotate endpoint.

Endpoint:

- `POST /v1/admin/signing/rotate-key`

Acceptance:

- new key appears in verification set
- old key remains usable until explicitly retired

## Epic 7. Authentication

### Task 7.1

Choose subject binding model.

Decision needed:

- per-user
- per-organization
- per-device

Recommended:

- per-user with device registration

Acceptance:

- one documented subject model selected

### Task 7.2

Implement auth for read APIs.

Acceptance:

- `GET /v1/entitlements/current` requires valid auth
- catalog may stay public or semi-public by policy

## Epic 8. Billing Integration

### Task 8.1

Normalize billing events.

Input examples:

- subscription created
- renewed
- payment failed
- refund
- cancellation

Acceptance:

- internal entitlement state updates deterministically from billing events

### Task 8.2

Map platform and plugin products.

Acceptance:

- `Platform Pro` and per-plugin products are represented independently

### Task 8.3

Support grace and revocation.

Acceptance:

- resolver emits correct `grace` and `revoked` states

## Epic 9. Security And Operations

### Task 9.1

Audit logging.

Must log:

- catalog publish
- entitlement recompute
- entitlement import
- package publish
- key rotation

### Task 9.2

Observability.

Must expose:

- catalog sync rate
- entitlement sync rate
- signature generation failures
- package resolution failures

### Task 9.3

Incident playbooks.

Need runbooks for:

- compromised signing key
- bad catalog release
- bad entitlement release
- package metadata mismatch

## MVP Milestones

## Milestone A. Signed Read-Only Platform

Scope:

- contracts approved
- signing worker ready
- catalog API ready
- entitlement API ready
- package resolve endpoint ready

Outcome:

- desktop can sync catalog and import/sync signed entitlements from backend

## Milestone B. Managed Publication

Scope:

- admin publish flow
- package validation flow
- artifact storage

Outcome:

- new plugins and versions can be published without manual JSON edits

## Milestone C. Commercial Unlock

Scope:

- auth
- billing integration
- entitlement recompute from provider events

Outcome:

- legal PRO unlock path exists end-to-end

## Recommended Team Split

### Backend platform

- contracts
- APIs
- data model
- admin endpoints

### Security/platform ops

- keys
- secret storage
- signing worker
- audit trails

### Commerce/billing

- product mapping
- entitlement normalization
- renewal/revocation logic

## Definition Of Done For Backend MVP

The MVP is done when:

- catalog snapshot is served by backend
- package metadata and artifact delivery are backend-managed
- entitlement snapshot is server-generated and signed
- desktop can unlock PRO through signed entitlement sync/import
- manual local config edits are no longer part of the commercial workflow

## Recommended Immediate Next Sprint

If work starts now, the first sprint should only include:

1. finalize contracts
2. implement signing worker
3. create `publishers`, `plugins`, `plugin_versions`, `catalog_snapshots`
4. implement `GET /v1/catalog/plugins`
5. implement `GET /v1/entitlements/current` with static/test subject data

That is the shortest path to a real backend surface without overcommitting to billing too early.
