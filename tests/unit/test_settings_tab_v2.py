import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.contracts import PluginDescriptor  # noqa: E402
from aimn.core.plugin_health_service import PluginHealthReport  # noqa: E402
from aimn.ui import settings_tab_v2 as settings_tab_module  # noqa: E402
from aimn.ui.settings_tab_v2 import SettingsTabV2  # noqa: E402


class _FakeStore:
    def __init__(self, payload: dict[str, dict[str, object]]) -> None:
        self._payload = payload
        self.saved: list[dict[str, object]] = []

    def get_settings(self, plugin_id: str, *, include_secrets: bool = False) -> dict[str, object]:
        _ = include_secrets
        return dict(self._payload.get(str(plugin_id), {}))

    def set_settings(
        self,
        plugin_id: str,
        values: dict[str, object],
        *,
        secret_fields: list[str],
        preserve_secrets: list[str],
    ) -> None:
        self.saved.append(
            {
                "plugin_id": plugin_id,
                "values": dict(values),
                "secret_fields": list(secret_fields),
                "preserve_secrets": list(preserve_secrets),
            }
        )
        self._payload[str(plugin_id)] = dict(values)


class _FakeCatalog:
    def __init__(self, plugin: PluginDescriptor) -> None:
        self._plugin = plugin

    def plugin_by_id(self, plugin_id: str):
        if str(plugin_id) == self._plugin.plugin_id:
            return self._plugin
        return None


class _FakeHealthService:
    def __init__(self, report: PluginHealthReport) -> None:
        self._report = report
        self.calls: list[dict[str, object]] = []

    def check_plugin(self, plugin_id: str, **kwargs: object) -> PluginHealthReport:
        payload = {"plugin_id": plugin_id}
        payload.update(kwargs)
        self.calls.append(payload)
        return self._report


def _run_async_sync(
    *,
    request_id: int,
    fn,
    on_finished,
    on_error=None,
    thread_pool=None,
    args=(),
    kwargs=None,
):
    _ = thread_pool
    try:
        result = fn(*(args or ()), **(kwargs or {}))
    except Exception as exc:
        if on_error is not None:
            on_error(request_id, exc)
        return None
    on_finished(request_id, result)
    return None


