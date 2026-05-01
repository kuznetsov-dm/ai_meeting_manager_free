from __future__ import annotations

from pathlib import Path

from aimn.core.app_paths import get_app_root


_TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "vocab.json",
    "merges.txt",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "spiece.model",
)

_WEIGHTS_FILES = (
    "pytorch_model.bin",
    "model.safetensors",
)


def _resolve_hf_snapshot(models_dir: Path, model_id: str) -> Path | None:
    hf_slug = model_id.replace("/", "--")
    repo_dir = models_dir / f"models--{hf_slug}"
    if not repo_dir.exists() or not repo_dir.is_dir():
        return None
    ref_main = repo_dir / "refs" / "main"
    if ref_main.exists():
        rev = ref_main.read_text(encoding="utf-8", errors="ignore").strip()
        if rev:
            snap = repo_dir / "snapshots" / rev
            if snap.exists() and snap.is_dir():
                return snap
    snaps = repo_dir / "snapshots"
    if not snaps.exists() or not snaps.is_dir():
        return None
    candidates = [p for p in snaps.iterdir() if p.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _snapshot_looks_complete(snapshot: Path) -> bool:
    if not (snapshot / "config.json").exists():
        return False
    # SentenceTransformer layouts normally include at least one of these.
    if not (snapshot / "modules.json").exists() and not (snapshot / "config_sentence_transformers.json").exists():
        return False
    if not any((snapshot / name).exists() for name in _WEIGHTS_FILES):
        return False
    if not any((snapshot / name).exists() for name in _TOKENIZER_FILES):
        return False
    return True


def embeddings_available(
    model_id: str | None,
    model_path: str | None,
    *,
    app_root: Path | None = None,
) -> bool:
    root = app_root or get_app_root()
    if model_path:
        path = Path(model_path)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return True
    models_dir = root / "models" / "embeddings"
    if not models_dir.exists():
        return False
    if not model_id:
        return any(models_dir.iterdir())
    slug = model_id.replace("/", "_")
    # Allow a "human folder" layout like models/embeddings/sentence-transformers/all-MiniLM-L6-v2/
    nested = models_dir / model_id
    if nested.exists() and nested.is_dir():
        return _snapshot_looks_complete(nested) if (nested / "config.json").exists() else True
    direct = models_dir / slug
    if direct.exists() and direct.is_dir():
        return _snapshot_looks_complete(direct) if (direct / "config.json").exists() else True
    snap = _resolve_hf_snapshot(models_dir, model_id)
    if snap is None:
        return False
    return _snapshot_looks_complete(snap)
