from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import sys
from pathlib import Path

from aimn.core.api import (
    OFFLINE_PRESET_ID,
    AppPaths,
    ArtifactStoreService,
    ManagementStore,
    PipelinePresetService,
    PipelineService,
    PluginCatalogService,
    load_plugin_manifest,
)
from aimn.core.contracts import StageEvent
from aimn.core.plugin_distribution import PluginDistributionResolver
from aimn.core.release_profile import active_release_profile
from aimn.ui.app import run

_PLUGIN_SCHEMA_CACHE: dict | None = None


def main() -> int:
    if len(sys.argv) == 1:
        return run()
    parser = argparse.ArgumentParser(prog="aimn")
    subparsers = parser.add_subparsers(dest="command")

    process_parser = subparsers.add_parser("process", help="Process meeting files without UI")
    process_parser.add_argument("files", nargs="+", help="Media files to process")
    process_parser.add_argument("--preset", default="", help="Pipeline preset id (default: active preset)")

    index_parser = subparsers.add_parser("index", help="Index commands")
    index_sub = index_parser.add_subparsers(dest="index_command")
    rebuild_parser = index_sub.add_parser("rebuild", help="Rebuild search index")
    rebuild_parser.add_argument("--meeting-id", default="", help="Rebuild index for a meeting id")

    plugin_parser = subparsers.add_parser("plugin", help="Plugin developer commands")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command")
    list_parser = plugin_sub.add_parser("list", help="List plugins with distribution/access metadata")
    list_parser.add_argument("--stage", default="", help="Filter by stage id")
    install_parser = plugin_sub.add_parser("install", help="Install plugin package from zip or folder")
    install_parser.add_argument("package_path", help="Path to plugin zip or unpacked plugin folder")
    install_remote_parser = plugin_sub.add_parser("install-remote", help="Install plugin package from catalog")
    install_remote_parser.add_argument("plugin_id", help="Plugin id from remote catalog")
    sync_catalog_parser = plugin_sub.add_parser("sync-catalog", help="Sync remote plugin catalog snapshot")
    sync_catalog_parser.add_argument("--source", default="", help="Override catalog URL/path")
    sync_entitlements_parser = plugin_sub.add_parser(
        "sync-entitlements",
        help="Sync signed entitlement snapshot",
    )
    sync_entitlements_parser.add_argument("--source", default="", help="Override entitlement URL/path")
    import_entitlements_parser = plugin_sub.add_parser(
        "import-entitlements",
        help="Import signed entitlement bundle from file or URL",
    )
    import_entitlements_parser.add_argument("source", help="Path or URL to signed entitlement JSON")
    update_parser = plugin_sub.add_parser("update", help="Update an installed plugin from zip or folder")
    update_parser.add_argument("plugin_id", help="Expected plugin id to update")
    update_parser.add_argument("package_path", help="Path to plugin zip or unpacked plugin folder")
    remove_parser = plugin_sub.add_parser("remove", help="Remove an installed plugin override")
    remove_parser.add_argument("plugin_id", help="Plugin id to remove from config/plugins_installed")
    validate_parser = plugin_sub.add_parser("validate", help="Validate plugin manifest and entrypoint")
    validate_parser.add_argument(
        "path",
        nargs="?",
        default="",
        help="Path to plugin.json or plugin directory (contains plugin.json)",
    )
    lint_parser = plugin_sub.add_parser("lint", help="Lint plugin manifest and entrypoint")
    lint_parser.add_argument(
        "path",
        nargs="?",
        default="",
        help="Path to plugin.json or plugin directory (contains plugin.json)",
    )

    args = parser.parse_args()
    release_profile = active_release_profile()
    if args.command == "process":
        return _cmd_process(args)
    if args.command == "index" and args.index_command == "rebuild":
        return _cmd_index_rebuild(args)
    if args.command == "plugin" and args.plugin_command == "list":
        return _cmd_plugin_list(args)
    if args.command == "plugin" and args.plugin_command == "install":
        if not release_profile.package_management_enabled():
            return _cmd_plugin_package_blocked(args)
        return _cmd_plugin_install(args)
    if args.command == "plugin" and args.plugin_command == "install-remote":
        if not release_profile.package_management_enabled():
            return _cmd_plugin_package_blocked(args)
        return _cmd_plugin_install_remote(args)
    if args.command == "plugin" and args.plugin_command == "sync-catalog":
        return _cmd_plugin_sync_catalog(args)
    if args.command == "plugin" and args.plugin_command == "sync-entitlements":
        return _cmd_plugin_sync_entitlements(args)
    if args.command == "plugin" and args.plugin_command == "import-entitlements":
        return _cmd_plugin_import_entitlements(args)
    if args.command == "plugin" and args.plugin_command == "update":
        if not release_profile.package_management_enabled():
            return _cmd_plugin_package_blocked(args)
        return _cmd_plugin_update(args)
    if args.command == "plugin" and args.plugin_command == "remove":
        if not release_profile.package_management_enabled():
            return _cmd_plugin_package_blocked(args)
        return _cmd_plugin_remove(args)
    if args.command == "plugin" and args.plugin_command in {"validate", "lint"}:
        return _cmd_plugin_validate(args)
    parser.print_help()
    return 1


