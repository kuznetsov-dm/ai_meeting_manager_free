# AI Meeting Manager Free

AI Meeting Manager Free is the public, standalone desktop edition of AI Meeting Manager.
It processes meeting recordings into transcripts, derived text artifacts, and optional
LLM-assisted outputs through a strict pipeline and isolated plugin architecture.

## Positioning

This repository is the public free edition.
It is intended to remain usable on its own, while commercial editions and paid plugin packs
may be distributed separately.

Key implications:
- The core application and the files in this repository are licensed under `MPL-2.0`.
- Separate plugins, premium extensions, hosted services, and commercial distributions may use different licenses.
- The plugin architecture is intentionally isolated so external plugins can be developed and distributed independently.
- Trademark rights are not granted by the source-code license. See [TRADEMARKS.md](TRADEMARKS.md).

## Core Principles

- Core contains infrastructure and pipeline orchestration.
- Domain features are delivered through plugins.
- Artifact storage is flat and deterministic.
- `*_MEETING.json` remains the canonical meeting passport.
- Stages are fixed, plugin implementations are replaceable.

## Free Build

This repository includes the `core_free` release profile used for the free distributable build.
That profile keeps the runtime intentionally minimal and bundles only the required local components.

## License

Unless a file says otherwise, this repository is licensed under `MPL-2.0`.
That means:
- You can use, modify, and distribute this code.
- Changes to MPL-covered files that you distribute must stay available under MPL-2.0.
- Larger works and separate modules can remain under different terms.

This is a practical fit for a public free edition with separately licensed paid plugins or premium distributions.

## Trademarks

The source code license does not grant rights to the project name, product branding, or logos.
See [TRADEMARKS.md](TRADEMARKS.md).
