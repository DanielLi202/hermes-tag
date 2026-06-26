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


def register(ctx):
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
