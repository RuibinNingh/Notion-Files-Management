"""应用版本号（对应原 C# AppVersion.cs）。"""
import os

# 合法渠道
VALID_CHANNELS = ("Status", "Beta")
DEFAULT_CHANNEL = "Beta"

# 基础版本号；对外展示版本会沿用旧规则拼接渠道后缀：2.0.0-Status / 2.0.0-Beta
BASE_VERSION = "2.0.0"

# 打包/发布流水线可注入；开发环境保持 development，避免写死时间误导排查。
BUILD_TIME = os.environ.get("NFM_BUILD_TIME", "development")
RELEASE_TIME = os.environ.get("NFM_RELEASE_TIME", "development")


def current_channel() -> str:
    """
    读取 NFM_CHANNEL 环境变量，校验为合法渠道。
    仅在 bootstrap（main.py / config.py）期间使用一次，结果会写回 config.json。
    """
    ch = os.environ.get("NFM_CHANNEL", "").strip()
    if ch not in VALID_CHANNELS:
        ch = DEFAULT_CHANNEL
    return ch


def normalize_channel(channel: str | None) -> str:
    """规范化渠道名，避免配置文件或环境变量里的异常值污染版本号。"""
    ch = (channel or "").strip()
    if ch not in VALID_CHANNELS:
        return DEFAULT_CHANNEL
    return ch


def version_for_channel(channel: str | None = None) -> str:
    """按旧版命名方式生成展示/更新比较用版本号。"""
    return f"{BASE_VERSION}-{normalize_channel(channel or current_channel())}"


# 当前构建版本号。模块级常量保留给旧调用方；路由会按 config.channel 动态派生。
APP_VERSION = version_for_channel()
