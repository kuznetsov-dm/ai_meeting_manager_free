import json

from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_TRANSCRIPT,
    PluginOutput,
    PluginResult,
)


def hook_transcribe(ctx: HookContext) -> PluginResult:
    transcript = "hello architecture\n"
    asr = json.dumps({"transcription": [{"text": "hello architecture"}]})
    result = PluginResult(
        outputs=[
            PluginOutput(kind=KIND_TRANSCRIPT, content=transcript, content_type="text"),
            PluginOutput(
                kind=KIND_ASR_SEGMENTS_JSON,
                content=asr,
                content_type="json",
                user_visible=False,
            ),
        ],
        warnings=[],
    )
    emit_result(ctx, result)
    return None


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_TRANSCRIPT, ArtifactSchema(content_type="text", user_visible=True))
        ctx.register_artifact_kind(
            KIND_ASR_SEGMENTS_JSON, ArtifactSchema(content_type="json", user_visible=False)
        )
        ctx.register_hook_handler("transcribe.run", hook_transcribe, mode="optional", priority=100)