class TestSettingsTabV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_merge_live_validation_keeps_saved_secret_when_widget_blank(self) -> None:
        merged = SettingsTabV2._merge_live_validation_settings(
            {"endpoint": "https://saved.example", "api_key": "persisted-secret"},
            {"endpoint": "https://draft.example", "api_key": ""},
            secret_fields=["api_key"],
            dirty_secret_fields={"api_key"},
        )

        self.assertEqual(merged.get("endpoint"), "https://draft.example")
        self.assertNotIn("api_key", merged)

    def test_secret_live_validation_uses_merged_override_and_updates_status(self) -> None:
        plugin_id = "llm.demo"
        plugin = PluginDescriptor(
            plugin_id=plugin_id,
            stage_id="llm_processing",
            name="Demo",
            module="plugins.llm.demo",
            class_name="Plugin",
            enabled=True,
            installed=True,
        )
        report = PluginHealthReport(
            plugin_id=plugin_id,
            stage_id="llm_processing",
            healthy=True,
            checked_at=0.0,
            cached=False,
        )
        health = _FakeHealthService(report)

        tab = SettingsTabV2.__new__(SettingsTabV2)
        QWidget.__init__(tab)
        self.addCleanup(tab.deleteLater)
        tab._app_root = repo_root
        tab._active_section_id = plugin_id
        tab._catalog = _FakeCatalog(plugin)
        tab._store = _FakeStore({plugin_id: {"endpoint": "https://saved.example", "timeout_seconds": 30}})
        tab._health_service = health
        tab._secret_validation_timer = QTimer(tab)
        tab._secret_validation_timer.setSingleShot(True)
        tab._secret_validation_timer.setInterval(700)
        tab._secret_validation_timer.timeout.connect(tab._run_secret_validation)
        tab._secret_validation_request_id = 0
        tab._field_widgets = {
            "endpoint": QLineEdit("https://draft.example"),
            "api_key": QLineEdit("live-secret"),
        }
        tab._secret_status_labels = {"api_key": QLabel("")}
        tab._dirty_secret_fields = set()
        tab._rendering_form = False
        tab._tr = lambda _key, default: default  # type: ignore[method-assign]
        tab._fmt = lambda _key, default, **kwargs: default.format(**kwargs)  # type: ignore[method-assign]
        tab._collect_prompt_manager_values = lambda: {}  # type: ignore[method-assign]
        tab._has_embeddings_fields = lambda: False  # type: ignore[method-assign]

        tab._on_secret_field_edited("api_key")

        self.assertTrue(tab._secret_validation_timer.isActive())
        self.assertEqual(tab._secret_status_labels["api_key"].property("aimn_validation_state"), "checking")

        with patch.object(settings_tab_module, "run_async", side_effect=_run_async_sync):
            tab._run_secret_validation()

        self.assertTrue(health.calls)
        call = health.calls[-1]
        self.assertEqual(call.get("plugin_id"), plugin_id)
        self.assertEqual(call.get("stage_id"), "llm_processing")
        self.assertEqual(
            call.get("settings_override"),
            {
                "endpoint": "https://draft.example",
                "timeout_seconds": 30,
                "api_key": "live-secret",
            },
        )
        self.assertEqual(tab._secret_status_labels["api_key"].property("aimn_validation_state"), "ok")

    def test_live_validation_keeps_embeddings_flags_even_when_model_is_not_local(self) -> None:
        plugin_id = "text_processing.semantic_refiner"
        tab = SettingsTabV2.__new__(SettingsTabV2)
        QWidget.__init__(tab)
        self.addCleanup(tab.deleteLater)
        tab._active_section_id = plugin_id
        tab._store = _FakeStore(
            {
                plugin_id: {
                    "embeddings_enabled": True,
                    "embeddings_allow_download": True,
                    "embeddings_model_id": "intfloat/multilingual-e5-base",
                }
            }
        )
        tab._field_widgets = {
            "embeddings_model_id": QLineEdit("intfloat/multilingual-e5-base"),
            "embeddings_allow_download": QLineEdit("true"),
        }
        tab._dirty_secret_fields = set()
        tab._collect_prompt_manager_values = lambda: {}  # type: ignore[method-assign]
        tab._collect = lambda: (  # type: ignore[method-assign]
            {
                "embeddings_enabled": True,
                "embeddings_allow_download": True,
                "embeddings_model_id": "intfloat/multilingual-e5-base",
            },
            [],
        )

        merged = tab._live_validation_settings_override()

        self.assertTrue(merged["embeddings_enabled"])
        self.assertTrue(merged["embeddings_allow_download"])
        self.assertEqual(merged["embeddings_model_id"], "intfloat/multilingual-e5-base")

    def test_save_keeps_embeddings_flags_for_auto_download_plugins(self) -> None:
        plugin_id = "text_processing.semantic_refiner"
        store = _FakeStore(
            {
                plugin_id: {
                    "embeddings_enabled": True,
                    "embeddings_allow_download": True,
                    "embeddings_model_id": "intfloat/multilingual-e5-base",
                }
            }
        )
        tab = SettingsTabV2.__new__(SettingsTabV2)
        QWidget.__init__(tab)
        self.addCleanup(tab.deleteLater)
        tab._active_section_id = plugin_id
        tab._pending_auto_save_section_id = plugin_id
        tab._store = store
        tab._models_panel = None
        tab._collect_prompt_manager_values = lambda: {}  # type: ignore[method-assign]
        tab._collect = lambda: (  # type: ignore[method-assign]
            {
                "embeddings_enabled": True,
                "embeddings_allow_download": True,
                "embeddings_model_id": "intfloat/multilingual-e5-base",
            },
            [],
        )

        tab._save()

        self.assertTrue(store.saved)
        saved_values = store.saved[-1]["values"]
        self.assertTrue(saved_values["embeddings_enabled"])
        self.assertTrue(saved_values["embeddings_allow_download"])
        self.assertEqual(saved_values["embeddings_model_id"], "intfloat/multilingual-e5-base")

if __name__ == "__main__":
    unittest.main()
