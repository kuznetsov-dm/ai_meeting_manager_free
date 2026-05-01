from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import warnings
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

Vector = Union[Dict[str, float], List[float]]


def _subprocess_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _running_in_frozen_bundle() -> bool:
    return bool(getattr(sys, "frozen", False))


class _SubprocessSentenceTransformerProxy:
    def __init__(self, source: str, *, cache_dir: str, offline: bool) -> None:
        self._source = str(source or "").strip()
        self._cache_dir = str(cache_dir or "").strip()
        self._offline = bool(offline)

    def probe(self) -> bool:
        try:
            self.encode(["healthcheck"])
        except Exception:
            return False
        return True

    def encode(self, sentences: Sequence[str] | str) -> list[list[float]]:
        if isinstance(sentences, str):
            payload_sentences = [sentences]
        else:
            payload_sentences = [str(item or "") for item in sentences]
        payload = json.dumps(
            {
                "source": self._source,
                "cache_dir": self._cache_dir,
                "offline": self._offline,
                "sentences": payload_sentences,
            },
            ensure_ascii=True,
        )
        script = """
import json
import os
import sys

payload = json.loads(sys.stdin.read() or "{}")
if payload.get("offline"):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TORCH_DISABLE_DYNAMO", "1")
import warnings
warnings.filterwarnings("ignore")
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(payload["source"], cache_folder=payload.get("cache_dir") or None)
vectors = model.encode(payload.get("sentences") or [])
if hasattr(vectors, "tolist"):
    vectors = vectors.tolist()
print(json.dumps(vectors, ensure_ascii=True))
"""
        env = os.environ.copy()
        if self._offline:
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
        env.setdefault("TORCH_DISABLE_DYNAMO", "1")
        result = subprocess.run(
            [sys.executable, "-c", script],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=env,
            timeout=180,
            creationflags=_subprocess_creationflags(),
        )
        if int(getattr(result, "returncode", 1) or 1) != 0:
            stderr_detail = str(result.stderr or "").strip()
            stdout_detail = str(result.stdout or "").strip()
            detail = stderr_detail or stdout_detail
            if stdout_detail.startswith("[[") and not stderr_detail:
                detail = "sentence_transformer_subprocess_failed"
            raise RuntimeError(detail.splitlines()[-1] if detail else "sentence_transformer_subprocess_failed")
        raw = str(result.stdout or "").strip()
        data = json.loads(raw) if raw else []
        return data if isinstance(data, list) else []

# --- Stopwords & Cleaning ---

def stopwords_ru() -> set[str]:
    """Extended list of Russian stopwords and conversational fillers."""
    return {
        # Prepositions & Conjunctions
        "и", "в", "во", "на", "что", "это", "как", "мы", "вы", "они", "он", "она", "оно",
        "с", "со", "к", "ко", "по", "за", "от", "для", "из", "о", "об", "про", "а", "но",
        "не", "да", "нет", "или", "ли", "бы", "то", "же", "до", "у", "без", "над", "под",
        "при", "через", "между", "перед", "после", "ради", "из-за", "из-под",

        # Pronouns / Determiners / Aux
        "я", "ты", "он", "она", "оно", "мы", "вы", "они",
        "мой", "моя", "мое", "мои", "твой", "твоя", "твое", "твои",
        "наш", "наша", "наше", "наши", "ваш", "ваша", "ваше", "ваши",
        "его", "ее", "её", "их", "мне", "моя", "мной", "тебе", "тебя", "вам", "вас",
        "этот", "эта", "это", "эти", "тот", "та", "те", "такой", "такая", "такие",
        "какой", "какая", "какие", "какого", "каких",
        "есть", "будет", "будут", "было", "были",

        # Conversational fillers / parasites (single tokens only; phrases are removed by clean_text_deep)
        "все", "всё", "всем", "всего",
        "вот", "ну", "так", "типа", "короче", "значит", "вообще", "просто", "сейчас",
        "там", "тут", "здесь", "потом", "потому", "поэтому", "собственно",
        "скажем", "допустим", "слушай", "слушайте", "смотрите",
        "понимаешь", "знаешь",
        "наверное", "возможно", "конечно", "действительно",
        "соответственно", "получается",
        "прям", "чисто", "конкретно", "кстати", "походу",
        "окей", "ладно", "хорошо", "давай", "давайте",
        "может", "быть", "кажется",
        "э", "эм", "м", "мм", "ага", "угу",
        "ещё", "еще", "уже", "только",
    }

