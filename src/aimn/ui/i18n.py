from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aimn.core.api import UiSettingsStore


class UiI18n:
    """
    Lightweight UI localization catalog with `en` fallback.

    Designed to be reused across tabs/widgets while locale coverage grows.
    """

    def __init__(self, app_root: Path, *, namespace: str) -> None:
        self._app_root = Path(app_root)
        self._namespace = str(namespace or "").strip()
        self._locale = self._resolve_locale()
        self._fallback = self._load_locale("en")
        self._active = self._load_locale(self._locale) if self._locale != "en" else self._fallback

    def t(self, key: str, default: str = "") -> str:
        namespaced = f"{self._namespace}.{key}" if self._namespace else str(key or "")
        value = self._active.get(namespaced)
        if value is None:
            value = self._fallback.get(namespaced)
        if value is None:
            value = default
        return str(value or "")

    def _resolve_locale(self) -> str:
        try:
            store = UiSettingsStore(self._app_root / "config" / "settings")
            locale = str(store.get("ui.locale") or "").strip().lower()
            if locale:
                return locale
        except Exception:
            pass
        return "en"

    def _load_locale(self, locale: str) -> dict[str, Any]:
        lid = str(locale or "").strip().lower() or "en"
        path = self._app_root / "src" / "aimn" / "ui" / "locales" / f"{lid}.json"
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}