def _cmd_plugin_package_blocked(args: argparse.Namespace) -> int:
    payload = {
        "status": "error",
        "message": "plugin_package_management_disabled_for_release_profile",
        "plugin_command": str(getattr(args, "plugin_command", "") or "").strip(),
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 1


def _cmd_process(args: argparse.Namespace) -> int:
    paths = AppPaths.resolve()
    preset = str(getattr(args, "preset", "") or "").strip()
    presets = PipelinePresetService(paths.config_dir / "settings", repo_root=paths.repo_root)
    if not preset:
        preset = presets.active_preset()
    snapshot = presets.load(preset)
    config_data = snapshot.config_data
    if not config_data and preset == OFFLINE_PRESET_ID:
        config_data = presets.offline_config()
        presets.save(preset, config_data)

    service = PipelineService(paths.repo_root, config_data)
    artifact_store = ArtifactStoreService(paths.repo_root)
    try:
        for file_path in args.files:
            media_path = Path(file_path)
            if not media_path.exists():
                print(f"missing_file: {media_path}")
                return 1
            def emit_event(event: StageEvent) -> None:
                message = event.message or ""
                stage = event.stage_id or "-"
                print(f"{event.event_type}\t{stage}\t{message}")
            outcome = service.run_file(
                media_path,
                force_run=False,
                event_callback=emit_event,
            )
            if outcome.error:
                print(f"pipeline_failed: {outcome.error}")
                return 1
            artifact_store.index_meeting(outcome.meeting.meeting_id)
            print(f"pipeline_finished\t{outcome.meeting.base_name}")
    finally:
        service.shutdown()
        artifact_store.close()
    return 0


def _cmd_index_rebuild(args: argparse.Namespace) -> int:
    paths = AppPaths.resolve()
    artifact_store = ArtifactStoreService(paths.repo_root)
    meeting_id = str(getattr(args, "meeting_id", "") or "").strip() or None
    artifact_store.rebuild_index(meeting_id)
    artifact_store.close()
    payload = {"status": "ok", "meeting_id": meeting_id}
    print(json.dumps(payload, ensure_ascii=True))
    return 0


def _cmd_plugin_list(args: argparse.Namespace) -> int:
    paths = AppPaths.resolve()
    service = PluginCatalogService(paths.repo_root)
    snapshot = service.load()
    resolver = PluginDistributionResolver(paths.repo_root)
    stage_filter = str(getattr(args, "stage", "") or "").strip()
    plugins = snapshot.catalog.all_plugins()
    if stage_filter:
        plugins = [plugin for plugin in plugins if plugin.stage_id == stage_filter]
    payload = {
        "status": "ok",
        "platform_edition_enabled": resolver.platform_edition_enabled(),
        "plugins": [
            {
                "plugin_id": plugin.plugin_id,
                "stage_id": plugin.stage_id,
                "enabled": bool(plugin.enabled),
                "installed": bool(plugin.installed),
                "entitled": bool(plugin.entitled),
                "access_state": plugin.access_state,
                "source_kind": plugin.source_kind,
                "pricing_model": plugin.pricing_model,
                "owner_type": plugin.owner_type,
                "included_in_core": bool(plugin.included_in_core),
                "requires_platform_edition": bool(plugin.requires_platform_edition),
                "catalog_enabled": bool(plugin.catalog_enabled),
                "version": plugin.version,
            }
            for plugin in plugins
        ],
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


def _cmd_plugin_install(args: argparse.Namespace) -> int:
    from aimn.core.plugin_package_service import PluginPackageService

    paths = AppPaths.resolve()
    service = PluginPackageService(paths.repo_root)
    result = service.install_from_path(Path(str(args.package_path)))
    print(
        json.dumps(
            {
                "status": "ok",
                "plugin_id": result.plugin_id,
                "version": result.version,
                "install_dir": str(result.install_dir),
                "replaced_existing": result.replaced_existing,
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_update(args: argparse.Namespace) -> int:
    from aimn.core.plugin_package_service import PluginPackageService

    paths = AppPaths.resolve()
    service = PluginPackageService(paths.repo_root)
    result = service.install_from_path(
        Path(str(args.package_path)),
        expected_plugin_id=str(args.plugin_id or "").strip(),
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "plugin_id": result.plugin_id,
                "version": result.version,
                "install_dir": str(result.install_dir),
                "replaced_existing": result.replaced_existing,
                "mode": "update",
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_install_remote(args: argparse.Namespace) -> int:
    from aimn.core.plugin_package_service import PluginPackageService

    paths = AppPaths.resolve()
    service = PluginPackageService(paths.repo_root)
    result = service.install_from_catalog(str(args.plugin_id or "").strip())
    print(
        json.dumps(
            {
                "status": "ok",
                "plugin_id": result.plugin_id,
                "version": result.version,
                "install_dir": str(result.install_dir),
                "replaced_existing": result.replaced_existing,
                "verification_state": result.verification_state,
                "trust_level": result.trust_level,
                "mode": "install_remote",
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_sync_catalog(args: argparse.Namespace) -> int:
    from aimn.core.plugin_sync_service import PluginSyncService

    paths = AppPaths.resolve()
    service = PluginSyncService(paths.repo_root)
    result = service.sync_catalog(str(getattr(args, "source", "") or "").strip())
    print(
        json.dumps(
            {
                "status": "ok",
                "source": result.source,
                "path": str(result.path),
                "plugin_count": result.plugin_count,
                "mode": "sync_catalog",
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_sync_entitlements(args: argparse.Namespace) -> int:
    from aimn.core.plugin_sync_service import PluginSyncService

    paths = AppPaths.resolve()
    service = PluginSyncService(paths.repo_root)
    result = service.sync_entitlements(str(getattr(args, "source", "") or "").strip())
    print(
        json.dumps(
            {
                "status": "ok",
                "source": result.source,
                "path": str(result.path),
                "verified": result.verified,
                "reason": result.reason,
                "platform_edition_enabled": result.platform_edition_enabled,
                "mode": "sync_entitlements",
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_import_entitlements(args: argparse.Namespace) -> int:
    from aimn.core.plugin_sync_service import PluginSyncService

    paths = AppPaths.resolve()
    service = PluginSyncService(paths.repo_root)
    result = service.import_entitlements(str(args.source or "").strip())
    print(
        json.dumps(
            {
                "status": "ok",
                "source": result.source,
                "path": str(result.path),
                "verified": result.verified,
                "reason": result.reason,
                "platform_edition_enabled": result.platform_edition_enabled,
                "mode": "import_entitlements",
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_remove(args: argparse.Namespace) -> int:
    from aimn.core.plugin_package_service import PluginPackageService

    paths = AppPaths.resolve()
    service = PluginPackageService(paths.repo_root)
    result = service.remove_installed_plugin(str(args.plugin_id or "").strip())
    print(
        json.dumps(
            {
                "status": "ok",
                "plugin_id": result.plugin_id,
                "removed": result.removed,
                "removed_path": str(result.removed_path),
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_plugin_validate(args: argparse.Namespace) -> int:
    paths = AppPaths.resolve()
    raw = str(getattr(args, "path", "") or "").strip()
    target = Path(raw) if raw else paths.plugins_dir
    if not target.is_absolute():
        target = (paths.repo_root / target).resolve()
    manifest_paths = _resolve_manifest_paths(target)
    if not manifest_paths:
        print(
            json.dumps(
                {"status": "error", "message": f"manifest_not_found:{target}"},
                ensure_ascii=True,
            )
        )
        return 1

    import_roots = (
        paths.repo_root.resolve(),
        paths.plugins_dir.resolve(),
        paths.installed_plugins_dir.resolve(),
    )
    for root in import_roots:
        root_s = str(root)
        if root_s not in sys.path:
            sys.path.insert(0, root_s)

    seen_plugin_ids: dict[str, Path] = {}
    ok_payloads: list[dict] = []
    errors: list[dict] = []
    for manifest_path in manifest_paths:
        payload, problem = _validate_single_manifest(manifest_path, seen_plugin_ids)
        if problem:
            errors.append({"manifest": str(manifest_path), "message": problem})
            continue
        ok_payloads.append(payload)

    if errors:
        print(
            json.dumps(
                {
                    "status": "error",
                    "total": len(manifest_paths),
                    "validated": len(ok_payloads),
                    "errors": errors,
                },
                ensure_ascii=True,
            )
        )
        return 1

    if len(ok_payloads) == 1:
        print(json.dumps(ok_payloads[0], ensure_ascii=True))
        return 0

    print(
        json.dumps(
            {
                "status": "ok",
                "total": len(ok_payloads),
                "validated": len(ok_payloads),
                "plugins": ok_payloads,
            },
            ensure_ascii=True,
        )
    )
    return 0


def _resolve_manifest_paths(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if not target.exists() or not target.is_dir():
        return []
    direct = target / "plugin.json"
    if direct.exists():
        return [direct]
    return sorted(target.rglob("plugin.json"))


def _validate_single_manifest(path: Path, seen_plugin_ids: dict[str, Path]) -> tuple[dict, str]:
    style_errors = _validate_manifest_raw(path)
    if style_errors:
        return {}, ";".join(style_errors)
    try:
        manifest = load_plugin_manifest(path)
    except Exception as exc:
        return {}, f"manifest_invalid:{exc}"

    existing = seen_plugin_ids.get(manifest.plugin_id)
    if existing and existing.resolve() != path.resolve():
        return {}, f"duplicate_plugin_id:{manifest.plugin_id}:{existing}:{path}"
    seen_plugin_ids.setdefault(manifest.plugin_id, path)

    layout_errors = _validate_repo_plugin_layout(path, manifest.entrypoint)
    if layout_errors:
        return {}, ";".join(layout_errors)

    try:
        module_name, class_name = str(manifest.entrypoint).split(":", 1)
        module = importlib.import_module(module_name)
        plugin_cls = getattr(module, class_name, None)
        if plugin_cls is None:
            raise ValueError(f"entrypoint_class_missing:{class_name}")
    except Exception as exc:
        return {}, f"entrypoint_invalid:{exc}"

    api_errors = _validate_entrypoint_source(module)
    if api_errors:
        return {}, ";".join(api_errors)

    return (
        {
            "status": "ok",
            "plugin_id": manifest.plugin_id,
            "manifest": str(path),
            "entrypoint": manifest.entrypoint,
            "hooks": len(manifest.hooks),
            "artifacts": len(manifest.artifacts),
            "dependencies": list(manifest.dependencies),
        },
        "",
    )


def _validate_repo_plugin_layout(path: Path, entrypoint: str) -> list[str]:
    repo_plugins_dir = Path(__file__).resolve().parents[2] / "plugins"
    try:
        relative = path.resolve().relative_to(repo_plugins_dir.resolve())
    except Exception:
        return []

    parent_name = path.parent.name
    if parent_name == "schemas" or parent_name.startswith("_test_"):
        return []

    errors: list[str] = []
    if len(relative.parts) != 3:
        errors.append(f"plugin_layout_invalid:{path}")
        return errors
    if "." in parent_name:
        errors.append(f"plugin_dir_dotted:{path.parent}")

    group_name = relative.parts[0]
    expected_module = f"plugins.{group_name}.{parent_name}.{parent_name}"
    module_name, _class_name = str(entrypoint).split(":", 1)
    if module_name != expected_module:
        errors.append(f"plugin_entrypoint_layout_invalid:{module_name}:{expected_module}")

    expected_module_file = path.parent / f"{parent_name}.py"
    if not expected_module_file.exists():
        errors.append(f"plugin_module_missing:{expected_module_file}")
    return errors


def _validate_manifest_raw(path: Path) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"manifest_invalid:{exc}"]
    if not isinstance(raw, dict):
        return ["manifest_invalid:plugin.json must be an object"]

    errors: list[str] = _validate_manifest_schema(raw)
    ui_stage = str(raw.get("ui_stage", "") or "").strip()
    if ui_stage and ui_stage not in {"transcription", "llm_processing", "management", "service", "other"}:
        errors.append(f"ui_stage_invalid:{ui_stage}")

    schema = raw.get("ui_schema")
    if not isinstance(schema, dict):
        return errors
    settings = schema.get("settings")
    if not isinstance(settings, list):
        return errors

    for index, setting in enumerate(settings):
        if not isinstance(setting, dict):
            continue
        key = str(setting.get("key", "") or "").strip() or f"index_{index}"
        options = setting.get("options")
        if options is None:
            continue
        if not isinstance(options, list):
            errors.append(f"ui_schema_options_invalid:{key}:must_be_list")
            continue
        for opt_index, opt in enumerate(options):
            if not isinstance(opt, dict) or not str(opt.get("label", "") or "").strip() or "value" not in opt:
                errors.append(f"ui_schema_options_invalid:{key}:option_{opt_index}")
                break
    return errors


def _validate_manifest_schema(raw: dict) -> list[str]:
    schema = _load_plugin_manifest_schema()
    if not schema:
        return []
    try:
        import jsonschema  # type: ignore
    except Exception:
        return []

    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    violations = sorted(
        list(validator.iter_errors(raw)),
        key=lambda item: ".".join(str(part) for part in list(item.path)),
    )
    for item in violations[:25]:
        location = ".".join(str(part) for part in list(item.path))
        where = location if location else "$"
        message = str(getattr(item, "message", "") or "invalid")
        errors.append(f"schema_invalid:{where}:{message}")
    return errors


def _load_plugin_manifest_schema() -> dict | None:
    global _PLUGIN_SCHEMA_CACHE
    if _PLUGIN_SCHEMA_CACHE is not None:
        return _PLUGIN_SCHEMA_CACHE
    schema_path = (
        Path(__file__).resolve().parents[2] / "plugins" / "schemas" / "plugin_manifest.schema.json"
    )
    if not schema_path.exists():
        _PLUGIN_SCHEMA_CACHE = {}
        return None
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        _PLUGIN_SCHEMA_CACHE = {}
        return None
    _PLUGIN_SCHEMA_CACHE = payload if isinstance(payload, dict) else {}
    return _PLUGIN_SCHEMA_CACHE or None


def _validate_entrypoint_source(module: object) -> list[str]:
    source = Path(str(getattr(module, "__file__", "") or ""))
    if not source.exists() or source.suffix != ".py":
        return []
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except Exception:
        return []

    errors: list[str] = []
    store_var_names = _find_store_variable_names(tree)
    store_methods = {
        name
        for name, member in inspect.getmembers(ManagementStore)
        if callable(member) and not str(name).startswith("_")
    }
    required_prompt_args = {"profile_id", "presets", "custom"}
    prompt_positional = ("profile_id", "presets", "custom")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in store_var_names:
                method = str(node.func.attr or "")
                if method and method not in store_methods:
                    errors.append(f"management_store_method_invalid:{method}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "resolve_prompt":
            provided = set(prompt_positional[: len(node.args)])
            provided.update(
                str(keyword.arg or "").strip()
                for keyword in node.keywords
                if str(keyword.arg or "").strip()
            )
            if not required_prompt_args.issubset(provided):
                errors.append("resolve_prompt_signature_invalid")
    return sorted(set(errors))


def _find_store_variable_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        call: ast.Call | None = None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            call = node.value
            targets = [node.target]
        else:
            continue
        fn = call.func
        if isinstance(fn, ast.Name):
            is_open_store = fn.id == "open_management_store"
        elif isinstance(fn, ast.Attribute):
            is_open_store = fn.attr == "open_management_store"
        else:
            is_open_store = False
        if not is_open_store:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


if __name__ == "__main__":
    raise SystemExit(main())
