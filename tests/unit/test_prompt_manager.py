import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from aimn.plugins.prompt_manager import (  # noqa: E402
    build_prompt,
    build_prompt_preview,
    compute_prompt_signature,
    default_prompt_manager_settings,
    normalize_presets,
    resolve_prompt,
)


class TestPromptManager(unittest.TestCase):
    def test_default_settings_include_required_profiles_and_sections(self) -> None:
        settings = default_prompt_manager_settings()
        profiles = settings.get("profiles")
        self.assertIsInstance(profiles, list)
        ids = {str(item.get("id", "")).strip() for item in profiles if isinstance(item, dict)}
        self.assertTrue({"brief", "standard", "detailed", "transcript_edit"}.issubset(ids))

        sections = settings.get("sections")
        self.assertIsInstance(sections, dict)
        for key in ("service_start", "request_wrapper", "context", "service_final", "input_wrapper"):
            self.assertTrue(str(sections.get(key, "")).strip(), key)

    def test_resolve_prompt_defaults_to_standard_when_profile_empty(self) -> None:
        presets = normalize_presets(
            [
                {"id": "brief", "label": "Brief", "prompt": "Brief prompt"},
                {"id": "standard", "label": "Standard", "prompt": "Standard prompt"},
                {"id": "detailed", "label": "Detailed", "prompt": "Detailed prompt"},
            ]
        )
        resolved = resolve_prompt("", presets, "")
        self.assertEqual(resolved, "Standard prompt")

    def test_resolve_prompt_custom_falls_back_to_default_custom_text(self) -> None:
        presets = normalize_presets(
            [
                {"id": "brief", "label": "Brief", "prompt": "Brief prompt"},
                {"id": "standard", "label": "Standard", "prompt": "Standard prompt"},
            ]
        )
        resolved = resolve_prompt("custom", presets, "")
        self.assertTrue(str(resolved).strip())

    def test_build_prompt_composes_sectional_template(self) -> None:
        rendered = build_prompt(
            transcript="Speaker A: decision made.",
            main_prompt="Summarize decisions and owners.",
            language_override="English",
            max_words=300,
        )
        self.assertIn("SYSTEM INSTRUCTIONS", rendered)
        self.assertIn("REQUEST BODY:", rendered)
        self.assertIn("CONTEXT RULES:", rendered)
        self.assertIn("OUTPUT STRUCTURE", rendered)
        self.assertIn("DYNAMIC INPUT:", rendered)
        self.assertIn("[TRANSCRIPT]", rendered)
        self.assertIn("Summarize decisions and owners.", rendered)
        self.assertTrue(rendered.startswith("IMPORTANT: Write the final answer only in English."))
        self.assertIn("FINAL LANGUAGE RULE:\nIMPORTANT: Write the final answer only in English.", rendered)

    def test_build_prompt_splits_context_and_transcript_from_runtime_markers(self) -> None:
        rendered = build_prompt(
            transcript=(
                "[APPROVED_CONTEXT_START]\nAgenda: Q1 plan\n[APPROVED_CONTEXT_END]\n\n"
                "[MEETING_TRANSCRIPT_START]\nSpeaker A: hello\n[MEETING_TRANSCRIPT_END]"
            ),
            main_prompt="Do it",
            language_override="",
            max_words=120,
        )
        self.assertIn("[CONTEXT]", rendered)
        self.assertIn("Agenda: Q1 plan", rendered)
        self.assertIn("[TRANSCRIPT]", rendered)
        self.assertIn("Speaker A: hello", rendered)
        self.assertIn("Write the final answer only in the language of the transcript", rendered)

    def test_build_prompt_promotes_russian_for_cyrillic_transcript(self) -> None:
        rendered = build_prompt(
            transcript=(
                "Смотрите, мы сейчас реализуем новый функционал для карточек товара и редактирования. "
                "Нужно создать заявку, проверить шаблон и согласовать следующие шаги."
            ),
            main_prompt="Create a balanced meeting summary covering decisions and tasks.",
            language_override="",
            max_words=200,
        )
        self.assertIn("Write the final answer only in Russian", rendered)
        self.assertIn("### Тема встречи", rendered)
        self.assertIn("### Краткое резюме встречи", rendered)
        self.assertNotIn("### Meeting topic", rendered)

    def test_normalize_presets_maps_legacy_essential_to_brief(self) -> None:
        presets = normalize_presets([{"id": "essential", "label": "Essential", "prompt": "Legacy"}])
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0].preset_id, "brief")

    def test_build_prompt_preview_renders_selected_profile_with_runtime_placeholders(self) -> None:
        rendered = build_prompt_preview(
            profile_id="transcript_edit",
            language_override="English",
            max_words=180,
        )
        self.assertIn("Maximum length: 180 words.", rendered)
        self.assertIn("Edit the transcript text", rendered)
        self.assertIn("[CONTEXT]", rendered)
        self.assertIn("[TRANSCRIPT]", rendered)

    def test_compute_prompt_signature_changes_between_profiles(self) -> None:
        standard_sig = compute_prompt_signature("standard", "")
        detailed_sig = compute_prompt_signature("detailed", "")
        self.assertTrue(str(standard_sig).strip())
        self.assertTrue(str(detailed_sig).strip())
        self.assertNotEqual(standard_sig, detailed_sig)


if __name__ == "__main__":
    unittest.main()
