from .core import PlatformSeam, TagConfig as FeishuTagConfig, TagEngine, TagStore as FeishuTagStore
from .base import HermesCronAPI, assert_real_seams

__all__ = [
    "FeishuTagAdapter",
    "FeishuTagConfig",
    "FeishuTagStore",
    "HermesCronAPI",
    "MessageEvent",
    "PlatformConfig",
    "PlatformSeam",
    "TagEngine",
    "adapter_factory",
    "assert_real_seams",
    "check_requirements",
    "register",
]

_FEISHU_EXPORTS = {
    "FeishuTagAdapter",
    "MessageEvent",
    "PlatformConfig",
    "adapter_factory",
    "check_requirements",
}


def _tag_command_help(args: str = "") -> str:
    return (
        "Hermes Tag command. Use /tag help, /tag status, "
        "/tag admin count, or /tag standing ... in an enabled chat."
    )


def _ensure_slack_native_tag_command() -> None:
    """Keep native Slack `/tag` reachable when Hermes clamps at 50 commands.

    Hermes core already includes plugin commands in `slack_native_slashes()`,
    but app manifests and the Slack Socket Mode command matcher are both capped
    at Slack's 50-command limit. On command-heavy installs the third pass
    (plugin commands) can be clamped off, so Slack accepts `/tag` from the
    manifest but the running Bolt app has no matching handler and times out.
    """
    try:
        from hermes_cli import commands as hermes_commands
    except Exception:
        return

    current = getattr(hermes_commands, "slack_native_slashes", None)
    if not callable(current) or getattr(current, "_hermes_tag_patched", False):
        return

    tag_entry = ("tag", "Hermes Tag commands", "help | status | admin count | standing ...")
    max_slashes = int(getattr(hermes_commands, "_SLACK_MAX_SLASH_COMMANDS", 50) or 50)

    def slack_native_slashes_with_tag():
        entries = list(current())
        names = [name for name, _desc, _hint in entries]
        if "tag" in names:
            idx = names.index("tag")
            entries[idx] = tag_entry
            return entries
        if len(entries) < max_slashes:
            entries.append(tag_entry)
            return entries
        for drop in ("version", "usage", "insights"):
            if drop in names:
                entries[names.index(drop)] = tag_entry
                return entries
        if entries:
            entries[-1] = tag_entry
        return entries

    slack_native_slashes_with_tag._hermes_tag_patched = True  # type: ignore[attr-defined]
    slack_native_slashes_with_tag._hermes_tag_original = current  # type: ignore[attr-defined]
    hermes_commands.slack_native_slashes = slack_native_slashes_with_tag


def register(ctx):
    _ensure_slack_native_tag_command()
    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "tag",
            _tag_command_help,
            description="Hermes Tag commands",
            args_hint="help | status | admin count | standing ...",
        )
    from .platforms.feishu import register as _register_feishu
    _register_feishu(ctx)
    try:
        from .platforms.slack import register as _register_slack
        _register_slack(ctx)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("hermes-tag: slack platform registration skipped", exc_info=True)

def __getattr__(name: str):
    if name in _FEISHU_EXPORTS:
        from . import platforms as _platforms  # noqa: F401
        from .platforms import feishu as _feishu
        value = getattr(_feishu, name)
        globals()[name] = value
        return value
    raise AttributeError(name)
