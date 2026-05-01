from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict

from aimn.core.app_paths import get_app_root
from aimn.core.atomic_io import atomic_write_text
from aimn.core.plugin_catalog_service import PluginCatalogService


_MODEL_QUALIFIER_SUFFIX = {
    "chat": "h",
    "flash": "f",
    "base": "b",
    "small": "s",
    "tiny": "t",
    "mini": "m",
    "large": "l",
    "medium": "d",
    "instruct": "i",
}

_CACHE_LOCK = threading.RLock()
_CACHE: dict[str, "AliasRegistry"] = {}
_LOGGER = logging.getLogger(__name__)


def _normalize_code(value: object, *, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", str(value or "")).lower()
    return cleaned or fallback


def _normalize_plugin_id(value: object) -> str:
    return str(value or "").strip()


def _normalize_model_ref(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    token = raw.split("/")[-1]
    if ":" in token:
        token = token.split(":", 1)[0]
    if token.lower().endswith(".gguf"):
        token = token[:-5]
    return token.strip().lower()


def _split_parts(value: str) -> list[str]:
    return [part for part in re.split(r"[^a-z0-9]+", value) if part]


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


class AliasRegistry:
    def __init__(self, app_root: Path | None = None) -> None:
        root = Path(app_root).resolve() if app_root else get_app_root()
        self._runtime_path = root / "output" / "settings" / "aliases.json"
        self._user_path = root / "config" / "settings" / "aliases.json"
        self._lock = threading.RLock()
        self._loaded = False
        self._catalog_service = PluginCatalogService(root)
        self._alias_policy_cache: dict[str, dict[str, Any]] = {}
        self._data: dict[str, dict[str, str] | int] = {
            "version": 1,
            "providers": {},
            "models": {},
        }

    def provider_code(self, plugin_id: str) -> str:
        pid = _normalize_plugin_id(plugin_id)
        if not pid:
            return "ll"
        with self._lock:
            self._load()
            providers = self._providers()
            existing = str(providers.get(pid, "")).strip()
            if existing:
                return _normalize_code(existing, fallback="ll")
            default = self._provider_code_hint(pid)
            if default:
                return default
            tail = pid.split(".")[-1] if "." in pid else pid
            candidate = _normalize_code(tail[:2] or tail, fallback="ll")
            used = {str(v) for v in providers.values() if str(v)}
            code = self._ensure_unique_code(candidate, used, max_len=3)
            providers[pid] = code
            self._save()
            return code

    def model_code(self, plugin_id: str, model_ref: str) -> str:
        pid = _normalize_plugin_id(plugin_id)
        model = _normalize_model_ref(model_ref)
        if not model:
            return "md"
        scoped_key = f"{pid}:{model}" if pid else model
        with self._lock:
            self._load()
            models = self._models()
            existing = str(models.get(scoped_key, "")).strip()
            if existing:
                return _normalize_code(existing, fallback="md")
            default = self._model_code_hint(pid, model_ref, model)
            if default:
                return default
            generated = self._generate_model_code(
                model,
                strip_tokens=self._strip_model_tokens(pid),
            )
            used = {
                str(value)
                for key, value in models.items()
                if str(value) and (not pid or str(key).startswith(f"{pid}:"))
            }
            code = self._ensure_unique_code(generated, used, max_len=4)
            models[scoped_key] = code
            self._save()
            return code

    def llm_alias_code(self, plugin_id: str, model_ref: str) -> str:
        return f"{self.provider_code(plugin_id)}{self.model_code(plugin_id, model_ref)}"

    def snapshot(self) -> dict:
        with self._lock:
            self._load()
            return {
                "version": int(self._data.get("version", 1) or 1),
                "providers": dict(self._providers()),
                "models": dict(self._models()),
            }

    def _providers(self) -> dict[str, str]:
        value = self._data.get("providers")
        if isinstance(value, dict):
            return value  # type: ignore[return-value]
        replacement: dict[str, str] = {}
        self._data["providers"] = replacement
        return replacement

    def _models(self) -> dict[str, str]:
        value = self._data.get("models")
        if isinstance(value, dict):
            return value  # type: ignore[return-value]
        replacement: dict[str, str] = {}
        self._data["models"] = replacement
        return replacement

    def _load(self) -> None:
        if self._loaded:
            return
        for path in (self._runtime_path, self._user_path):
            loaded = self._read_path(path)
            if loaded:
                self._data = loaded
                self._loaded = True
                return
        self._loaded = True

    def _read_path(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        providers = raw.get("providers")
        models = raw.get("models")
        return {
            "version": int(raw.get("version", 1) or 1),
            "providers": dict(providers) if isinstance(providers, dict) else {},
            "models": dict(models) if isinstance(models, dict) else {},
        }

    def _save(self) -> None:
        payload = {
            "version": int(self._data.get("version", 1) or 1),
            "providers": self._providers(),
            "models": self._models(),
        }
        try:
            atomic_write_text(
                self._runtime_path,
                json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            )
        except OSError as exc:
            # Alias persistence is best-effort; callers still need the generated code even if
            # another process is holding the registry file open.
            _LOGGER.warning("alias_registry_save_failed path=%s error=%s", self._runtime_path, exc)

    @staticmethod
    def _ensure_unique_code(base: str, used: set[str], *, max_len: int) -> str:
        cleaned = _normalize_code(base, fallback="md")[:max_len]
        if cleaned not in used:
            return cleaned
        for index in range(2, 100):
            suffix = str(index)
            trimmed = cleaned[: max_len - len(suffix)] if max_len > len(suffix) else cleaned[:1]
            candidate = f"{trimmed}{suffix}"
            if candidate not in used:
                return candidate
        return cleaned

    def _generate_model_code(self, model_token: str, *, strip_tokens: set[str]) -> str:
        parts = _split_parts(model_token)
        if not parts:
            return "md"

        if strip_tokens:
            parts = [part for part in parts if part not in strip_tokens]

        if not parts:
            return "md"

        first = parts[0]
        if first == "chat":
            return "ch"
        if first.startswith("r") and any(ch.isdigit() for ch in first):
            compact = _normalize_code(first, fallback="r")
            return compact[:3] or "md"
        if first == "tinyllama":
            digits = "".join(ch for part in parts[1:] for ch in part if ch.isdigit())
            return ("tl" + digits[:2]) if digits else "tl"
        if first == "llama":
            digits = [re.sub(r"[^0-9]", "", part) for part in parts[1:] if any(ch.isdigit() for ch in part)]
            joined = "".join(item for item in digits if item)
            return ("l" + joined[:3]) if joined else "ll"

        letters = "".join(ch for ch in first if ch.isalpha())
        digits = "".join(ch for ch in first if ch.isdigit())
        code = ""
        if letters:
            code += letters[:1]
            if digits:
                code += digits[:2]
            elif len(letters) > 1:
                code += letters[1:2]
        elif digits:
            code += digits[:2]
        else:
            code += first[:2]

        for part in parts[1:]:
            if part in _MODEL_QUALIFIER_SUFFIX:
                code += _MODEL_QUALIFIER_SUFFIX[part]
                break
            part_digits = "".join(ch for ch in part if ch.isdigit())
            if part_digits:
                code += part_digits[:1]
                break

        return _normalize_code(code, fallback="md")[:4]

    def _provider_code_hint(self, plugin_id: str) -> str:
        policy = self._alias_policy(plugin_id)
        raw = str(policy.get("provider_code", "") or "").strip()
        if not raw:
            return ""
        return _normalize_code(raw, fallback="ll")[:3]

    def _model_code_hint(self, plugin_id: str, model_ref: str, normalized_model: str) -> str:
        policy = self._alias_policy(plugin_id)
        mapping = policy.get("model_codes")
        if not isinstance(mapping, dict):
            return ""
        candidates: set[str] = set()
        raw = str(model_ref or "").strip().lower()
        norm = str(normalized_model or "").strip().lower()
        if raw:
            candidates.add(raw)
            candidates.add(_normalize_model_ref(raw))
            tail = raw.split("/")[-1]
            candidates.add(tail)
            if ":" in tail:
                candidates.add(tail.split(":", 1)[0])
        if norm:
            candidates.add(norm)
        for key, value in mapping.items():
            ref = str(key or "").strip().lower()
            if not ref:
                continue
            token = _normalize_model_ref(ref)
            if ref in candidates or token in candidates:
                code = str(value or "").strip()
                if code:
                    return _normalize_code(code, fallback="md")[:4]
        return ""

    def _strip_model_tokens(self, plugin_id: str) -> set[str]:
        policy = self._alias_policy(plugin_id)
        raw = policy.get("strip_model_tokens")
        if not isinstance(raw, list):
            return set()
        return {
            str(token or "").strip().lower()
            for token in raw
            if str(token or "").strip()
        }

    def _alias_policy(self, plugin_id: str) -> dict[str, Any]:
        pid = _normalize_plugin_id(plugin_id)
        if not pid:
            return {}
        cached = self._alias_policy_cache.get(pid)
        if cached is not None:
            return dict(cached)
        try:
            plugin = self._catalog_service.load().catalog.plugin_by_id(pid)
        except Exception:
            plugin = None
        caps = getattr(plugin, "capabilities", None) if plugin else None
        policy = _cap_get(caps, "alias_code_policy", default={})
        normalized = dict(policy) if isinstance(policy, dict) else {}
        self._alias_policy_cache[pid] = normalized
        return dict(normalized)


def get_alias_registry(app_root: Path | None = None) -> AliasRegistry:
    root = Path(app_root).resolve() if app_root else get_app_root()
    key = str(root).lower()
    with _CACHE_LOCK:
        existing = _CACHE.get(key)
        if existing:
            return existing
        created = AliasRegistry(root)
        _CACHE[key] = created
        return created


def resolve_provider_code(plugin_id: str, *, app_root: Path | None = None) -> str:
    return get_alias_registry(app_root).provider_code(plugin_id)


def resolve_model_code(plugin_id: str, model_ref: str, *, app_root: Path | None = None) -> str:
    return get_alias_registry(app_root).model_code(plugin_id, model_ref)


def resolve_llm_alias_code(plugin_id: str, model_ref: str, *, app_root: Path | None = None) -> str:
    return get_alias_registry(app_root).llm_alias_code(plugin_id, model_ref)


def reset_alias_registry_cache_for_tests() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
