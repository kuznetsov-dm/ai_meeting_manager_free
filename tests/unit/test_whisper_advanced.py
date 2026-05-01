import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestWhisperAdvanced(unittest.TestCase):
    def test_builds_cli_with_quality_flags_and_vad(self) -> None:
        from aimn.plugins.api import HookContext
        from plugins.transcription.whisper_advanced import whisper_advanced
        from plugins.transcription.whisper_advanced import whisper_basic

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            models_dir = tmp_path / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "ggml-small.bin").write_bytes(b"")
            vad_model = tmp_path / "vad.bin"
            vad_model.write_bytes(b"")

            media = tmp_path / "in.wav"
            media.write_bytes(b"RIFFxxxxWAVE")
            whisper_bin = tmp_path / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
            whisper_bin.write_bytes(b"")

            ctx = HookContext(
                plugin_id="transcription.whisperadvanced",
                meeting_id="m1",
                alias=None,
                input_text=None,
                input_media_path=str(media),
                plugin_config={},
            )
            captured: dict[str, object] = {}

            class _Proc:
                def __init__(self, cmd, env):
                    self.cmd = cmd
                    self.env = env
                    self.stdout = []
                    self.returncode = 0

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def wait(self):
                    cmd = list(self.cmd or [])
                    if "-of" in cmd:
                        out_base = Path(cmd[cmd.index("-of") + 1])
                        out_base.with_suffix(".txt").write_text("[music]\nhello\n", encoding="utf-8")
                        out_base.with_suffix(".json").write_text(
                            json.dumps({"transcription": [{"text": "[music]"}, {"text": "hello"}]}),
                            encoding="utf-8",
                        )
                    return 0

            def _popen(cmd, **kwargs):
                captured["cmd"] = list(cmd)
                captured["env"] = dict(kwargs.get("env") or {})
                return _Proc(cmd, kwargs.get("env"))

            with mock.patch.object(whisper_basic.subprocess, "Popen", _popen):
                result = whisper_advanced.WhisperAdvancedPlugin(
                    model="small",
                    whisper_path=str(whisper_bin),
                    models_dir=str(models_dir),
                    vad_model=str(vad_model),
                    no_context=True,
                    suppress_nst=True,
                ).run(ctx)

            cmd = list(captured.get("cmd") or [])
            self.assertIn("--vad", cmd)
            self.assertIn("--vad-model", cmd)
            self.assertIn("--suppress-nst", cmd)
            self.assertIn("-mc", cmd)
            self.assertIn("0", cmd)
            transcript = next((out.content for out in result.outputs if out.kind == "transcript"), "")
            self.assertEqual(str(transcript).strip(), "hello")

    def test_truncates_on_stuck_output(self) -> None:
        from aimn.plugins.api import HookContext
        from plugins.transcription.whisper_advanced import whisper_advanced
        from plugins.transcription.whisper_advanced import whisper_basic

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            models_dir = tmp_path / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "ggml-small.bin").write_bytes(b"")
            vad_model = tmp_path / "vad.bin"
            vad_model.write_bytes(b"")

            media = tmp_path / "in.wav"
            media.write_bytes(b"RIFFxxxxWAVE")
            whisper_bin = tmp_path / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
            whisper_bin.write_bytes(b"")

            ctx = HookContext(
                plugin_id="transcription.whisperadvanced",
                meeting_id="m1",
                alias=None,
                input_text=None,
                input_media_path=str(media),
                plugin_config={},
            )

            # Build a JSON that contains a long consecutive run of identical text.
            entries = [{"offsets": {"from": 0, "to": 1000}, "text": "ok"}]
            entries += [{"offsets": {"from": 1000 + i * 100, "to": 1100 + i * 100}, "text": "stuck"} for i in range(20)]
            entries += [{"offsets": {"from": 4000, "to": 5000}, "text": "tail"}]

            class _Proc:
                def __init__(self, cmd, env):
                    self.cmd = cmd
                    self.env = env
                    self.stdout = []
                    self.returncode = 0

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def wait(self):
                    cmd = list(self.cmd or [])
                    if "-of" in cmd:
                        out_base = Path(cmd[cmd.index("-of") + 1])
                        out_base.with_suffix(".txt").write_text("ok\n" + ("stuck\n" * 20) + "tail\n", encoding="utf-8")
                        out_base.with_suffix(".json").write_text(
                            json.dumps({"transcription": entries}),
                            encoding="utf-8",
                        )
                    return 0

            def _popen(cmd, **kwargs):
                return _Proc(cmd, kwargs.get("env"))

            with mock.patch.object(whisper_basic.subprocess, "Popen", _popen):
                result = whisper_advanced.WhisperAdvancedPlugin(
                    model="small",
                    whisper_path=str(whisper_bin),
                    models_dir=str(models_dir),
                    vad_model=str(vad_model),
                    stuck_detector_enabled=True,
                    stuck_min_run=10,
                    stuck_action="truncate",
                ).run(ctx)

            transcript = next((out.content for out in result.outputs if out.kind == "transcript"), "")
            self.assertEqual(str(transcript).strip(), "ok")


if __name__ == "__main__":
    unittest.main()

