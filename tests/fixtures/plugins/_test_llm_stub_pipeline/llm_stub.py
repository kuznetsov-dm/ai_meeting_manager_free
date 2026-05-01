from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import KIND_SUMMARY, PluginOutput, PluginResult


def hook_summary(ctx: HookContext) -> PluginResult:
    text = (
        "## Summary\n"
        "- Stub summary for integration tests.\n\n"
        "## Projects Discussed\n"
        "- Integration Platform\n\n"
        "## Planned Agenda\n"
        "- Review integration status\n"
        "- Align rollout timeline\n\n"
        "## Action Items\n"
        "- [ ] Follow up on integration tests\n"
    )
    result = PluginResult(
        outputs=[PluginOutput(kind=KIND_SUMMARY, content=text, content_type="text/markdown")],
        warnings=[],
    )
    emit_result(ctx, result)
    return None


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(
            KIND_SUMMARY, ArtifactSchema(content_type="text/markdown", user_visible=True)
        )
        ctx.register_hook_handler("derive.after_postprocess", hook_summary, mode="optional", priority=100)
