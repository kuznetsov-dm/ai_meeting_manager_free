# Contributing

Thanks for contributing to AI Meeting Manager.

## Quick start
- Use Python 3.11+.
- Run the UI via `python run_ui.py`.
- Run tests via `pwsh -File scripts/run_tests.ps1`.

## Project rules
- Core stays infrastructure-only; data logic lives in plugins.
- `*_MEETING.json` is the single source of truth.
- Flat artifact storage is mandatory.
- Core/UI must not hardcode concrete plugin IDs.

## Plugin development
- Main guide: `plugins/plugin_developer_requirements.md`.
- Keep plugin UI declarative (`ui_schema.settings`) whenever possible.
- If a plugin has custom Qt UI (`ui.*`), use standard UI components from
  `src/aimn/ui/widgets/standard_components.py` and avoid hardcoded colors.
- Keep user-facing plugin copy in `plugin.json`; `plugin_passport.json` is runtime metadata only.

## Localization and UX rules
- No hardcoded English-only statuses in user-facing UI.
- Prefer machine-readable status/error codes in plugin actions; UI text must be localizable.
- New UI must remain readable in all themes: `light`, `dark`, `light_mono`, `dark_mono`.

## Pull requests
- Keep changes small and focused.
- Update docs when changing contracts or schemas.
- Include tests when behavior changes.
