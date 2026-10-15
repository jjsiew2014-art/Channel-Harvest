"""
error_classifier.py
Centralized error classification layer and structured error model for Channel Harvest.

Provides:
- ErrorCategory: Canonical enumeration of all error categories.
- DownloadError: Structured dataclass representing a classified failure.
- ErrorClassifier: Evidence-based classifier mapping raw error messages/exceptions
  to human-friendly, actionable diagnostic objects without overclaiming.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Tuple


# =============================================================================
# Canonical Error Categories
# =============================================================================

class ErrorCategory:
    """Canonical error category identifiers."""
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    BOT_VERIFICATION = "BOT_VERIFICATION"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PRIVATE_VIDEO = "PRIVATE_VIDEO"
    VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
    REGION_RESTRICTED = "REGION_RESTRICTED"
    AGE_RESTRICTED = "AGE_RESTRICTED"
    JS_RUNTIME_ERROR = "JS_RUNTIME_ERROR"
    EJS_ERROR = "EJS_ERROR"
    PO_TOKEN_ERROR = "PO_TOKEN_ERROR"
    IMPERSONATION_ERROR = "IMPERSONATION_ERROR"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_429 = "HTTP_429"
    HTTP_500 = "HTTP_500"
    HTTP_502 = "HTTP_502"
    HTTP_503 = "HTTP_503"
    FORMAT_ERROR = "FORMAT_ERROR"
    FFMPEG_ERROR = "FFMPEG_ERROR"
    DISK_SPACE_ERROR = "DISK_SPACE_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    FILE_SYSTEM_ERROR = "FILE_SYSTEM_ERROR"
    FILE_LOCKED = "FILE_LOCKED"
    HTTP_416 = "RANGE_NOT_SATISFIABLE"
    RANGE_NOT_SATISFIABLE = "RANGE_NOT_SATISFIABLE"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

    # Douyin and Authentication Error Categories
    COOKIE_FILE_INVALID = "COOKIE_FILE_INVALID"
    COOKIE_NOT_APPLIED = "COOKIE_NOT_APPLIED"
    DOUYIN_SESSION_REQUIRED = "DOUYIN_SESSION_REQUIRED"
    DOUYIN_API_BLOCKED = "DOUYIN_API_BLOCKED"
    DOUYIN_EXTRACTOR_INCOMPATIBLE = "DOUYIN_EXTRACTOR_INCOMPATIBLE"
    UNKNOWN_EXTRACTION_ERROR = "UNKNOWN_EXTRACTION_ERROR"
    PLATFORM_TEMPORARILY_UNAVAILABLE = "PLATFORM_TEMPORARILY_UNAVAILABLE"

    # Aliases for flexibility and testing compatibility
    PLATFORM_UNAVAILABLE = PLATFORM_TEMPORARILY_UNAVAILABLE
    FILE_ACCESS_CONFLICT = FILE_LOCKED
    HTTP_416_RANGE_NOT_SATISFIABLE = RANGE_NOT_SATISFIABLE
    HTTP_403_FORBIDDEN = HTTP_403
    HTTP_404_NOT_FOUND = HTTP_404
    HTTP_429_TOO_MANY_REQUESTS = HTTP_429
    HTTP_500_SERVER_ERROR = HTTP_500
    HTTP_502_BAD_GATEWAY = HTTP_502
    HTTP_503_SERVICE_UNAVAILABLE = HTTP_503
    EJS_CHALLENGE_FAILED = EJS_ERROR
    DENO_MISSING_OR_BROKEN = JS_RUNTIME_ERROR
    PO_TOKEN_REQUIRED = PO_TOKEN_ERROR
    IMPERSONATION_UNAVAILABLE = IMPERSONATION_ERROR
    DISK_SPACE = DISK_SPACE_ERROR
    FILE_SYSTEM = FILE_SYSTEM_ERROR
    UNKNOWN = UNKNOWN_ERROR
    UNKNOWN_EXTRACTION = UNKNOWN_EXTRACTION_ERROR


# =============================================================================
# Structured DownloadError Model
# =============================================================================

@dataclass
class DownloadError:
    """
    Structured representation of a download failure with both user-facing
    clarity and deep diagnostic fidelity.
    """
    category: str
    title: str
    user_message: str
    suggested_action: str
    technical_details: str
    component: str = "yt-dlp"
    stage: str = "video"  # "video", "audio", "conversion", "subtitle", "thumbnail", "metadata", "scan", "queue"
    http_status: Optional[int] = None
    retryable: bool = False
    concise_status: str = "Failed"
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    raw_error: str = ""
    video_id: str = ""
    video_title: str = ""
    platform: str = "youtube"

    @property
    def message(self) -> str:
        """Alias for user_message for backwards compatibility and clarity."""
        return self.user_message

    def get_localized_title(self, lang: Optional[str] = None) -> str:
        """Returns localized title based on current application language."""
        from core.i18n import I18nManager
        is_zh = (lang.startswith("zh") if lang else I18nManager.is_chinese())
        if not is_zh:
            return self.title
        t = self.title or ""
        translations = {
            "Audio extraction failed": "音频提取失败",
            "Video download failed": "视频下载失败",
            "Audio/Video conversion failed": "音视频合并转换失败",
            "Subtitle download failed": "字幕下载失败",
            "Thumbnail download failed": "封面图下载失败",
            "Channel scanning failed": "频道扫描失败",
            "Download cancelled": "下载已取消",
            "Disk space full": "磁盘存储空间不足",
            "Temporary file permission denied": "临时文件创建权限被拒绝",
            "Permission denied": "写入权限被拒绝",
            "File system error": "文件系统错误",
            "File finalization locked": "文件重命名锁定 (WinError 32)",
            "JavaScript runtime missing": "缺少 JavaScript 运行时 (Deno)",
            "JS challenge solver failure": "JS 挑战求解组件失败",
            "YouTube PO Token required": "需要 YouTube PO Token 验证",
            "Bot verification required": "需要进行人机身份验证",
            "Age-restricted video": "年龄限制视频",
            "Sign-in required": "需要登录 YouTube 账号",
            "Private video": "私享视频无法访问",
            "Video unavailable": "视频不可用",
            "Region restricted": "地区受限视频",
            "Format not available": "所选格式不可用",
            "FFmpeg processing error": "FFmpeg 处理失败",
            "YouTube request rate limited": "请求受到频率限制 (429)",
            "Requested range not satisfiable": "请求范围不可用 (HTTP 416)",
            "Connection timed out": "网络连接超时",
            "Network connection error": "网络连接错误",
            "Cookie file invalid": "Cookie 文件无效",
            "Cookie authentication not applied": "Cookie 认证未应用",
            "Douyin session cookies required": "需要有效的抖音会话 Cookie",
            "Douyin session required": "需要有效的抖音会话 Cookie",
            "Douyin API security block (ArgusSecurityPlugin)": "抖音 API 安全拦截 (ArgusSecurityPlugin)",
            "Douyin API security block": "抖音 API 安全拦截 (ArgusSecurityPlugin)",
            "Douyin API blocked by security plugin": "抖音 API 安全拦截 (ArgusSecurityPlugin)",
            "Douyin extractor incompatible": "抖音提取器兼容性异常",
            "Douyin extraction failed": "抖音视频提取失败",
            "Douyin temporarily unavailable": "抖音暂时不可用",
            "Platform temporarily unavailable": "平台暂时不可用",
            "Temporarily unavailable": "暂时不可用",
            "Unknown extraction error": "提取视频信息失败",
        }
        for en_prefix, zh_prefix in translations.items():
            if t.startswith(en_prefix):
                return t.replace(en_prefix, zh_prefix, 1)
        return t

    def get_localized_user_message(self, lang: Optional[str] = None) -> str:
        """Returns localized user-facing reason message based on current application language."""
        from core.i18n import I18nManager
        is_zh = (lang.startswith("zh") if lang else I18nManager.is_chinese())
        if not is_zh:
            return self.user_message

        if self.title == "Temporary file permission denied" or "temporary directory is not writable" in self.user_message.lower():
            return "Channel Harvest 无法创建临时下载文件，因为配置的临时目录不可写。"

        if self.category == ErrorCategory.IMPERSONATION_ERROR:
            return "TikTok 需要浏览器模拟 (impersonation) 支持，但当前运行环境未提供兼容的模拟目标。"

        if self.platform == "tiktok":
            tiktok_zh_messages = {
                ErrorCategory.CANCELLED: "下载已由用户主动取消。",
                ErrorCategory.HTTP_403: "TikTok 拒绝了请求 (HTTP 403 禁止访问)。",
                ErrorCategory.RATE_LIMITED: "TikTok 暂时对当前网络连接施加了请求频率限制 (HTTP 429)。",
                ErrorCategory.BOT_VERIFICATION: "TikTok 检测到异常请求，要求进行人机身份安全验证。",
                ErrorCategory.LOGIN_REQUIRED: "该视频需要登录 TikTok 账号，或是私密/仅好友可见内容。",
                ErrorCategory.PRIVATE_VIDEO: "该 TikTok 视频已被创作者设为私密，无法公开访问。",
                ErrorCategory.VIDEO_UNAVAILABLE: "该 TikTok 视频不可用，或已被创作者/平台删除。",
                ErrorCategory.REGION_RESTRICTED: "视频上传者限制了该 TikTok 内容在您所在国家或地区的播放权限。",
                ErrorCategory.FORMAT_ERROR: "TikTok 未提供所选择的格式或分辨率。",
                ErrorCategory.FFMPEG_ERROR: "FFmpeg 在进行音视频合并、转码或后期封装处理时发生异常。",
                ErrorCategory.TIMEOUT: "连接 TikTok 服务器超时，网络未能在规定时间内响应。",
                ErrorCategory.NETWORK_ERROR: "无法与 TikTok 服务器建立稳定的网络连接。",
                ErrorCategory.DISK_SPACE_ERROR: "目标磁盘剩余空间不足，无法保存下载内容。",
                ErrorCategory.PERMISSION_ERROR: "Channel Harvest 没有向目标文件夹写入文件的权限。",
                ErrorCategory.FILE_SYSTEM_ERROR: "文件保存路径或视频标题中包含系统不支持的特殊字符，或超出了 Windows 的最长路径限制。",
                ErrorCategory.FILE_LOCKED: "由于受到 Windows 其他进程的临时占用，下载文件无法完成最终重命名。",
                ErrorCategory.UNKNOWN_ERROR: "未能明确识别本次下载失败的具体成因。",
            }
            if self.category in tiktok_zh_messages:
                return tiktok_zh_messages[self.category]

        if self.platform == "douyin":
            douyin_zh_messages = {
                ErrorCategory.CANCELLED: "下载已由用户主动取消。",
                ErrorCategory.HTTP_403: "抖音拒绝了请求 (HTTP 403 禁止访问)。",
                ErrorCategory.RATE_LIMITED: "抖音暂时对当前网络连接施加了请求频率限制 (HTTP 429)。",
                ErrorCategory.BOT_VERIFICATION: "抖音需要有效的会话 Cookie（Fresh cookies）以获取视频详情。请在“设置”中配置抖音身份验证（浏览器 Cookie 或自定义 Cookie 文件）。",
                ErrorCategory.LOGIN_REQUIRED: "该视频需要登录抖音账号，或是私密/仅互关好友可见内容。",
                ErrorCategory.PRIVATE_VIDEO: "该抖音视频已被创作者设为私密，无法公开访问。",
                ErrorCategory.VIDEO_UNAVAILABLE: "该抖音视频不可用，或已被创作者/平台下架删除。",
                ErrorCategory.REGION_RESTRICTED: "视频上传者限制了该抖音内容在您所在地区的播放权限。",
                ErrorCategory.FORMAT_ERROR: "抖音未提供所选择的格式或分辨率。",
                ErrorCategory.FFMPEG_ERROR: "FFmpeg 在进行音视频合并、转码或后期封装处理时发生异常。",
                ErrorCategory.TIMEOUT: "连接抖音服务器超时，网络未能在规定时间内响应。",
                ErrorCategory.NETWORK_ERROR: "无法与抖音服务器建立稳定的网络连接。",
                ErrorCategory.DISK_SPACE_ERROR: "目标磁盘剩余空间不足，无法保存下载内容。",
                ErrorCategory.PERMISSION_ERROR: "Channel Harvest 没有向目标文件夹写入文件的权限。",
                ErrorCategory.FILE_SYSTEM_ERROR: "文件保存路径或视频标题中包含系统不支持的特殊字符，或超出了 Windows 的最长路径限制。",
                ErrorCategory.FILE_LOCKED: "由于受到 Windows 其他进程的临时占用，下载文件无法完成最终重命名。",
                ErrorCategory.COOKIE_FILE_INVALID: "指定的抖音 Cookie 文件不存在、为空或格式无效（需为 Netscape 格式）。",
                ErrorCategory.COOKIE_NOT_APPLIED: "未能成功将 Cookie 配置传递给下载引擎或未检测到可用凭据。",
                ErrorCategory.DOUYIN_SESSION_REQUIRED: "抖音需要有效的会话 Cookie（Fresh cookies）以获取视频详情。当前未配置任何有效的抖音 Cookie。",
                ErrorCategory.DOUYIN_API_BLOCKED: "抖音服务器安全防护组件 (ArgusSecurityPlugin) 拦截了详情请求（缺少有效的设备安全标识 UIFID 或触发了反爬验证）。即使已加载 Cookie 文件，若缺少完整的设备安全挑战令牌亦无法绕过。",
                ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: "yt-dlp 的抖音解析组件 (DouyinIE) 与当前抖音网页接口不兼容或未实现安全挑战求解支持。",
                ErrorCategory.UNKNOWN_EXTRACTION_ERROR: "未能从抖音服务器提取到视频元数据或下载地址。",
                ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: "抖音暂时不可用 — 等待 yt-dlp 上游修复。目前抖音服务器端的 ArgusSecurityPlugin 安全防护机制 (HTTP 403) 阻止了视频详情解析。",
                ErrorCategory.UNKNOWN_ERROR: "未能明确识别本次下载失败的具体成因。",
            }
            if self.category in douyin_zh_messages:
                return douyin_zh_messages[self.category]

        cat_messages = {
            ErrorCategory.CANCELLED: "下载已由用户主动取消。",
            ErrorCategory.FILE_LOCKED: "由于受到 Windows 其他进程（如杀毒软件扫描、文件索引或云盘同步）的临时占用，下载文件无法完成最终重命名。",
            ErrorCategory.DISK_SPACE_ERROR: "目标磁盘剩余空间不足，无法保存下载内容。",
            ErrorCategory.PERMISSION_ERROR: "Channel Harvest 没有向目标文件夹写入文件的权限。",
            ErrorCategory.FILE_SYSTEM_ERROR: "文件保存路径或视频标题中包含系统不支持的特殊字符，或超出了 Windows 的最长路径限制。",
            ErrorCategory.COOKIE_FILE_INVALID: "指定的 Cookie 文件不存在、为空或格式无效（需为 Netscape 格式）。",
            ErrorCategory.COOKIE_NOT_APPLIED: "未能成功将 Cookie 配置传递给下载引擎。",
            ErrorCategory.DOUYIN_SESSION_REQUIRED: "抖音需要有效的会话 Cookie 以获取视频详情。当前未配置任何有效的抖音 Cookie。",
            ErrorCategory.DOUYIN_API_BLOCKED: "抖音服务器安全防护组件 (ArgusSecurityPlugin) 拦截了详情请求（缺少有效的设备安全标识 UIFID 或触发了反爬验证）。",
            ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: "yt-dlp 的抖音解析组件与当前抖音网页接口不兼容。",
            ErrorCategory.UNKNOWN_EXTRACTION_ERROR: "提取视频信息失败。",
            ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: "该平台目前处于暂时停用状态 — 等待上游修复更新。",
            ErrorCategory.JS_RUNTIME_ERROR: "yt-dlp 需要 JavaScript 运行环境 (Deno) 来解析 YouTube 视频请求验证。",
            ErrorCategory.EJS_ERROR: "YouTube JavaScript 验证求解组件执行失败或未能成功加载。",
            ErrorCategory.PO_TOKEN_ERROR: "YouTube 要求提供有效的 Proof of Origin (PO) Token 或访客标识数据方可拉取视频流。",
            ErrorCategory.BOT_VERIFICATION: "YouTube 检测到频繁请求，要求进行人机身份验证。",
            ErrorCategory.AGE_RESTRICTED: "该视频已被标记为年龄限制内容，需要登录已满法定年龄的 YouTube 账号方可观看。",
            ErrorCategory.LOGIN_REQUIRED: "该视频需要登录 YouTube 账号，或是频道会员专属内容。",
            ErrorCategory.PRIVATE_VIDEO: "该视频已被创作者设为私享（Private），无法公开访问。",
            ErrorCategory.VIDEO_UNAVAILABLE: "该视频不可用，或已被创作者/平台下架删除。",
            ErrorCategory.REGION_RESTRICTED: "视频上传者限制了该内容在您所在国家或地区的播放权限。",
            ErrorCategory.FORMAT_ERROR: "YouTube 服务器未提供所选择的分辨率或封装格式。",
            ErrorCategory.FFMPEG_ERROR: "FFmpeg 在进行音视频合并、转码或后期封装处理时发生异常。",
            ErrorCategory.RANGE_NOT_SATISFIABLE: "断点续传失败：服务器拒绝了请求的文件字节范围。Channel Harvest 已自动重置损坏的临时分块并尝试重新完整下载。若仍失败，建议稍后重试。",
            ErrorCategory.RATE_LIMITED: "YouTube 暂时对当前网络连接施加了请求频率限制 (HTTP 429)。",
            ErrorCategory.HTTP_403: "YouTube 服务器暂时拒绝了音视频流的拉取请求 (HTTP 403 Forbidden)。",
            ErrorCategory.HTTP_404: "在远程服务器上未找到请求的媒体流或资源 (HTTP 404)。",
            ErrorCategory.HTTP_500: "YouTube 服务器端暂时发生内部错误或服务不可用 (HTTP 500)。",
            ErrorCategory.HTTP_502: "YouTube 服务器网关异常 (HTTP 502 Bad Gateway)。",
            ErrorCategory.HTTP_503: "YouTube 服务器当前服务不可用或过载 (HTTP 503)。",
            ErrorCategory.TIMEOUT: "连接 YouTube 服务器超时，网络未能在规定时间内响应。",
            ErrorCategory.NETWORK_ERROR: "无法与 YouTube 服务器建立稳定的网络连接。",
            ErrorCategory.UNKNOWN_ERROR: "未能明确识别本次下载失败的具体成因。",
        }
        return cat_messages.get(self.category, self.user_message)

    def get_localized_suggested_action(self, lang: Optional[str] = None) -> str:
        """Returns localized actionable guidance based on current application language."""
        from core.i18n import I18nManager
        is_zh = (lang.startswith("zh") if lang else I18nManager.is_chinese())
        if not is_zh:
            return self.suggested_action

        if self.title == "Temporary file permission denied" or "temporary directory is not writable" in self.user_message.lower():
            return (
                "• 检查 Windows 用户临时目录 (%TEMP%) 的读写权限。\n"
                "• 重启 Channel Harvest 以重置临时工作空间。\n"
                "• 避免在受限的系统目录中运行本软件。"
            )

        if self.category == ErrorCategory.IMPERSONATION_ERROR:
            return (
                "• 确保应用程序运行环境中已安装 curl_cffi 核心组件。\n"
                "• 请前往“设置”>“下载组件”检查浏览器伪装支持状态。\n"
                "• 重启 Channel Harvest 以刷新已加载的运行组件。"
            )

        if self.platform == "tiktok":
            tiktok_zh_actions = {
                ErrorCategory.CANCELLED: "您可以随时恢复或重新启动下载队列。",
                ErrorCategory.HTTP_403: (
                    "• TikTok 服务器暂时拒绝了该请求或对当前 IP 施加了访问限制。\n"
                    "• 请稍候片刻重试，等待服务器临时限制解除。\n"
                    "• 避免短时间内连续并发下载大量 TikTok 视频。\n"
                    "• 若问题持续，请在浏览器中打开链接确认视频是否能正常公开播放。"
                ),
                ErrorCategory.RATE_LIMITED: (
                    "• 请稍等几分钟后再继续下载。\n"
                    "• Channel Harvest 会自动按策略退避并进行重试。"
                ),
                ErrorCategory.BOT_VERIFICATION: (
                    "• 请在常用浏览器中打开 TikTok 并完成安全验证提示。\n"
                    "• 请稍候几分钟后再尝试下载。\n"
                    "• 避免短时间内发起极高频次的批量下载请求。"
                ),
                ErrorCategory.LOGIN_REQUIRED: (
                    "• 请确认该视频是否需要登录 TikTok 账号方可观看。\n"
                    "• 检查该视频或创作者主页是否已设为仅好友可见或访问受限。"
                ),
                ErrorCategory.PRIVATE_VIDEO: (
                    "• 请确认创作者是否已将该视频设为私密状态。"
                ),
                ErrorCategory.VIDEO_UNAVAILABLE: (
                    "• 请在浏览器中打开链接，确认该视频是否仍然存在且能正常访问。"
                ),
                ErrorCategory.REGION_RESTRICTED: (
                    "• 该内容在您当前的地理区域不可用。\n"
                    "• 若正在使用代理或 VPN，可尝试切换至内容支持的地区节点。"
                ),
                ErrorCategory.TIMEOUT: (
                    "• 请检查当前网络连接的通畅度与连接速度。\n"
                    "• Channel Harvest 会自动安排延时重试。"
                ),
                ErrorCategory.NETWORK_ERROR: (
                    "• 请检查本地网络或 Wi-Fi 连接是否正常。\n"
                    "• 若开启了系统代理、防火墙或 VPN，请检查其配置是否正常。"
                ),
            }
            if self.category in tiktok_zh_actions:
                return tiktok_zh_actions[self.category]

        if self.platform == "douyin":
            douyin_zh_actions = {
                ErrorCategory.CANCELLED: "您可以随时恢复或重新启动下载队列。",
                ErrorCategory.HTTP_403: (
                    "• 抖音服务器暂时拒绝了该请求或对当前 IP 施加了访问限制。\n"
                    "• 请稍候片刻重试，等待服务器临时限制解除。\n"
                    "• 避免短时间内连续并发下载大量抖音视频。\n"
                    "• 若问题持续，请在浏览器中打开链接确认视频是否能正常公开播放。"
                ),
                ErrorCategory.RATE_LIMITED: (
                    "• 请稍等几分钟后再继续下载。\n"
                    "• Channel Harvest 会自动按策略退避并进行重试。"
                ),
                ErrorCategory.BOT_VERIFICATION: (
                    "• 请前往“设置”>“身份验证”，选择“抖音”。\n"
                    "• 选择“浏览器 Cookie”（Chrome/Edge/Firefox）或导入有效的 Cookie 文件 (cookies.txt)。\n"
                    "• 若 Cookie 已过期，请在浏览器中打开 douyin.com 刷新登录状态。"
                ),
                ErrorCategory.LOGIN_REQUIRED: (
                    "• 请确认该视频是否需要登录抖音账号方可观看。\n"
                    "• 检查该视频是否已设为私密或仅互关好友可见。"
                ),
                ErrorCategory.PRIVATE_VIDEO: (
                    "• 请确认创作者是否已将该抖音视频设为私密状态。"
                ),
                ErrorCategory.VIDEO_UNAVAILABLE: (
                    "• 请在浏览器中打开链接，确认该视频是否仍然存在且能正常访问。"
                ),
                ErrorCategory.REGION_RESTRICTED: (
                    "• 该内容在您当前的地理区域不可用。\n"
                    "• 若正在使用代理或 VPN，可尝试切换至内容支持的地区节点。"
                ),
                ErrorCategory.TIMEOUT: (
                    "• 请检查当前网络连接的通畅度与连接速度。\n"
                    "• Channel Harvest 会自动安排延时重试。"
                ),
                ErrorCategory.NETWORK_ERROR: (
                    "• 请检查本地网络或 Wi-Fi 连接是否正常。\n"
                    "• 若开启了系统代理、防火墙或 VPN，请检查其配置是否正常。"
                ),
                ErrorCategory.COOKIE_FILE_INVALID: (
                    "• 请确认在“设置”>“身份验证”中选择的 Cookie 文件路径正确且文件可读。\n"
                    "• 确保导出的 Cookie 文件为标准的 Netscape HTTP Cookie 格式。\n"
                    "• 避免使用空白或已损坏的文本文件。"
                ),
                ErrorCategory.COOKIE_NOT_APPLIED: (
                    "• 请在“设置”>“身份验证”中重新选择并保存抖音 Cookie 配置。\n"
                    "• 重启 Channel Harvest 以确保认证配置生效。"
                ),
                ErrorCategory.DOUYIN_SESSION_REQUIRED: (
                    "• 请前往“设置”>“身份验证”，选择“抖音”。\n"
                    "• 选择“浏览器 Cookie”（Chrome/Edge/Firefox）或导入有效的 Cookie 文件 (cookies.txt)。\n"
                    "• 若 Cookie 已过期，请在浏览器中打开 douyin.com 刷新登录状态。"
                ),
                ErrorCategory.DOUYIN_API_BLOCKED: (
                    "• 抖音目前通过 ArgusSecurityPlugin 及设备安全标识 (UIFID / x-tt-argus) 进行反爬防护。\n"
                    "• 请在浏览器中访问该抖音视频并完成滑动验证/安全校验后，重新导出最新的完整 Cookie 文件。\n"
                    "• 确认 Cookie 文件中包含经过校验的 UIFID 或 sessionid 字段。\n"
                    "• 关注 yt-dlp 后续版本更新（yt-dlp 暂未内置针对抖音安全插件的 challenge 求解器）。"
                ),
                ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: (
                    "• 请检查软件是否运行最新兼容版本的 yt-dlp 组件。\n"
                    "• 在浏览器中确认该链接是否能在网页端正常播放。\n"
                    "• 可向 yt-dlp 或 Channel Harvest 反馈该视频链接以获取适配更新。"
                ),
                ErrorCategory.UNKNOWN_EXTRACTION_ERROR: (
                    "• 请稍后重试，或在浏览器中打开视频确认播放状态。\n"
                    "• 检查网络连接是否正常。"
                ),
                ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: (
                    "• 抖音支持目前处于临时冻结状态，等待 yt-dlp 官方提供支持安全挑战求解的提取器更新。\n"
                    "• 请切换至 YouTube 或 TikTok 进行媒体下载。"
                ),
            }
            if self.category in douyin_zh_actions:
                return douyin_zh_actions[self.category]

        cat_actions = {
            ErrorCategory.CANCELLED: "您可以随时恢复或重新启动下载队列。",
            ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: "• 该平台目前处于暂时停用状态。\n• 请切换至其他可用平台进行媒体下载。",
            ErrorCategory.COOKIE_FILE_INVALID: "• 请确认选择的 Cookie 文件路径正确且为标准的 Netscape 格式。\n• 避免使用空白或已损坏的文本文件。",
            ErrorCategory.COOKIE_NOT_APPLIED: "• 请在设置中重新选择并保存 Cookie 配置。\n• 重启软件后重试。",
            ErrorCategory.DOUYIN_SESSION_REQUIRED: "• 请前往“设置”>“身份验证”，选择“抖音”并配置 Cookie。\n• 在浏览器中打开 douyin.com 刷新登录状态。",
            ErrorCategory.DOUYIN_API_BLOCKED: "• 抖音安全防护组件 (ArgusSecurityPlugin) 拦截了请求。\n• 请在浏览器中完成安全验证后重新导出包含 UIFID 的 Cookie。\n• 关注 yt-dlp 提取器后续更新。",
            ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: "• 请检查 yt-dlp 组件版本。\n• 确认该链接在浏览器中能否正常播放。",
            ErrorCategory.UNKNOWN_EXTRACTION_ERROR: "• 请稍后重试，或在浏览器中打开视频确认播放状态。\n• 检查网络连接是否正常。",
            ErrorCategory.FILE_LOCKED: "• 请稍候片刻，等待 Windows 或杀毒软件完成对文件的扫描。\n• 可临时将下载目标文件夹加入杀毒软件的实时扫描排除名单。\n• 若开启了云盘同步（如 OneDrive、Google Drive 等），可暂时暂停同步。\n• 请关闭可能已打开该临时文件的播放器或文件管理器。",
            ErrorCategory.DISK_SPACE_ERROR: "• 请清理目标驱动器的存储空间。\n• 或者在软件设置中将下载保存路径更改为空间充足的磁盘。",
            ErrorCategory.PERMISSION_ERROR: "• 请选择拥有写入权限的保存目录（例如系统的“下载”或“视频”文件夹）。\n• 检查目标文件是否被其他应用程序占用或设为只读。",
            ErrorCategory.FILE_SYSTEM_ERROR: "• 请选择路径较短的保存文件夹（例如 C:\\Downloads）。\n• 检查下载目录设置。",
            ErrorCategory.JS_RUNTIME_ERROR: "• 请打开“设置”>“下载组件”检查 Deno 组件状态。\n• 确保软件目录下的 runtime/deno.exe 完整存在。",
            ErrorCategory.EJS_ERROR: "• 请检查当前网络连接是否顺畅。\n• 可在“设置”>“下载组件”中检查并更新 yt-dlp 及 EJS 核心组件。",
            ErrorCategory.PO_TOKEN_ERROR: "• 请前往“设置”>“YOUTUBE 登录”配置本地浏览器 Cookie 会话。\n• 或在默认浏览器中登录 YouTube 后重试。",
            ErrorCategory.BOT_VERIFICATION: "• 请在常用浏览器中打开 YouTube 并完成人机验证提示。\n• 前往“设置”>“YOUTUBE 登录”选择导入浏览器的 Cookie。\n• 避免短时间内发起极高频次的批量下载请求。",
            ErrorCategory.AGE_RESTRICTED: "• 请在“设置”>“YOUTUBE 登录”中选择已登录成年账号的浏览器 Cookie。\n• 请确认在浏览器中能够正常播放该视频。",
            ErrorCategory.LOGIN_REQUIRED: "• 请在“设置”>“YOUTUBE 登录”中配置浏览器 Cookie。\n• 请确认该视频是否为付费会员专享或需要额外订阅权限。",
            ErrorCategory.PRIVATE_VIDEO: "• 请确认视频创作者是否将其设为了非公开或私享状态。",
            ErrorCategory.VIDEO_UNAVAILABLE: "• 请在浏览器中打开链接，确认该视频是否仍然存在且能正常播放。",
            ErrorCategory.REGION_RESTRICTED: "• 该视频在您当前的地理区域不可用。\n• 若正在使用代理或 VPN，可尝试切换至视频支持的地区节点。",
            ErrorCategory.FORMAT_ERROR: "• 在主界面的“下载选项”中，将视频分辨率调整为“最高分辨率”。\n• 或尝试将视频格式由 MOV/WEBM 改选为 MP4。",
            ErrorCategory.FFMPEG_ERROR: "• 请前往“设置”>“下载组件”，确认 FFmpeg 组件已正常就绪。\n• 检查目标保存磁盘是否可写且有足够的剩余容量。",
            ErrorCategory.RANGE_NOT_SATISFIABLE: "• 软件已自动清理冲突的断点续传缓存并重试。\n• 若问题依然存在，可能是该视频流临时下载地址已过期，建议稍后重新下载该视频。",
            ErrorCategory.RATE_LIMITED: "• 请稍等几分钟后再继续下载。\n• Channel Harvest 会自动按策略退避并进行重试。",
            ErrorCategory.HTTP_403: "• 请稍后重试，或避免同时并发下载大量视频。\n• 若频繁出现，建议在“设置”>“YOUTUBE 登录”中导入浏览器 Cookie。",
            ErrorCategory.HTTP_404: "• 请在浏览器中检查该视频是否已被删除或替换。\n• 重新扫描频道或刷新视频列表后重试。",
            ErrorCategory.HTTP_500: "• YouTube 服务器当前可能正遭遇短暂故障。\n• 软件会自动重试，您也可以稍后再次尝试。",
            ErrorCategory.HTTP_502: "• YouTube 服务器当前可能正遭遇短暂故障。\n• 软件会自动重试，您也可以稍后再次尝试。",
            ErrorCategory.HTTP_503: "• YouTube 服务器当前可能正遭遇短暂故障。\n• 软件会自动重试，您也可以稍后再次尝试。",
            ErrorCategory.TIMEOUT: "• 请检查当前网络连接的通畅度与连接速度。\n• Channel Harvest 会自动安排延时重试。",
            ErrorCategory.NETWORK_ERROR: "• 请检查本地网络或 Wi-Fi 连接是否正常。\n• 若开启了系统代理、防火墙或 VPN，请检查其配置与规则是否正常。",
            ErrorCategory.UNKNOWN_ERROR: "• 请查看下方的技术详情，或复制错误报告以便进一步排查。\n• 建议重新尝试下载，或在浏览器中打开视频确认播放状态。",
        }
        return cat_actions.get(self.category, self.suggested_action)

    def to_report(self, runtime_info: Optional[Dict[str, str]] = None) -> str:
        """
        Generates a clean, standardized, sanitized troubleshooting report
        suitable for copying to clipboard or sending in bug reports.
        Guarantees that no tokens, cookies, or secrets are leaked.
        """
        from core.diagnostics import PrivacySanitizer

        r_info = runtime_info or {}
        yt_ver = r_info.get("yt-dlp", "Unknown")
        ejs_ver = r_info.get("ejs", "Unknown")
        deno_ver = r_info.get("deno", "Unknown")
        ffmpeg_ver = r_info.get("ffmpeg", "Unknown")

        sanitized_tech = PrivacySanitizer.sanitize_message(self.technical_details or self.raw_error)
        sanitized_title = PrivacySanitizer.sanitize_message(self.video_title or "Unknown")

        stage_display = " ".join(word.capitalize() for word in self.stage.split()) if self.stage else "General"

        lines = [
            "Channel Harvest Error Report",
            "============================",
            f"Video: {sanitized_title}",
            f"Video ID: {self.video_id or 'Unknown'}",
            f"Stage: {stage_display}",
            f"Error Category: {self.category}",
            f"Component: {self.component}",
        ]
        if self.http_status:
            lines.append(f"HTTP Status: {self.http_status}")
        lines.extend([
            "",
            "Reason:",
            self.user_message,
            "",
            "What you can do:",
            self.suggested_action,
            "",
            "Technical Error:",
            sanitized_tech,
            "",
            f"Timestamp: {self.timestamp}",
            "",
            "Runtime:",
            f"  yt-dlp: {yt_ver}",
            f"  EJS: {ejs_ver}",
            f"  Deno: {deno_ver}",
            f"  FFmpeg: {ffmpeg_ver}",
        ])
        return "\n".join(lines)


# =============================================================================
# Centralized Error Classifier
# =============================================================================

class ErrorClassifier:
    """
    Evidence-based classifier mapping raw error messages and exceptions
    to structured DownloadError instances.
    """

    # Regex to extract HTTP status code from error strings
    _HTTP_STATUS_RE = re.compile(r"(?:HTTP\s+(?:Error\s+)?|code\s+|status\s+)(\d{3})\b", re.IGNORECASE)

    @classmethod
    def extract_http_status(cls, error_text: str) -> Optional[int]:
        """Extracts 3-digit HTTP status code if present in the error string."""
        match = cls._HTTP_STATUS_RE.search(error_text)
        if match:
            try:
                code = int(match.group(1))
                if 400 <= code <= 599:
                    return code
            except (ValueError, TypeError):
                pass
        return None

    @classmethod
    def classify(
        cls,
        raw_error: str,
        component: Optional[str] = None,
        stage: Optional[str] = None,
        video_id: str = "",
        video_title: str = "",
        platform: Optional[str] = None,
    ) -> DownloadError:
        """
        Classifies raw error string into a structured DownloadError.
        Strictly evidence-based: does not overclaim.
        """
        from core.diagnostics import PrivacySanitizer

        raw_clean = str(raw_error or "").strip()
        sanitized_raw = PrivacySanitizer.sanitize_message(raw_clean)
        low = sanitized_raw.lower()

        # Detect platform context
        plat = (platform or "").lower().strip()
        if not plat:
            if any(term in low for term in ("[tiktok]", "tiktok.com", "api.tiktokv.com", "tiktok extractor")):
                plat = "tiktok"
            elif any(term in low for term in ("[douyin]", "douyin.com", "iesdouyin.com", "douyin extractor")):
                plat = "douyin"
            else:
                plat = "youtube"
        is_tiktok = (plat == "tiktok")
        is_douyin = (plat == "douyin")

        # Infer execution stage if not explicitly provided
        st = (stage or "").lower()
        if not st:
            if "audio pass" in low or "audio download" in low or "extracting audio" in low or "[extractaudio]" in low or "extractaudio" in low:
                st = "audio"
            elif "video pass" in low or "video download" in low:
                st = "video"
            elif "conversion" in low or "muxing" in low or "postprocessing" in low or "[ffmpeg]" in low:
                st = "conversion"
            elif "subtitle" in low:
                st = "subtitle"
            elif "thumbnail" in low:
                st = "thumbnail"
            elif "scan" in low or "channel" in low:
                st = "scan"
            else:
                st = "video"

        # Determine stage title prefix
        if st == "audio":
            stage_title = "Audio extraction failed"
        elif st == "conversion":
            stage_title = "Audio/Video conversion failed"
        elif st == "subtitle":
            stage_title = "Subtitle download failed"
        elif st == "thumbnail":
            stage_title = "Thumbnail download failed"
        elif st == "scan":
            stage_title = "Channel scanning failed"
        else:
            stage_title = "Video download failed"

        # Extract HTTP status code if present
        http_code = cls.extract_http_status(sanitized_raw)

        # ---------------------------------------------------------------------
        # 0. Browser Impersonation Missing / Unavailable (Fail Fast)
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "the extractor is attempting impersonation, but no impersonate target is available",
            "no impersonate target is available",
            "no available impersonate target",
            "impersonate target is unavailable",
            "impersonate targets were requested",
        )):
            return DownloadError(
                category=ErrorCategory.IMPERSONATION_ERROR,
                title="Browser impersonation unavailable",
                user_message="TikTok requires browser impersonation support, but the current runtime does not provide a compatible impersonation target.",
                suggested_action=(
                    "• Ensure curl_cffi is installed in the application runtime.\n"
                    "• Verify available impersonation targets in Settings > Runtime.\n"
                    "• Restart Channel Harvest to detect installed components."
                ),
                technical_details=sanitized_raw,
                component="yt-dlp (curl_cffi)",
                stage=st,
                http_status=403 if http_code == 403 else None,
                retryable=False,
                concise_status="Failed — Impersonation error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="tiktok" if is_tiktok else plat,
            )

        # ---------------------------------------------------------------------
        # 0.0 Platform Temporarily Unavailable / Frozen
        # ---------------------------------------------------------------------
        if (
            "platform_temporarily_unavailable" in low
            or "temporarily unavailable" in low
            or "暂时不可用" in sanitized_raw
        ):
            target_plat = plat or ("douyin" if (is_douyin or "douyin" in low or "抖音" in sanitized_raw) else "unknown")
            return cls.for_unavailable_platform(
                platform_id=target_plat,
                reason=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                stage=st,
            )

        # ---------------------------------------------------------------------
        # 0.1 Cookie Validation & Application Errors
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "cookie_file_invalid",
            "cookie file is invalid",
            "cookie file does not exist",
            "cookie file is empty",
            "not look like a netscape format",
            "invalid cookie file",
            "cookie file not found",
            "cookie file contains no douyin cookies",
        )):
            return DownloadError(
                category=ErrorCategory.COOKIE_FILE_INVALID,
                title="Cookie file invalid",
                user_message="The specified cookie file does not exist, is empty, or is not in valid Netscape format.",
                suggested_action=(
                    "• Ensure the cookie file path in Settings > Authentication is correct.\n"
                    "• Export cookies in standard Netscape HTTP format using a browser extension.\n"
                    "• Verify that the cookie file is readable and non-empty."
                ),
                technical_details=sanitized_raw,
                component="Authentication",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — Cookie file invalid",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="douyin" if is_douyin else plat,
            )

        if any(term in low for term in (
            "cookie_not_applied",
            "cookies could not be applied",
            "cookie authentication not applied",
        )):
            return DownloadError(
                category=ErrorCategory.COOKIE_NOT_APPLIED,
                title="Cookie authentication not applied",
                user_message="The configured cookie authentication could not be applied to the download engine.",
                suggested_action=(
                    "• Re-select and save your authentication settings in Settings > Authentication.\n"
                    "• Restart Channel Harvest to refresh configuration state."
                ),
                technical_details=sanitized_raw,
                component="Authentication",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — Cookie not applied",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="douyin" if is_douyin else plat,
            )

        # ---------------------------------------------------------------------
        # 0.2 Douyin API Blocked by ArgusSecurityPlugin / Security Challenge
        # ---------------------------------------------------------------------
        has_argus_block = (
            "douyin_api_blocked" in low
            or "argussecurityplugin" in low
            or "uifid not found" in low
            or ((is_douyin or "[douyin]" in low or "douyin.com" in low) and "fresh cookies" in low and any(
                c in low for c in ("cookie", "cookies were provided", "custom cookie file", "auth: custom cookie file", "passing verified cookie file")
            ))
        )
        if has_argus_block:
            return DownloadError(
                category=ErrorCategory.DOUYIN_API_BLOCKED,
                title="Douyin API security block (ArgusSecurityPlugin)",
                user_message="Douyin's Argus security system (ArgusSecurityPlugin) blocked the video detail request. Even though cookies were provided, Douyin rejected the request because it lacks an interactive device token (UIFID) or triggered anti-scraping protection.",
                suggested_action=(
                    "• Douyin now requires dynamic device tokens (UIFID / x-tt-argus) generated during interactive browser sessions.\n"
                    "• Open douyin.com in your browser, complete any interactive verification/slide captcha, and re-export the complete cookie file.\n"
                    "• Note that yt-dlp currently lacks a challenge solver for Douyin's ArgusSecurityPlugin."
                ),
                technical_details=sanitized_raw,
                component="Douyin / ArgusSecurityPlugin",
                stage=st,
                http_status=403 if http_code == 403 else None,
                retryable=False,
                concise_status="Failed — Argus security block",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="douyin",
            )

        # ---------------------------------------------------------------------
        # 0.3 Douyin Session Cookies Required (No Cookies Configured)
        # ---------------------------------------------------------------------
        if (is_douyin or "douyin" in low or "[douyin]" in low) and (
            "douyin_session_required" in low
            or any(term in low for term in ("fresh cookies", "s_v_web_id", "session cookies required"))
        ):
            return DownloadError(
                category=ErrorCategory.DOUYIN_SESSION_REQUIRED,
                title="Douyin session required",
                user_message="Douyin requires fresh session cookies to retrieve video details. No active Douyin cookies were configured.",
                suggested_action=(
                    "• Go to Settings > Douyin Authentication.\n"
                    "• Select Browser Cookies (Chrome/Edge/Firefox) or specify a Custom Cookie File (cookies.txt).\n"
                    "• Open Douyin in your browser to establish session cookies."
                ),
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp",
                stage=st,
                http_status=403 if http_code == 403 else None,
                retryable=False,
                concise_status="Failed — Fresh cookies required",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="douyin",
            )

        # ---------------------------------------------------------------------
        # 0.4 Douyin Extractor Incompatibility
        # ---------------------------------------------------------------------
        if (is_douyin or "douyin" in low or "[douyin]" in low) and (
            "douyin_extractor_incompatible" in low
            or ("unsupported url" in low and ("douyin.com" in low or "iesdouyin.com" in low or is_douyin))
            or "douyinie" in low
        ):
            return DownloadError(
                category=ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE,
                title="Douyin extractor incompatible",
                user_message="yt-dlp's Douyin extractor (DouyinIE) is unable to process this Douyin URL or the page structure has changed.",
                suggested_action=(
                    "• Check if an updated version of yt-dlp is available in Settings > Downloads.\n"
                    "• Verify that the video link can be played in a web browser.\n"
                    "• Douyin frequently modifies its web layout and API parameters."
                ),
                technical_details=sanitized_raw,
                component="yt-dlp (DouyinIE)",
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Extractor incompatible",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="douyin",
            )

        # ---------------------------------------------------------------------
        # 0.5 Unknown Extraction Error (Douyin)
        # ---------------------------------------------------------------------
        if (is_douyin or "douyin" in low or "[douyin]" in low) and (
            "unknown_extraction_error" in low
        ):
            return DownloadError(
                category=ErrorCategory.UNKNOWN_EXTRACTION_ERROR,
                title="Douyin extraction failed",
                user_message="Failed to extract Douyin video information or media streams.",
                suggested_action=(
                    "• Please retry the operation after a few moments.\n"
                    "• Verify your network connection and check if the video is publicly accessible."
                ),
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp",
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Extraction error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="douyin",
            )

        # ---------------------------------------------------------------------
        # 1. User Cancellation
        # ---------------------------------------------------------------------
        if any(term in low for term in ("cancelled", "canceled", "downloadcancelledexception", "aborted by user")):
            return DownloadError(
                category=ErrorCategory.CANCELLED,
                title="Download cancelled",
                user_message="The download was stopped by user request.",
                suggested_action="You can resume or restart downloads at any time.",
                technical_details="Operation cancelled by user.",
                component="System",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Cancelled",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 2. Windows File Locking / Access Conflict (WinError 32)
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "[winerror 32]",
            "winerror 32",
            "being used by another process",
            "unable to rename file",
            "file is being used by another process",
        )):
            return DownloadError(
                category=ErrorCategory.FILE_LOCKED,
                title="File finalization locked",
                user_message="The downloaded file could not be finalized because it is temporarily locked by another Windows process (such as antivirus scanning, file indexer, or cloud sync).",
                suggested_action="• Wait a few moments for Windows/antivirus to finish scanning the file.\n• Temporarily exclude the download directory from real-time antivirus scanning.\n• Pause cloud synchronization (OneDrive, Google Drive, Dropbox) for the download folder.\n• Close any applications (media players, file explorers) that may have opened the partial file.",
                technical_details=sanitized_raw,
                component="Windows File System",
                stage=stage if stage else "File Finalization",
                http_status=None,
                retryable=False,
                concise_status="Failed — File locked",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 3. Local File System & Disk Space Errors
        # ---------------------------------------------------------------------
        if any(term in low for term in ("no space left on device", "disk full", "not enough disk space", "errno 28")):
            return DownloadError(
                category=ErrorCategory.DISK_SPACE_ERROR,
                title="Disk space full",
                user_message="The destination disk does not have enough free space to save this download.",
                suggested_action="• Free up storage space on your target drive.\n• Or change the download destination folder in Settings.",
                technical_details=sanitized_raw,
                component="FileSystem",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — Disk full",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        if any(term in low for term in ("permission denied", "errno 13", "access is denied")):
            is_temp_permission = bool(
                re.search(r"[\'\"].*?(?:tmp|temp).*?\.tmp[\'\"]", low)
                or any(t in low for t in ("system32", "windows\\system32", "\\temp\\", "\\tmp\\", "temporary directory", "temporary file"))
                or (".tmp" in low and ("permission denied" in low or "errno 13" in low))
            )
            if is_temp_permission:
                return DownloadError(
                    category=ErrorCategory.PERMISSION_ERROR,
                    title="Temporary file permission denied",
                    user_message="Channel Harvest could not create a temporary download file because the configured temporary directory is not writable.",
                    suggested_action=(
                        "• Verify that your Windows user temporary directory (%TEMP%) is accessible and writable.\n"
                        "• Restart Channel Harvest to reset the temporary workspace.\n"
                        "• Avoid running the application in a restricted system directory."
                    ),
                    technical_details=sanitized_raw,
                    component="FileSystem",
                    stage=st,
                    http_status=None,
                    retryable=False,
                    concise_status="Failed — Temp dir not writable",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                    platform=plat,
                )

            return DownloadError(
                category=ErrorCategory.PERMISSION_ERROR,
                title="Permission denied",
                user_message="Channel Harvest was denied permission to write files into the destination folder.",
                suggested_action="• Choose a destination folder with write permissions (e.g. Downloads or Videos).\n• Check whether another program has locked the file.",
                technical_details=sanitized_raw,
                component="FileSystem",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — Permission error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        if any(term in low for term in ("filename too long", "invalid argument", "errno 22", "illegal byte sequence")):
            return DownloadError(
                category=ErrorCategory.FILE_SYSTEM_ERROR,
                title="File system error",
                user_message="The file path or title contains invalid characters or exceeds Windows path limits.",
                suggested_action="• Select a shorter destination path closer to the drive root (e.g. C:\\Downloads).\n• Check folder path settings.",
                technical_details=sanitized_raw,
                component="FileSystem",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — File system error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 3. JavaScript Runtime & EJS Component Errors (Evidence-based)
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "no supported javascript runtime",
            "could not find a javascript runtime",
            "deno could not be found",
            "executable not found: deno",
            "deno runtime missing",
            "deno: command not found",
            "deno executable not found",
        )):
            return DownloadError(
                category=ErrorCategory.JS_RUNTIME_ERROR,
                title="JavaScript runtime missing",
                user_message="yt-dlp requires a JavaScript runtime (Deno) to solve YouTube extraction challenges.",
                suggested_action="• Open Settings > Runtime Manager and verify Deno runtime status.\n• Ensure runtime/deno.exe exists in the application directory.",
                technical_details=sanitized_raw,
                component="Deno",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — JS runtime error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        if any(term in low for term in (
            "remote components challenge solver script",
            "challenge solver script",
            "npm package (deno) were skipped",
            "signature solving failed",
            "n challenge solving failed",
            "yt-dlp-ejs",
            "solving js challenges using deno failed",
            "js challenges using deno failed",
        )):
            return DownloadError(
                category=ErrorCategory.EJS_ERROR,
                title="JS challenge solver failure",
                user_message="YouTube JavaScript challenge solver components failed to execute or could not be loaded.",
                suggested_action="• Check internet connectivity.\n• Open Settings > Runtime Manager to check for yt-dlp / EJS component updates.",
                technical_details=sanitized_raw,
                component="EJS",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — EJS error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 4. Proof of Origin (PO) Token / Visitor Data (Evidence-based)
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "po token",
            "po-token",
            "potoken",
            "visitor data",
            "visitor_data",
            "proof of origin",
        )):
            return DownloadError(
                category=ErrorCategory.PO_TOKEN_ERROR,
                title="YouTube PO Token required",
                user_message="YouTube requires a Proof of Origin (PO) token or Visitor Data to stream this video.",
                suggested_action="• Go to Settings > YouTube Authentication and configure your browser session.\n• Or try logging into YouTube in your default browser.",
                technical_details=sanitized_raw,
                component="yt-dlp",
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — PO Token error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 5. Bot Verification & Captcha Challenge
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "confirm you're not a bot",
            "confirm you’re not a bot",
            "sign in to confirm you're not a bot",
            "sign in to confirm you’re not a bot",
            "bot verification",
            "captcha",
        )):
            return DownloadError(
                category=ErrorCategory.BOT_VERIFICATION,
                title="Bot verification required",
                user_message=(
                    "Douyin requires bot verification or browser confirmation for this connection."
                    if is_douyin else
                    ("TikTok requires bot verification or browser confirmation for this connection." if is_tiktok else "YouTube requires bot verification or browser confirmation for this connection.")
                ),
                suggested_action=(
                    "• Open Douyin in your web browser and solve any CAPTCHA or prompt.\n• Wait a few minutes before trying again.\n• Avoid starting high-frequency bulk requests."
                    if is_douyin else
                    ("• Open TikTok in your web browser and solve any CAPTCHA or prompt.\n• Wait a few minutes before trying again.\n• Avoid starting high-frequency bulk requests."
                    if is_tiktok else
                    "• Open YouTube in your web browser and solve any CAPTCHA or prompt.\n• Go to Settings > YouTube Authentication and select your browser cookies.\n• Avoid starting high-frequency bulk requests.")
                ),
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"),
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Bot verification",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 6. Age Restriction
        # ---------------------------------------------------------------------
        if any(term in low for term in ("age-restricted", "confirm your age", "inappropriate for some users")):
            return DownloadError(
                category=ErrorCategory.AGE_RESTRICTED,
                title="Age-restricted video",
                user_message="This video is age-restricted and requires an authenticated adult account.",
                suggested_action=(
                    "• Verify you can watch this video in your browser with an active login."
                    if (is_tiktok or is_douyin) else
                    "• Go to Settings > YouTube Authentication and select your browser with an active YouTube login.\n• Verify you can watch this video in your browser."
                ),
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"),
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Age restricted",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 7. Login Required / Members-Only
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "sign in to view this video",
            "this video requires payment",
            "members-only",
            "this video is only available to channel members",
            "login required",
            "account is terminated",
            "you do not have permission to view",
            "log in to view",
            "log into an account that has access",
        )):
            return DownloadError(
                category=ErrorCategory.LOGIN_REQUIRED,
                title="Sign-in required",
                user_message=(
                    "This Douyin video requires an active login or permission to view."
                    if is_douyin else
                    ("This TikTok video requires an active login or permission to view." if is_tiktok else "This video requires an active login or paid membership.")
                ),
                suggested_action=(
                    "• Verify whether this video requires logging into Douyin in your web browser.\n• Check if the video is set to friends-only or private."
                    if is_douyin else
                    ("• Verify whether this video requires logging into TikTok in your web browser.\n• Check if the video or creator profile is set to friends-only or private."
                    if is_tiktok else
                    "• Configure browser authentication in Settings > YouTube Authentication.\n• Verify whether this video is members-only or requires subscription.")
                ),
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"),
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Login required",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 8. Video Unavailable vs Private Video
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "private video",
            "this video is private",
            "private post",
            "this post is private",
            "post is private",
            "private account",
            "this account is private",
            "account is private",
        )):
            return DownloadError(
                category=ErrorCategory.PRIVATE_VIDEO,
                title="Private video",
                user_message=(
                    "This Douyin video is marked private by the creator and cannot be accessed."
                    if is_douyin else
                    ("This TikTok video is marked private by the creator and cannot be accessed." if is_tiktok else "This video is marked private by the channel owner and cannot be accessed.")
                ),
                suggested_action="• Check whether the video has been made public or moved to an unlisted/private state.",
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"),
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Private video",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        if any(term in low for term in (
            "video unavailable",
            "this video is unavailable",
            "this video has been removed",
            "video does not exist",
            "video has been deleted",
            "premiere will begin",
            "live stream recording is not available",
        )):
            return DownloadError(
                category=ErrorCategory.VIDEO_UNAVAILABLE,
                title="Video unavailable",
                user_message=(
                    "This video is unavailable or has been removed from Douyin."
                    if is_douyin else
                    ("This video is unavailable or has been removed from TikTok." if is_tiktok else "This video is unavailable or has been removed from YouTube.")
                ),
                suggested_action="• Verify that the video still exists and can be watched in your browser.",
                technical_details=sanitized_raw,
                component="Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"),
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Video unavailable",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 9. Region / Geo Restriction
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "not available in your country",
            "region restricted",
            "geo restricted",
            "geoblocked",
            "blocked in your country",
            "uploader has not made this video available in your country",
            "your ip address is blocked",
            "ip address is blocked",
            "blocked from accessing this post",
        )):
            return DownloadError(
                category=ErrorCategory.REGION_RESTRICTED,
                title="Region restricted",
                user_message="The video uploader has restricted availability in your geographic region.",
                suggested_action="• Check whether the video is restricted in your country.\n• If using a VPN or proxy, switch to a supported geographic location.",
                technical_details=sanitized_raw,
                component="yt-dlp",
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Region restricted",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 9.5 Unsupported URL
        # ---------------------------------------------------------------------
        if any(term in low for term in ("unsupported url", "unsupportederror")):
            plat_name = "Douyin" if is_douyin else ("TikTok" if is_tiktok else "YouTube")
            return DownloadError(
                category=ErrorCategory.UNKNOWN_ERROR,
                title="Unsupported URL",
                user_message=f"The provided URL is not supported by the {plat_name} extractor.",
                suggested_action=f"• Check the {plat_name} URL format.\n• Provide an individual video link or supported profile link.",
                technical_details=sanitized_raw,
                component=f"{plat_name} / yt-dlp" if (is_tiktok or is_douyin) else "yt-dlp",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — Unsupported URL",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 10. Format Not Available
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "requested format not available",
            "format is not available",
            "no video formats found",
            "unsupported video format",
        )):
            return DownloadError(
                category=ErrorCategory.FORMAT_ERROR,
                title="Format not available",
                user_message="The selected resolution or container format is not offered by YouTube for this video.",
                suggested_action="• Switch video resolution to 'Best Available' in Download Options.\n• Or try selecting MP4 container instead of MOV/WEBM.",
                technical_details=sanitized_raw,
                component="yt-dlp",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — Format error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 11. FFmpeg Post-Processing / Muxing Errors
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "ffmpeg",
            "ffprobe",
            "muxing failed",
            "audio conversion failed",
            "conversion failed",
            "postprocessing error",
            "postprocessing:",
        )):
            return DownloadError(
                category=ErrorCategory.FFMPEG_ERROR,
                title=f"{stage_title} (FFmpeg)",
                user_message="FFmpeg encountered an error while merging, converting, or processing media files.",
                suggested_action="• Verify that FFmpeg is properly installed and accessible in Settings > Runtime Manager.\n• Verify that the destination drive is writable and has free space.",
                technical_details=sanitized_raw,
                component="FFmpeg",
                stage=st,
                http_status=None,
                retryable=False,
                concise_status="Failed — FFmpeg error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # ---------------------------------------------------------------------
        # 12. HTTP Status Code Errors
        # ---------------------------------------------------------------------
        # HTTP 416: Requested Range Not Satisfiable / Invalid Resume
        if http_code == 416 or any(term in low for term in (
            "http error 416",
            "416 requested range not satisfiable",
            "requested range not satisfiable",
            "range not satisfiable",
            "unable to download video data: http error 416",
        )):
            return DownloadError(
                category=ErrorCategory.RANGE_NOT_SATISFIABLE,
                title="Requested range not satisfiable",
                user_message=(
                    "The partial download could not be resumed because the requested byte range was not accepted by the server. "
                    "Channel Harvest automatically reset the incomplete partial download and attempted a fresh download. "
                    "If the fresh download also fails, try downloading this video again later."
                ),
                suggested_action=(
                    "• Channel Harvest automatically resets corrupted resume states.\n"
                    "• If the failure persists, the YouTube stream URL may have expired; try restarting the download later."
                ),
                technical_details=sanitized_raw,
                component="yt-dlp / HTTP Download",
                stage=stage if stage else "Video Download / Resume",
                http_status=416,
                retryable=False,
                concise_status="Failed — Range error (416)",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
            )

        # HTTP 429: Too Many Requests / Rate Limited
        if http_code == 429 or "429" in sanitized_raw or "too many requests" in low:
            plat_name = "Douyin" if is_douyin else ("TikTok" if is_tiktok else "YouTube")
            return DownloadError(
                category=ErrorCategory.RATE_LIMITED,
                title=f"{plat_name} request rate limited",
                user_message=f"{plat_name} is temporarily limiting requests from this connection (HTTP 429).",
                suggested_action="• Wait a few minutes before starting new downloads.\n• Channel Harvest will automatically back off and retry.",
                technical_details=sanitized_raw,
                component=f"{plat_name} / yt-dlp" if (is_tiktok or is_douyin) else "yt-dlp",
                stage=st,
                http_status=429,
                retryable=True,
                concise_status="Failed — Rate limited (429)",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # HTTP 403: Forbidden
        if http_code == 403 or "403" in sanitized_raw or "forbidden" in low:
            if is_douyin:
                return DownloadError(
                    category=ErrorCategory.HTTP_403,
                    title=f"{stage_title} (HTTP 403)",
                    user_message="Douyin rejected the request (HTTP 403 Forbidden).",
                    suggested_action=(
                        "• Douyin has restricted access for this request or IP address.\n"
                        "• Wait a few minutes before trying again to allow temporary restrictions to lift.\n"
                        "• Avoid downloading too many Douyin videos simultaneously.\n"
                        "• If persistent, verify that the video is publicly accessible in a web browser."
                    ),
                    technical_details=sanitized_raw,
                    component="Douyin / yt-dlp",
                    stage=st,
                    http_status=403,
                    retryable=True,
                    concise_status="Failed — Douyin 403",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                    platform="douyin",
                )
            elif is_tiktok:
                return DownloadError(
                    category=ErrorCategory.HTTP_403,
                    title=f"{stage_title} (HTTP 403)",
                    user_message="TikTok rejected the request (HTTP 403 Forbidden).",
                    suggested_action=(
                        "• TikTok has restricted access for this request or IP address.\n"
                        "• Wait a few minutes before trying again to allow temporary restrictions to lift.\n"
                        "• Avoid downloading too many TikTok videos simultaneously.\n"
                        "• If persistent, verify that the video is publicly accessible in a web browser."
                    ),
                    technical_details=sanitized_raw,
                    component="TikTok / yt-dlp",
                    stage=st,
                    http_status=403,
                    retryable=True,
                    concise_status="Failed — TikTok 403",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                    platform="tiktok",
                )
            else:
                return DownloadError(
                    category=ErrorCategory.HTTP_403,
                    title=f"{stage_title} (HTTP 403)",
                    user_message="YouTube temporarily rejected the media stream request (HTTP 403 Forbidden).",
                    suggested_action="• Try again later or avoid downloading many videos simultaneously.\n• If persistent, configure your browser session in Settings > YouTube Authentication.",
                    technical_details=sanitized_raw,
                    component="yt-dlp",
                    stage=st,
                    http_status=403,
                    retryable=False,
                    concise_status="Failed — HTTP 403",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                    platform="youtube",
                )

        # HTTP 404: Not Found
        if http_code == 404 or "404" in sanitized_raw or "not found" in low:
            plat_name = "Douyin" if is_douyin else ("TikTok" if is_tiktok else "YouTube")
            return DownloadError(
                category=ErrorCategory.HTTP_404,
                title=f"{stage_title} (HTTP 404)",
                user_message=(
                    f"The media stream or resource was not found on {plat_name} (HTTP 404)."
                    if (is_tiktok or is_douyin) else
                    "The media stream or resource was not found on the remote server (HTTP 404)."
                ),
                suggested_action=(
                    f"• Verify that the video still exists on {plat_name}.\n• If this video was recently deleted or made private, verify in your browser."
                    if (is_tiktok or is_douyin) else
                    "• Verify that the video still exists on YouTube.\n• If this video was recently uploaded or deleted, refresh the channel list."
                ),
                technical_details=sanitized_raw,
                component=f"{plat_name} / yt-dlp" if (is_tiktok or is_douyin) else "yt-dlp",
                stage=st,
                http_status=404,
                retryable=False,
                concise_status="Failed — HTTP 404",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # HTTP 500 / 502 / 503 Server Errors
        if http_code in (500, 502, 503) or any(term in low for term in ("500 internal", "502 bad gateway", "503 service unavailable")):
            code_val = http_code or (500 if "500" in sanitized_raw else 502 if "502" in sanitized_raw else 503)
            cat_val = ErrorCategory.HTTP_500 if code_val == 500 else ErrorCategory.HTTP_502 if code_val == 502 else ErrorCategory.HTTP_503
            plat_name = "Douyin" if is_douyin else ("TikTok" if is_tiktok else "YouTube")
            return DownloadError(
                category=cat_val,
                title=f"{plat_name} server error (HTTP {code_val})",
                user_message=f"{plat_name} servers encountered a temporary internal error (HTTP {code_val}).",
                suggested_action=f"• {plat_name} servers are currently experiencing temporary issues.\n• Channel Harvest will retry automatically, or you can try again later.",
                technical_details=sanitized_raw,
                component=f"{plat_name} / yt-dlp" if (is_tiktok or is_douyin) else "yt-dlp",
                stage=st,
                http_status=code_val,
                retryable=True,
                concise_status=f"Failed — HTTP {code_val}",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 13. Network Timeouts & Connection Failures
        # ---------------------------------------------------------------------
        if any(term in low for term in ("timed out", "timeout", "time out", "read timed out", "connection timed out")):
            plat_name = "Douyin" if is_douyin else ("TikTok" if is_tiktok else "YouTube")
            return DownloadError(
                category=ErrorCategory.TIMEOUT,
                title="Connection timed out",
                user_message=f"Network request timed out while contacting {plat_name} servers.",
                suggested_action="• Check your internet connection speed and stability.\n• Channel Harvest will retry automatically with backoff.",
                technical_details=sanitized_raw,
                component="Network",
                stage=st,
                http_status=None,
                retryable=True,
                concise_status="Failed — Timeout",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        if any(term in low for term in (
            "connection reset",
            "connection refused",
            "connection error",
            "nodename nor servname provided",
            "getaddrinfo failed",
            "socket",
            "network is unreachable",
            "gaierror",
            "urlopen error",
            "remote end closed connection",
            "ssl: certificate_verify_failed",
        )):
            plat_name = "Douyin" if is_douyin else ("TikTok" if is_tiktok else "YouTube")
            return DownloadError(
                category=ErrorCategory.NETWORK_ERROR,
                title="Network connection error",
                user_message=f"Unable to establish a reliable connection to {plat_name} servers.",
                suggested_action="• Check your network or Wi-Fi connection.\n• Check proxy, firewall, or VPN settings if enabled.",
                technical_details=sanitized_raw,
                component="Network",
                stage=st,
                http_status=None,
                retryable=True,
                concise_status="Failed — Network error",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 14. Fallback: Unknown Error (Honest reporting without overclaiming)
        # ---------------------------------------------------------------------
        return DownloadError(
            category=ErrorCategory.UNKNOWN_ERROR,
            title=stage_title,
            user_message="Channel Harvest could not determine the exact cause of this download failure.",
            suggested_action="• Check the technical details below or copy the error report for troubleshooting.\n• Try downloading the video again or verify it in your browser.",
            technical_details=sanitized_raw or "An unclassified exception occurred.",
            component=component or "yt-dlp",
            stage=st,
            http_status=http_code,
            retryable=False,
            concise_status="Failed — Unknown error",
            raw_error=sanitized_raw,
            video_id=video_id,
            video_title=video_title,
            platform=plat,
        )

    @classmethod
    def for_unavailable_platform(
        cls,
        platform_id: str,
        reason: str = "",
        video_id: str = "",
        video_title: str = "",
        stage: str = "scan",
    ) -> DownloadError:
        """
        Creates a structured DownloadError for a temporarily frozen/unavailable platform.
        Ensures clear, honest communication without instructing users to perform futile actions
        like re-exporting cookie files when the platform is temporarily blocked at the architecture level.
        """
        is_douyin = (platform_id.lower() == "douyin")
        display_name = "Douyin" if is_douyin else platform_id.capitalize()

        if is_douyin:
            title = "Douyin temporarily unavailable"
            user_message = (
                "Douyin is temporarily unavailable — waiting for an upstream yt-dlp fix. "
                "Server-side ArgusSecurityPlugin HTTP 403 blocking currently prevents metadata extraction."
            )
            suggested_action = (
                "• Douyin support is temporarily frozen while awaiting an upstream yt-dlp extractor fix.\n"
                "• Please use YouTube or TikTok for media downloads."
            )
        else:
            title = f"{display_name} temporarily unavailable"
            user_message = f"{display_name} is temporarily unavailable."
            suggested_action = "• Please select an active and available platform."

        return DownloadError(
            category=ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE,
            title=title,
            user_message=user_message,
            suggested_action=suggested_action,
            technical_details=reason or f"Platform '{platform_id}' is temporarily frozen.",
            component="platform_adapter",
            stage=stage,
            platform=platform_id.lower(),
            retryable=False,
            concise_status="Temporarily Unavailable",
            raw_error=reason or f"Platform {platform_id} is temporarily unavailable",
            video_id=video_id,
            video_title=video_title,
        )