def clean_text_deep(text: str) -> str:
    """Removes common conversational fillers (best-effort, without heavy rewriting)."""
    if not text:
        return ""

    value = " ".join(str(text).split()).strip()
    if not value:
        return ""

    # Drop common whisper hallucinations on silence (subtitle credits).
    if re.search(r"(?i)\b(?:редактор\s+субтитров|корректор)\b", value):
        # In practice these often appear as repeated short lines; removing them wholesale is safer
        # than letting them dominate keywords.
        value = re.sub(r"(?i)\b(?:редактор\s+субтитров|корректор)\b.*", " ", value)

    # Strip common ASR noise tokens/words.
    value = re.sub(
        r"(?i)\[(?:blank_audio|foreign|music|noise|laughter|inaudible|silence|unknown)\]",
        " ",
        value,
    )
    value = re.sub(r"(?i)\b(?:blank_audio|inaudible|foreign|music|noise|laughter)\b", " ", value)
    value = " ".join(value.split()).strip()
    if not value:
        return ""

    # Remove filler at sentence head (repeat a few times).
    head_re = re.compile(
        r"(?i)^\s*(?:"
        r"(?:ну|вот|типа|короче|значит|собственно|просто)\b|"
        r"в\s+общем|в\s+принципе|как\s+бы|то\s+есть|"
        r"(?:скажем|допустим|смотрите|слушай|слушайте)\b"
        r")\s*(?:[,—-]\s*)?"
    )
    for _ in range(3):
        new = head_re.sub("", value)
        if new == value:
            break
        value = new

    # Remove common filler phrases anywhere (best-effort).
    value = re.sub(
        r"(?i)\b(?:"
        r"все\s+равно|"
        r"может\s+быть|"
        r"мне\s+кажется|"
        r"как\s+бы|"
        r"то\s+есть|"
        r"в\s+общем|"
        r"в\s+принципе|"
        r"на\s+самом\s+деле|"
        r"по\s+сути|"
        r"в\s+любом\s+случае|"
        r"скажем\s+так|"
        r"так\s+сказать|"
        r"если\s+честно"
        r")\b",
        " ",
        value,
    )

    # Remove common single-token fillers anywhere.
    value = re.sub(
        r"(?i)\b(?:"
        r"все|всё|"
        r"ну|вот|типа|короче|значит|собственно|просто|вообще|кстати|"
        r"реально|буквально|вроде|прям|"
        r"бла|"
        r"ладно|окей|"
        r"скажем|допустим|"
        r"слушай|слушайте|смотрите|"
        r"ага|угу|"
        r"э|эм|мм|м"
        r")\b",
        " ",
        value,
    )

    # Collapse repeated fillers like "ну ну ну".
    value = re.sub(r"(?i)\b(ну|вот|типа|короче|значит)\b(?:\s+\1\b)+", r"\1", value)
    # Collapse repeated words like "формирует формирует" / "ланц ланц".
    value = re.sub(r"(?i)\b([0-9a-zа-яё-]{3,})\b(?:\s+\1\b)+", r"\1", value)
    # Collapse "да да" / "нет нет" runs without removing single confirmations.
    value = re.sub(r"(?i)\b(да|нет)\b(?:\s+\1\b)+", r"\1", value)
    # Remove "вот X вот" pattern.
    value = re.sub(r"(?i)\bвот\s+([0-9a-zа-яё-]{2,})\s+вот\b", r"\1", value)

    # Cleanup spaces around punctuation.
    value = re.sub(r"\s+([,.;:!?…])", r"\1", value)
    value = re.sub(r"([,.;:!?…])\s{2,}", r"\1 ", value)

    return " ".join(value.split()).strip()

def tokenize(text: str) -> List[str]:
    """Improved tokenizer that keeps hyphens inside words."""
    raw = re.findall(r"(?:\b[A-Za-zА-Яа-я0-9]+(?:-[A-Za-zА-Яа-я0-9]+)*\b)", text.lower())
    return [token for token in raw if token]

