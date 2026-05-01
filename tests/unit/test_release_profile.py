import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.app_paths import get_plugin_distribution_path  # noqa: E402
from aimn.core.pipeline_settings import PipelineSettingsStore  # noqa: E402
from aimn.core.plugins_registry import load_registry_payload  # noqa: E402
from aimn.core.release_profile import active_release_profile  # noqa: E402


class TestReleaseProfile(unittest.TestCase):
    def test_default_profile_when_env_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIMN_RELEASE_PROFILE", None)
            profile = active_release_profile()
        self.assertEqual(profile.profile_id, "default")
        self.assertTrue(profile.package_management_enabled())
        self.assertTrue(profile.management_tab_visible())

    def test_core_free_profile_reads_manifest_flags(self) -> None:
        with patch.dict(os.environ, {"AIMN_RELEASE_PROFILE": "core_free"}, clear=False):
            profile = active_release_profile()
        self.assertEqual(profile.profile_id, "core_free")
        self.assertFalse(profile.package_management_enabled())
        self.assertFalse(profile.management_tab_visible())
        self.assertEqual(
            profile.bundled_plugin_ids(),
            (
                "transcription.whisperadvanced",
                "llm.llama_cli",
                "text_processing.minutes_heuristic_v2",
                "text_processing.semantic_refiner",
            ),
        )

    def test_plugin_distribution_path_prefers_release_config_for_locked_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AIMN_RELEASE_PROFILE": "core_free"},
            clear=False,
        ):
            app_root = Path(tmp)
            config_dir = app_root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            local_path = config_dir / "plugin_distribution.json"
            local_path.write_text("{}", encoding="utf-8")
            release_path = repo_root / "releases" / "core_free" / "config" / "plugin_distribution.json"

            path = get_plugin_distribution_path(app_root)

        self.assertEqual(path, release_path)

    def test_registry_default_payload_uses_release_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AIMN_RELEASE_PROFILE": "core_free"},
            clear=False,
        ):
            repo_root = Path(tmp)
            release_config = repo_root / "releases" / "core_free" / "config"
            release_config.mkdir(parents=True, exist_ok=True)
            release_plugins_toml = release_config / "plugins.toml"
            release_plugins_toml.write_text("[allowlist]\nids = ['llm.llama_cli']\n", encoding="utf-8")

            payload, source, path = load_registry_payload(repo_root)

        self.assertEqual(source, "default")
        self.assertEqual(path, release_plugins_toml)
        allowlist = payload.get("allowlist", {})
        self.assertEqual(allowlist.get("ids"), ["llm.llama_cli"])

    def test_pipeline_settings_store_uses_release_overlay_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AIMN_RELEASE_PROFILE": "core_free"},
            clear=False,
        ):
            repo_root = Path(tmp)
            base_dir = repo_root / "app_instance" / "config" / "settings"
            release_pipeline = repo_root / "releases" / "core_free" / "config" / "settings" / "pipeline"
            release_pipeline.mkdir(parents=True, exist_ok=True)
            (release_pipeline / "active.json").write_text('{"preset":"default"}', encoding="utf-8")
            default_path = release_pipeline / "default.json"
            default_path.write_text('{"stages":{"llm_processing":{"plugin_id":"llm.llama_cli"}}}', encoding="utf-8")

            store = PipelineSettingsStore(base_dir, repo_root=repo_root)
            active = store.load_active_preset()
            data, source, path, overrides = store.load_with_overrides("default")

        self.assertEqual(active, "default")
        self.assertEqual(source, "config")
        self.assertEqual(path, default_path)
        self.assertEqual(overrides, [])
        self.assertEqual(data.get("stages", {}).get("llm_processing", {}).get("plugin_id"), "llm.llama_cli")

    def test_registry_payload_sanitizes_incompatible_user_stage_plugin_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AIMN_RELEASE_PROFILE": "core_free"},
            clear=False,
        ):
            repo_root = Path(tmp)
            release_config = repo_root / "releases" / "core_free" / "config"
            release_config.mkdir(parents=True, exist_ok=True)
            (release_config / "plugins.toml").write_text(
                "\n".join(
                    [
                        "[allowlist]",
                        "ids = ['transcription.whisperadvanced', 'llm.llama_cli']",
                        "",
                        "[stages.transcription]",
                        "plugin_id = 'transcription.whisperadvanced'",
                        "",
                        "[stages.llm_processing]",
                        "plugin_id = 'llm.llama_cli'",
                        "params.timeout_seconds = 120",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            user_path = repo_root / "plugins.json"
            user_path.write_text(
                (
                    '{"disabled":{"ids":["llm.llama_cli"]},'
                    '"stages":{"llm_processing":{"plugin_id":"llm.openrouter","params":{"timeout_seconds":9}}}}'
                ),
                encoding="utf-8",
            )

            payload, source, _path = load_registry_payload(repo_root)

        self.assertEqual(source, "user")
        self.assertEqual(payload.get("stages", {}).get("llm_processing", {}).get("plugin_id"), "llm.llama_cli")
        self.assertEqual(payload.get("stages", {}).get("llm_processing", {}).get("params", {}).get("timeout_seconds"), 9)
        self.assertEqual(payload.get("disabled", {}).get("ids"), [])
        self.assertEqual(
            payload.get("allowlist", {}).get("ids"),
            ["transcription.whisperadvanced", "llm.llama_cli"],
        )

    def test_pipeline_settings_store_sanitizes_runtime_stage_plugin_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AIMN_RELEASE_PROFILE": "core_free"},
            clear=False,
        ):
            repo_root = Path(tmp)
            base_dir = repo_root / "app_instance" / "config" / "settings"
            release_pipeline = repo_root / "releases" / "core_free" / "config" / "settings" / "pipeline"
            release_pipeline.mkdir(parents=True, exist_ok=True)
            (release_pipeline / "active.json").write_text('{"preset":"default"}', encoding="utf-8")
            (release_pipeline / "default.json").write_text(
                (
                    '{"pipeline":{"preset":"default","optional_stage_retries":1},'
                    '"stages":{"llm_processing":{"plugin_id":"llm.llama_cli","params":{"temperature":0.2}},'
                    '"transcription":{"plugin_id":"transcription.whisperadvanced","params":{"model":"base"}}}}'
                ),
                encoding="utf-8",
            )
            runtime_dir = repo_root / "app_instance" / "output" / "settings" / "pipeline"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "default.json").write_text(
                (
                    '{"pipeline":{"preset":"default","optional_stage_retries":3},'
                    '"stages":{"llm_processing":{"plugin_id":"llm.openrouter","params":{"temperature":0.7}},'
                    '"service":{"plugin_id":"service.some_old_plugin"}}}'
                ),
                encoding="utf-8",
            )

            store = PipelineSettingsStore(base_dir, repo_root=repo_root)
            data, source, _path, overrides = store.load_with_overrides("default")

        self.assertEqual(source, "runtime")
        self.assertEqual(data.get("pipeline", {}).get("optional_stage_retries"), 3)
        self.assertEqual(data.get("stages", {}).get("llm_processing", {}).get("plugin_id"), "llm.llama_cli")
        self.assertEqual(data.get("stages", {}).get("llm_processing", {}).get("params", {}).get("temperature"), 0.7)
        self.assertNotIn("service", data.get("stages", {}))
        self.assertIn("stages.llm_processing.params.temperature", overrides)

    def test_core_free_release_plugin_settings_cover_only_bundled_plugins(self) -> None:
        release_plugins_dir = repo_root / "releases" / "core_free" / "config" / "settings" / "plugins"
        plugin_files = sorted(path.name for path in release_plugins_dir.glob("*.json"))
        self.assertEqual(
            plugin_files,
            [
                "llm.llama_cli.json",
                "transcription.whisperadvanced.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
