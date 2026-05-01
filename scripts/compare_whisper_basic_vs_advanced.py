from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


REPO_ROOT = _repo_root()
APP_ROOT = REPO_ROOT / "apps" / "ai_meeting_manager"

for p in (APP_ROOT, APP_ROOT / "src"):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)


def _default_inputs() -> list[Path]:
    out_dir = APP_ROOT / "output"
    bases = [
        "260128-1602_260128_1602_260113_1308_55a45d2f",
        "260128-1602_260128_1602_260112_0838_2026012_",
        "260128-1602_260128_1602_260113_0737_20260113",
    ]
    paths: list[Path] = []
    for base in bases:
        wav = out_dir / f"{base}.audio.wav"
        if wav.exists():
            paths.append(wav)
    return paths


def _slug(path: Path) -> str:
    name = path.name
    if name.endswith(".audio.wav"):
        return name[: -len(".audio.wav")]
    return path.stem


def _parse_asr_entries(asr_json: str) -> list[dict]:
    try:
        payload = json.loads(asr_json) if asr_json and asr_json.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return []
    entries = payload.get("transcription")
    if not isinstance(entries, list):
        entries = payload.get("segments")
    return entries if isinstance(entries, list) else []


def _entry_text(entry: dict) -> str:
    return str(entry.get("text", "") or "").strip()


def _entry_start_ms(entry: dict) -> int | None:
    offsets = entry.get("offsets")
    if isinstance(offsets, dict):
        value = offsets.get("from")
        try:
            return int(value)
        except Exception:
            return None
    for k in ("start_ms", "t0"):
        try:
            value = entry.get(k)
            if value is not None:
                return int(value)
        except Exception:
            pass
    return None


def _format_ts_ms(ms: int | None) -> str:
    if ms is None:
        return ""
    total = int(ms)
    if total < 0:
        total = 0
    s, milli = divmod(total, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"


def _normalize(text: str) -> str:
    value = str(text or "").strip().lower()
    value = " ".join(value.split())
    return value


def _longest_run(entries: list[dict]) -> dict:
    if not entries:
        return {"len": 0, "start_idx": 0, "text": "", "start_ms": None, "start_ts": ""}
    texts = [_normalize(_entry_text(e)) for e in entries]
    best_len = 1
    best_start = 0
    best_text = texts[0]
    run_len = 1
    run_start = 0
    run_text = texts[0]
    for idx in range(1, len(texts)):
        t = texts[idx]
        if t and t == run_text:
            run_len += 1
            continue
        if run_len > best_len and run_text:
            best_len = run_len
            best_start = run_start
            best_text = run_text
        run_text = t
        run_start = idx
        run_len = 1
    if run_len > best_len and run_text:
        best_len = run_len
        best_start = run_start
        best_text = run_text
    start_ms = _entry_start_ms(entries[best_start]) if best_len > 1 else None
    return {
        "len": int(best_len),
        "start_idx": int(best_start),
        "text": str(best_text),
        "start_ms": start_ms,
        "start_ts": _format_ts_ms(start_ms),
    }


def _transcript_stats(text: str) -> dict:
    lines = [ln.strip() for ln in str(text or "").splitlines() if str(ln or "").strip()]
    bracket_lines = sum(1 for ln in lines if ln.startswith("[") and ln.endswith("]"))
    return {"chars": len(text or ""), "lines": len(lines), "bracket_lines": int(bracket_lines)}


def _asr_stats(asr_json: str) -> dict:
    entries = _parse_asr_entries(asr_json)
    texts = [_normalize(_entry_text(e)) for e in entries if _entry_text(e)]
    c = Counter(texts)
    top = [{"text": t, "count": int(n)} for t, n in c.most_common(5) if t]
    return {"entries": len(entries), "top5": top, "longest_run": _longest_run(entries)}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="Output directory")
    parser.add_argument("inputs", nargs="*", help="Input audio files (wav/mp3/flac/ogg)")
    args = parser.parse_args()

    inputs = [Path(p) for p in (args.inputs or [])]
    if not inputs:
        inputs = _default_inputs()
    inputs = [p for p in inputs if p.exists()]
    if not inputs:
        print("No inputs found.")
        return 2

    out_dir = Path(args.out).expanduser().resolve() if args.out else None
    if not out_dir:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_dir = APP_ROOT / "output_compare" / f"whisper_basic_vs_advanced_{stamp}"

    from aimn.plugins.api import HookContext
    from plugins.transcription.whisper_advanced.whisper_basic import WhisperBasicPlugin
    from plugins.transcription.whisper_advanced.whisper_advanced import WhisperAdvancedPlugin

    vad_model = str(APP_ROOT / "models" / "whisper" / "ggml-silero-v6.2.0.bin")
    whisper_path = str(APP_ROOT / "bin" / "whisper_cpp" / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli"))

    summary: dict[str, object] = {"out_dir": str(out_dir), "items": []}

    for media_path in inputs:
        base = _slug(media_path)
        item_dir = out_dir / base
        ctx = HookContext(
            plugin_id="transcription.compare",
            meeting_id=f"cmp_{base}",
            alias=None,
            input_text=None,
            input_media_path=str(media_path),
            plugin_config={},
        )

        basic = WhisperBasicPlugin(model="small", whisper_path=whisper_path, vad_model=vad_model)
        advanced = WhisperAdvancedPlugin(model="small", whisper_path=whisper_path, vad_model=vad_model)

        basic_res = basic.run(ctx)
        adv_res = advanced.run(ctx)

        def _get(outputs, kind: str) -> str:
            for out in outputs:
                if out.kind == kind:
                    return str(out.content or "")
            return ""

        basic_txt = _get(basic_res.outputs, "transcript")
        basic_asr = _get(basic_res.outputs, "asr_segments_json")
        adv_txt = _get(adv_res.outputs, "transcript")
        adv_asr = _get(adv_res.outputs, "asr_segments_json")
        adv_diag = _get(adv_res.outputs, "asr_diagnostics_json")

        _write_text(item_dir / "basic.transcript.txt", basic_txt)
        _write_text(item_dir / "advanced.transcript.txt", adv_txt)
        _write_text(item_dir / "basic.asr_segments_json.json", basic_asr)
        _write_text(item_dir / "advanced.asr_segments_json.json", adv_asr)
        if adv_diag.strip():
            _write_text(item_dir / "advanced.asr_diagnostics_json.json", adv_diag)

        record = {
            "input": str(media_path),
            "base": base,
            "basic": {
                "transcript": _transcript_stats(basic_txt),
                "asr": _asr_stats(basic_asr),
            },
            "advanced": {
                "transcript": _transcript_stats(adv_txt),
                "asr": _asr_stats(adv_asr),
            },
        }
        summary["items"].append(record)

        print(f"\n== {base}")
        print("basic:", record["basic"]["transcript"], "longest_run:", record["basic"]["asr"]["longest_run"])
        print(
            "adv  :",
            record["advanced"]["transcript"],
            "longest_run:",
            record["advanced"]["asr"]["longest_run"],
        )

    _write_json(out_dir / "summary.json", summary)
    print(f"\nWrote: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