def add_hidden_markers(text: str, markers: Sequence[str]) -> str:
    """
    Appends HTML comment markers to a markdown text (not shown to users in most renderers),
    to keep benchmark/diagnostics honest without polluting the visible output.
    """
    unique: list[str] = []
    seen: set[str] = set()
    for marker in markers or []:
        value = str(marker or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    if not unique:
        return text
    out = (text or "").rstrip()
    for value in unique:
        token = f"<!-- {value} -->"
        if token in out:
            continue
        out += "\n\n" + token
    return out.rstrip() + "\n"

# --- Segmentation Logic ---

def split_sentences(text: str) -> List[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    
    try:
        from razdel import sentenize
        sentences = [item.text.strip() for item in sentenize(cleaned) if item and item.text]
        return [s for s in sentences if s]
    except ImportError:
        pass

    parts = re.split(r"(?<=[.!?…])\s+", cleaned)
    sentences = [s.strip() for s in parts if s.strip()]
    if len(sentences) > 1:
        return sentences

    # Fallback for long transcripts with no punctuation: chunk by word count.
    words = cleaned.split()
    if len(words) <= 30:
        return sentences
    chunk_size = 20
    return [" ".join(words[i : i + chunk_size]).strip() for i in range(0, len(words), chunk_size) if words[i : i + chunk_size]]

def merge_segments_smart(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merges ASR segments based on pauses and punctuation.
    """
    if not segments:
        return []

    merged = []
    current_group = segments[0].copy()
    current_group["text"] = current_group["text"].strip()

    for i in range(1, len(segments)):
        next_seg = segments[i]
        next_text = next_seg["text"].strip()
        
        prev_end = current_group["end"]
        curr_start = next_seg["start"]
        gap = curr_start - prev_end
        
        is_continuation = gap < 2.0 and not re.search(r"[.!?…]$", current_group["text"])
        is_tight_flow = gap < 0.5
        
        if is_continuation or is_tight_flow:
            sep = " " if not current_group["text"].endswith("-") else ""
            current_group["text"] += sep + next_text
            current_group["end"] = next_seg["end"]
        else:
            current_group["text"] = clean_text_deep(current_group["text"])
            merged.append(current_group)
            current_group = next_seg.copy()
            current_group["text"] = next_text

    current_group["text"] = clean_text_deep(current_group["text"])
    merged.append(current_group)
    return merged

# --- Business Logic Extractors ---

ACTION_PATTERNS = [
    r"(?:нужно|надо|необходимо|следует|обязаны)\s+(?:сделать|подготовить|написать|позвонить|отправить|проверить|согласовать|купить|заказать)",
    r"(?:давай|давайте)\s+(?:мы\s+)?(?:сделаем|посмотрим|решим|обсудим|запишем|внесем)",
    r"(?:прошу|попрошу)\s+(?:вас|тебя)?",
    r"(?:срок|дедлайн)\s+(?:до|к)\s+",
    r"(?:я\s+)?(?:беру|возьму)\s+(?:на\s+себя|в\s+работу)",
    r"(?:задача|экшн)\s*[:—]",
]

def extract_actions(text: str, limit: int = 15) -> List[str]:
    """Extracts Action Items using regex patterns."""
    sentences = split_sentences(text)
    actions = []
    seen = set()
    
    for sent in sentences:
        if "?" in sent:
            continue
            
        for pattern in ACTION_PATTERNS:
            if re.search(pattern, sent, re.IGNORECASE):
                cleaned = sent.strip("- *")
                if cleaned not in seen and len(cleaned) > 10:
                    actions.append(cleaned)
                    seen.add(cleaned)
                break
        if len(actions) >= limit:
            break
            
    return actions

def generate_topic_name(text: str) -> str:
    """Generates a human-readable topic from the text (lexical keyphrases; no LLM)."""
    tokens = tokenize(text)
    stops = stopwords_ru()
    content = [t for t in tokens if t not in stops and len(t) >= 3]
    if not content:
        return "Meeting Notes"

    # Unigram counts
    counts: dict[str, int] = {}
    for t in content:
        counts[t] = counts.get(t, 0) + 1

    # Bigram counts (prefer phrases)
    bigrams: dict[tuple[str, str], int] = {}
    for a, b in zip(tokens, tokens[1:]):
        if a in stops or b in stops:
            continue
        if len(a) < 3 or len(b) < 3:
            continue
        bigrams[(a, b)] = bigrams.get((a, b), 0) + 1

    phrases = sorted(bigrams.items(), key=lambda kv: (kv[1], counts.get(kv[0][0], 0) + counts.get(kv[0][1], 0)), reverse=True)
    chosen: list[str] = []
    used: set[str] = set()

    for (a, b), c in phrases:
        if c < 2:
            break
        phrase = f"{a.capitalize()} {b}"
        key = f"{a} {b}"
        if key in used:
            continue
        used.add(key)
        chosen.append(phrase)
        if len(chosen) >= 3:
            break

    # Fill with strong unigrams
    for w, _c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        if any(w.lower() in p.lower() for p in chosen):
            continue
        chosen.append(w.capitalize())
        if len(chosen) >= 5:
            break

    return " • ".join(chosen) if chosen else "Meeting Notes"

# --- Math & Vectors ---

def idf(tokens_list: List[List[str]]) -> Dict[str, float]:
    df: Dict[str, int] = {}
    for tokens in tokens_list:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    n = max(len(tokens_list), 1)
    return {token: math.log((1 + n) / (1 + freq)) + 1 for token, freq in df.items()}

# --- ML Model Loading ---

def get_models_dir() -> str:
    """Returns the absolute path to the local models directory."""
    # Project root is ../../ from plugins/text_processing/
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, "models", "embeddings")


_EMBEDDINGS_RUNTIME_MODULES = (
    "sentence_transformers",
    "transformers",
    "huggingface_hub",
    "torch",
)

_LAST_SENTENCE_TRANSFORMER_STATUS = "ok"
_LAST_SENTENCE_TRANSFORMER_ERROR_DETAIL = ""


def _embeddings_runtime_ready() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in _EMBEDDINGS_RUNTIME_MODULES)


def _normalize_sentence_transformer_error_detail(detail: object) -> str:
    value = " ".join(str(detail or "").split()).strip()
    if not value:
        return ""
    if len(value) > 240:
        return value[:237].rstrip() + "..."
    return value


def _set_sentence_transformer_status(status: str, detail: object = "") -> None:
    global _LAST_SENTENCE_TRANSFORMER_ERROR_DETAIL, _LAST_SENTENCE_TRANSFORMER_STATUS
    _LAST_SENTENCE_TRANSFORMER_STATUS = str(status or "unknown").strip() or "unknown"
    _LAST_SENTENCE_TRANSFORMER_ERROR_DETAIL = (
        ""
        if _LAST_SENTENCE_TRANSFORMER_STATUS in {"ok", "ready"}
        else _normalize_sentence_transformer_error_detail(detail)
    )


def get_last_sentence_transformer_status() -> str:
    return _LAST_SENTENCE_TRANSFORMER_STATUS


def get_last_sentence_transformer_error_detail() -> str:
    return _LAST_SENTENCE_TRANSFORMER_ERROR_DETAIL


def _emit_progress(progress_callback: Optional[Callable[[int], None]], value: int) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(max(0, min(100, int(value))))
    except Exception:
        return


def _ensure_embeddings_runtime(allow_download: bool) -> tuple[bool, str]:
    if _embeddings_runtime_ready():
        return True, "ready"
    if _running_in_frozen_bundle():
        return False, "runtime_unavailable_in_bundle"
    if not allow_download:
        return False, "runtime_missing"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "sentence-transformers",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=900,
            check=False,
            creationflags=_subprocess_creationflags(),
        )
    except Exception:
        return False, "runtime_install_failed"
    if int(getattr(result, "returncode", 1) or 1) != 0:
        return False, "runtime_install_failed"
    ready = _embeddings_runtime_ready()
    return ready, ("ready" if ready else "runtime_install_failed")

def try_sentence_transformer(
    model_id: Optional[str],
    allow_download: bool = False,
    model_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[object]:
    """
    Attempts to load a SentenceTransformer model.

    Note: When allow_download is False, we try hard to avoid implicit downloads by:
    - requiring a local cache hit under models/embeddings/
    - enabling HF offline env flags (best-effort)
    """
    _set_sentence_transformer_status("unknown")
    if model_path:
        try:
            from pathlib import Path

            resolved = Path(str(model_path)).expanduser()
            if resolved.exists():
                model_path = str(resolved)
            else:
                model_path = None
        except Exception:
            model_path = None

    if not model_id and not model_path:
        _set_sentence_transformer_status("missing_configuration")
        return None

    cache_dir = get_models_dir()
    _emit_progress(progress_callback, 5)
    runtime_ready, runtime_status = _ensure_embeddings_runtime(allow_download)
    if not runtime_ready:
        _emit_progress(progress_callback, 100)
        _set_sentence_transformer_status(runtime_status)
        return None
    _emit_progress(progress_callback, 25)

    def _resolve_local_source(mid: str) -> Optional[str]:
        """
        Resolve a local on-disk path for a HF cached model.

        We prefer passing a snapshot directory to SentenceTransformer to avoid any
        network activity / cache probing when running in offline mode.
        """
        try:
            from pathlib import Path

            root = Path(cache_dir)
            if not root.exists():
                return None

            slug = mid.replace("/", "_")
            hf_slug = mid.replace("/", "--")

            # Some setups store extracted models in a direct folder (slug).
            direct = root / slug
            if direct.exists() and direct.is_dir():
                # Heuristic: treat as a valid model dir if it has config.json.
                if (direct / "config.json").exists():
                    return str(direct)

            # Standard HF cache layout: models--ORG--REPO/snapshots/<rev>/
            repo_dir = root / f"models--{hf_slug}"
            if not repo_dir.exists() or not repo_dir.is_dir():
                return None

            # Prefer refs/main if present; it points to a snapshot hash.
            ref_main = repo_dir / "refs" / "main"
            if ref_main.exists():
                rev = ref_main.read_text(encoding="utf-8", errors="ignore").strip()
                if rev:
                    snap = repo_dir / "snapshots" / rev
                    if snap.exists() and (snap / "config.json").exists():
                        return str(snap)

            snaps_root = repo_dir / "snapshots"
            if not snaps_root.exists():
                return None

            # Fallback: pick the newest snapshot that looks like a model dir.
            candidates = []
            for child in snaps_root.iterdir():
                if not child.is_dir():
                    continue
                if (child / "config.json").exists():
                    candidates.append(child)
            if not candidates:
                return None
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(candidates[0])
        except Exception:
            return None

    def _local_cache_hit(mid: str) -> bool:
        import os
        from pathlib import Path

        root = Path(cache_dir)
        if not root.exists():
            return False
        slug = mid.replace("/", "_")
        hf_slug = mid.replace("/", "--")
        candidates = [
            root / slug,
            root / f"models--{hf_slug}",
        ]
        for candidate in candidates:
            if candidate.exists():
                return True
        # Also accept nested cache layouts created by huggingface_hub.
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                name = child.name
                if name == slug or name == f"models--{hf_slug}":
                    return True
        except Exception:
            pass
        return False

    old_env = {}
    try:
        local_available = bool(model_path) or bool(model_id and _local_cache_hit(model_id))
        if not allow_download:
            # Hard guard: require local cache presence (or explicit local model_path).
            if not model_path and model_id and not _local_cache_hit(model_id):
                _emit_progress(progress_callback, 100)
                _set_sentence_transformer_status("model_missing")
                return None

            for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
                old_env[key] = os.environ.get(key)
                os.environ[key] = "1"
        else:
            _emit_progress(progress_callback, 45 if not local_available else 65)

        source = model_path or model_id
        if not allow_download and not model_path and model_id:
            # Prefer local snapshot path to prevent any network probes.
            local_source = _resolve_local_source(model_id)
            if not local_source:
                _emit_progress(progress_callback, 100)
                _set_sentence_transformer_status("model_missing")
                return None
            source = local_source
        if not source:
            _emit_progress(progress_callback, 100)
            _set_sentence_transformer_status("missing_configuration")
            return None
        if os.name == "nt" and not _running_in_frozen_bundle():
            proxy = _SubprocessSentenceTransformerProxy(
                source,
                cache_dir=cache_dir,
                offline=not allow_download,
            )
            try:
                proxy.encode(["healthcheck"])
            except Exception as exc:
                try:
                    from sentence_transformers import SentenceTransformer

                    warnings.filterwarnings("ignore")
                    os.environ.setdefault("TORCH_DISABLE_DYNAMO", "1")
                    model = SentenceTransformer(source, cache_folder=cache_dir)
                    _emit_progress(progress_callback, 100)
                    _set_sentence_transformer_status("ready")
                    return model
                except Exception as fallback_exc:
                    _emit_progress(progress_callback, 100)
                    detail = str(fallback_exc or "").strip() or str(exc or "").strip()
                    _set_sentence_transformer_status(
                        "model_load_failed" if allow_download else "model_missing",
                        detail,
                    )
                    return None
            _emit_progress(progress_callback, 100)
            _set_sentence_transformer_status("ready")
            return proxy
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            _emit_progress(progress_callback, 100)
            _set_sentence_transformer_status("runtime_missing")
            return None
        os.environ.setdefault("TORCH_DISABLE_DYNAMO", "1")
        model = SentenceTransformer(source, cache_folder=cache_dir)
        _emit_progress(progress_callback, 100)
        _set_sentence_transformer_status("ready")
        return model
    except Exception as exc:
        _emit_progress(progress_callback, 100)
        _set_sentence_transformer_status(
            "model_load_failed" if allow_download else "model_missing",
            exc,
        )
        return None
    finally:
        try:
            for key, prev in old_env.items():
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev
        except Exception:
            pass
