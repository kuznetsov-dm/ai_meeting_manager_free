from __future__ import annotations

from typing import Callable

from aimn.core.api import ManagementStore


class LlmPromptContextController:
    def __init__(self, *, paths, settings_store, prompt_settings_id: str) -> None:
        self._paths = paths
        self._settings_store = settings_store
        self._prompt_settings_id = str(prompt_settings_id or "").strip()

    @staticmethod
    def llm_stage_will_run(
        runtime_config: dict[str, object],
        *,
        force_run_from: str | None,
        stage_order: list[str],
    ) -> bool:
        llm_index = stage_order.index("llm_processing") if "llm_processing" in stage_order else -1
        if llm_index < 0:
            return False
        start_stage = str(force_run_from or "").strip()
        if start_stage in stage_order and stage_order.index(start_stage) > llm_index:
            return False

        pipeline = runtime_config.get("pipeline")
        disabled: set[str] = set()
        if isinstance(pipeline, dict):
            raw_disabled = pipeline.get("disabled_stages")
            if isinstance(raw_disabled, list):
                disabled = {str(item or "").strip() for item in raw_disabled if str(item or "").strip()}
        if "llm_processing" in disabled:
            return False

        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            return False
        llm_stage = stages.get("llm_processing")
        if not isinstance(llm_stage, dict):
            return False
        variants = llm_stage.get("variants")
        if isinstance(variants, list):
            return any(
                isinstance(entry, dict) and str(entry.get("plugin_id", "") or "").strip()
                for entry in variants
            )
        return bool(str(llm_stage.get("plugin_id", "") or "").strip())

    @staticmethod
    def meeting_id_for_prompt_context(
        *,
        active_meeting_manifest: object | None,
        active_meeting_base_name: str,
        load_meeting_by_base: Callable[[str], object | None],
    ) -> str:
        if active_meeting_manifest is not None:
            mid = str(getattr(active_meeting_manifest, "meeting_id", "") or "").strip()
            if mid:
                return mid
        base = str(active_meeting_base_name or "").strip()
        if not base:
            return ""
        try:
            meeting = load_meeting_by_base(base)
        except Exception:
            return ""
        return str(getattr(meeting, "meeting_id", "") or "").strip() if meeting is not None else ""

    def load_llm_agenda_selection(self, *, meeting_id: str) -> dict:
        payload = self._settings_store.get_settings(self._prompt_settings_id, include_secrets=False)
        mapping = payload.get("agenda_selection_by_meeting")
        if not isinstance(mapping, dict):
            return {}
        key = str(meeting_id or "").strip()
        raw = mapping.get(key) if key and isinstance(mapping.get(key), dict) else None
        if raw is None and isinstance(mapping.get("__global__"), dict):
            raw = mapping.get("__global__")
        if not isinstance(raw, dict):
            return {}
        return {
            "agenda_id": str(raw.get("agenda_id", "") or "").strip(),
            "agenda_title": str(raw.get("agenda_title", "") or "").strip(),
            "agenda_text": str(raw.get("agenda_text", "") or "").strip(),
        }

    def save_llm_agenda_selection(self, *, meeting_id: str, selection: dict) -> None:
        try:
            payload = self._settings_store.get_settings(self._prompt_settings_id, include_secrets=False)
            current = dict(payload) if isinstance(payload, dict) else {}
            mapping = current.get("agenda_selection_by_meeting")
            if not isinstance(mapping, dict):
                mapping = {}
            key = str(meeting_id or "").strip() or "__global__"
            mapping[key] = {
                "agenda_id": str(selection.get("agenda_id", "") or "").strip(),
                "agenda_title": str(selection.get("agenda_title", "") or "").strip(),
                "agenda_text": str(selection.get("agenda_text", "") or "").strip(),
            }
            current["agenda_selection_by_meeting"] = mapping
            self._settings_store.set_settings(
                self._prompt_settings_id,
                current,
                secret_fields=[],
                preserve_secrets=[],
            )
        except Exception:
            return

    def load_agenda_catalog(self) -> list[dict]:
        items = self._load_management_items(
            row_loader="list_agendas",
            id_keys=("id",),
            value_builder=lambda entry, agenda_id: {
                "id": agenda_id,
                "title": str(entry.get("title", "") or "").strip(),
                "text": str(entry.get("text", "") or "").strip(),
                "updated_at": str(entry.get("updated_at", "") or "").strip(),
            },
        )
        return self._sort_catalog_items(items)

    def load_project_catalog(self) -> list[dict]:
        items = self._load_management_items(
            row_loader="list_projects",
            id_keys=("project_id", "id"),
            value_builder=lambda entry, project_id: {
                "project_id": project_id,
                "name": str(entry.get("name", "") or "").strip(),
                "status": str(entry.get("status", "") or "").strip(),
                "updated_at": str(entry.get("updated_at", "") or "").strip(),
            },
        )
        return self._sort_catalog_items(items)

    def _load_management_items(
        self,
        *,
        row_loader: str,
        id_keys: tuple[str, ...],
        value_builder: Callable[[dict, str], dict],
    ) -> list[dict]:
        app_root = getattr(self._paths, "app_root", None)
        if app_root is None:
            return []
        store = ManagementStore(app_root)
        try:
            loader = getattr(store, row_loader, None)
            raw_rows = loader() if callable(loader) else []
        finally:
            store.close()
        if not isinstance(raw_rows, list):
            return []
        items: list[dict] = []
        for entry in raw_rows:
            if not isinstance(entry, dict):
                continue
            row_id = ""
            for key in id_keys:
                row_id = str(entry.get(key, "") or "").strip()
                if row_id:
                    break
            if not row_id:
                continue
            items.append(value_builder(entry, row_id))
        return items

    @staticmethod
    def _sort_catalog_items(items: list[dict]) -> list[dict]:
        ordered = [entry for entry in items if isinstance(entry, dict)]
        ordered.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return ordered

    @staticmethod
    def parse_project_ids(raw: object) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for chunk in text.split(","):
            item = str(chunk or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @staticmethod
    def stringify_project_ids(project_ids: list[str]) -> str:
        clean = [str(item or "").strip() for item in (project_ids or []) if str(item or "").strip()]
        return ",".join(clean)

    @staticmethod
    def apply_llm_prompt_selection(runtime_config: dict[str, object], selection: dict) -> None:
        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            stages = {}
            runtime_config["stages"] = stages
        llm_stage = stages.get("llm_processing")
        if not isinstance(llm_stage, dict):
            llm_stage = {}
            stages["llm_processing"] = llm_stage
        params = llm_stage.get("params")
        if not isinstance(params, dict):
            params = {}
            llm_stage["params"] = params

        agenda_id = str(selection.get("agenda_id", "") or "").strip()
        agenda_title = str(selection.get("agenda_title", "") or "").strip()
        agenda_text = str(selection.get("agenda_text", "") or "").strip()
        if agenda_id:
            params["prompt_agenda_id"] = agenda_id
        else:
            params.pop("prompt_agenda_id", None)
        if agenda_title:
            params["prompt_agenda_title"] = agenda_title
        else:
            params.pop("prompt_agenda_title", None)
        if agenda_text:
            params["prompt_agenda_text"] = agenda_text
        else:
            params.pop("prompt_agenda_text", None)
        project_ids = LlmPromptContextController.parse_project_ids(selection.get("prompt_project_ids"))
        if project_ids:
            params["prompt_project_ids"] = LlmPromptContextController.stringify_project_ids(project_ids)
        else:
            params.pop("prompt_project_ids", None)

    @staticmethod
    def apply_llm_agenda_selection(runtime_config: dict[str, object], selection: dict) -> None:
        # Backward-compatible alias used by older callers/tests.
        LlmPromptContextController.apply_llm_prompt_selection(runtime_config, selection)
