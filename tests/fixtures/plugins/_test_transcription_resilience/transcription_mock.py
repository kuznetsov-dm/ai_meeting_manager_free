from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import KIND_TRANSCRIPT, PluginOutput, PluginResult


def hook_transcribe(ctx: HookContext) -> PluginResult:
    result = PluginResult(
        outputs=[PluginOutput(kind=KIND_TRANSCRIPT, content="hello resilience\n", content_type="text")],
        warnings=[],
    )
    emit_result(ctx, result)
    return None


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_TRANSCRIPT, ArtifactSchema(content_type="text", user_visible=True))
        ctx.register_hook_handler("transcribe.run", hook_transcribe, mode="optional", priority=100)
