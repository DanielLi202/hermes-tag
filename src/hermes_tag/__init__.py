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
    "register",
]

_FEISHU_EXPORTS = {
    "FeishuTagAdapter",
    "MessageEvent",
    "PlatformConfig",
    "adapter_factory",
}


def _tag_command_help(args: str = "") -> str:
    return (
        "Hermes Tag command. Use /tag help, /tag status, "
        "/tag admin count, or /tag standing ... in an enabled chat."
    )


def register(ctx):
    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "tag",
            _tag_command_help,
            description="Hermes Tag commands",
            args_hint="help | status | admin count | standing ...",
        )
    from .platforms.feishu import register as _register_feishu
    _register_feishu(ctx)
    from .platforms.slack import register as _register_slack
    _register_slack(ctx)
    from .platforms.dingtalk import register as _register_dingtalk
    _register_dingtalk(ctx)


def __getattr__(name: str):
    if name in _FEISHU_EXPORTS:
        from . import platforms as _platforms  # noqa: F401
        from .platforms import feishu as _feishu
        value = getattr(_feishu, name)
        globals()[name] = value
        return value
    raise AttributeError(name)
