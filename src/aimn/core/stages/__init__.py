from __future__ import annotations

from aimn.core.plugins_config import PluginsConfig
from aimn.core.pipeline import StageAdapter, StagePolicy

from .base import PluginStageAdapter
from .llm_processing import LlmProcessingAdapter
from .management import ManagementAdapter
from .media_convert import MediaConvertAdapter
from .service import ServiceAdapter
from .text_processing import TextProcessingAdapter
from .transcription import TranscriptionAdapter


class StagesRegistry:
    def __init__(self, config: PluginsConfig) -> None:
        self._config = config

    def build(self) -> list[StageAdapter]:
        optional_retries = self._config.optional_stage_retries()
        disabled = set(self._config.disabled_stages())
        stages: list[StageAdapter] = [
            MediaConvertAdapter(
                StagePolicy(stage_id="media_convert", required=False, max_retries=optional_retries),
                self._config,
            )
        ]
        if "media_convert" in disabled:
            stages = []

        optional_stages = [
            ("transcription", True, TranscriptionAdapter, []),
            ("text_processing", False, TextProcessingAdapter, ["transcription"]),
            ("llm_processing", False, LlmProcessingAdapter, ["transcription"]),
            ("management", False, ManagementAdapter, ["llm_processing"]),
            ("service", False, ServiceAdapter, ["llm_processing"]),
        ]

        for stage_id, required, adapter_cls, depends_on in optional_stages:
            if stage_id in disabled:
                continue
            retries = optional_retries if not required else 0
            continue_on_error = True
            stages.append(
                adapter_cls(
                    StagePolicy(
                        stage_id=stage_id,
                        required=required,
                        continue_on_error=continue_on_error,
                        depends_on=list(depends_on),
                        max_retries=retries,
                    ),
                    self._config,
                )
            )

        return stages


__all__ = [
    "PluginStageAdapter",
    "StagesRegistry",
    "MediaConvertAdapter",
    "TranscriptionAdapter",
    "TextProcessingAdapter",
    "LlmProcessingAdapter",
    "ManagementAdapter",
    "ServiceAdapter",
]
