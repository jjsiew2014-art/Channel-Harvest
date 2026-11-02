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
    BILIBILI_API_BLOCKED = "BILIBILI_API_BLOCKED"
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
    def is_bilibili(self) -> bool:
        return self.platform == "bilibili"

    @property
    def is_douyin(self) -> bool:
        return self.platform == "douyin"

    @property
    def is_tiktok(self) -> bool:
        return self.platform == "tiktok"

    @property
    def is_facebook(self) -> bool:
        return self.platform == "facebook"

    @property
    def is_instagram(self) -> bool:
        return self.platform == "instagram"

    @property
    def is_x(self) -> bool:
        return self.platform in ("x", "twitter")

    @property
    def message(self) -> str:
        """Alias for user_message for backwards compatibility and clarity."""
        return self.user_message

    def get_localized_title(self, lang: Optional[str] = None) -> str:
        """Returns localized title based on current application language."""
        from core.i18n import I18nManager
        if lang is None:
            lang = I18nManager.get_language()
        if lang == I18nManager.LANG_ZH_TW or (lang is None and I18nManager.is_traditional_chinese()):
            t = self.title or ""
            tw_translations = {
                "Channel scanning failed (Error 352)": "頻道掃描失敗 (錯誤 352 風控攔截)",
                "Channel scanning failed (HTTP 412)": "頻道掃描失敗 (HTTP 412 反爬限制)",
                "Video download failed (Error 352)": "影片下載失敗 (錯誤 352 風控攔截)",
                "Video download failed (HTTP 412)": "影片下載失敗 (HTTP 412 反爬限制)",
                "Bilibili risk-control rejection": "嗶哩嗶哩風控攔截 (錯誤 352)",
                "Audio extraction failed": "音訊提取失敗",
                "Video download failed": "影片下載失敗",
                "Audio/Video conversion failed": "音訊與視訊合併轉檔失敗",
                "Subtitle download failed": "字幕下載失敗",
                "Thumbnail download failed": "縮圖下載失敗",
                "Channel scanning failed": "頻道掃描失敗",
                "Download cancelled": "下載已取消",
                "Disk space full": "磁碟儲存空間不足",
                "Temporary file permission denied": "暫存檔案建立權限遭拒",
                "Permission denied": "寫入權限遭拒",
                "File system error": "檔案系統錯誤",
                "File finalization locked": "檔案重新命名遭鎖定 (WinError 32)",
                "JavaScript runtime missing": "缺少 JavaScript 執行階段 (Deno)",
                "JS challenge solver failure": "JS 挑戰求解元件失敗",
                "YouTube PO Token required": "需要 YouTube PO Token 驗證",
                "Bot verification required": "需要進行人機身分驗證",
                "Age-restricted video": "年齡限制影片",
                "Sign-in required": "需要登入 YouTube 帳號",
                "Private video": "私人影片無法存取",
                "Video unavailable": "影片無法播放",
                "Region restricted": "地區限制影片",
                "Format not available": "所選格式無法使用",
                "Unsupported Container / Codec Combination (FFmpeg)": "不支援的封裝容器與編碼組合 (FFmpeg)",
                "Corrupted / Incomplete Media Stream (FFmpeg)": "媒體串流損毀或不完整 (FFmpeg)",
                "FFmpeg processing error": "FFmpeg 處理失敗",
                "YouTube request rate limited": "請求受到頻率限制 (429)",
                "Requested range not satisfiable": "請求範圍無效 (HTTP 416)",
                "Connection timed out": "網路連線逾時",
                "Network connection error": "網路連線錯誤",
                "Cookie file invalid": "Cookie 檔案無效",
                "Cookie authentication not applied": "Cookie 身分驗證未套用",
                "Douyin session cookies required": "需要有效的抖音工作階段 Cookies",
                "Douyin session required": "需要有效的抖音工作階段 Cookies",
                "Douyin API security block (ArgusSecurityPlugin)": "抖音 API 安全攔截 (ArgusSecurityPlugin)",
                "Douyin API security block": "抖音 API 安全攔截 (ArgusSecurityPlugin)",
                "Douyin API blocked by security plugin": "抖音 API 安全攔截 (ArgusSecurityPlugin)",
                "Douyin extractor incompatible": "抖音解析元件相容性異常",
                "Douyin extraction failed": "抖音影片解析失敗",
                "Douyin temporarily unavailable": "抖音暫時無法使用",
                "Platform temporarily unavailable": "平台暫時無法使用",
                "Temporarily unavailable": "暫時無法使用",
                "Unknown extraction error": "解析影片資訊失敗",
            }
            for en_prefix, zh_prefix in tw_translations.items():
                if t.startswith(en_prefix):
                    return t.replace(en_prefix, zh_prefix, 1)
            return t

        is_zh = (lang.startswith("zh") if lang else I18nManager.is_chinese())
        if not is_zh:
            return self.title
        t = self.title or ""
        translations = {
            "Channel scanning failed (Error 352)": "频道扫描失败 (错误 352 风控拦截)",
            "Channel scanning failed (HTTP 412)": "频道扫描失败 (HTTP 412 反爬限制)",
            "Video download failed (Error 352)": "视频下载失败 (错误 352 风控拦截)",
            "Video download failed (HTTP 412)": "视频下载失败 (HTTP 412 反爬限制)",
            "Bilibili risk-control rejection": "哔哩哔哩风控拦截 (错误 352)",
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
            "Unsupported Container / Codec Combination (FFmpeg)": "不支持的封装容器与编码组合 (FFmpeg)",
            "Corrupted / Incomplete Media Stream (FFmpeg)": "媒体流损坏或不完整 (FFmpeg)",
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
        if lang is None:
            lang = I18nManager.get_language()
        if lang == I18nManager.LANG_ZH_TW or (lang is None and I18nManager.is_traditional_chinese()):
            if self.title == "Temporary file permission denied" or "temporary directory is not writable" in self.user_message.lower():
                return "Channel Harvest 無法建立暫存下載檔案，因為所設定的暫存目錄不可寫入。"

            if self.category == ErrorCategory.IMPERSONATION_ERROR:
                return "TikTok 需要瀏覽器模擬 (impersonation) 支援，但目前執行環境未提供相容的模擬目標。"

            if self.platform == "tiktok":
                tiktok_tw_messages = {
                    ErrorCategory.CANCELLED: "下載已由使用者主動取消。",
                    ErrorCategory.HTTP_403: "TikTok 拒絕了請求 (HTTP 403 禁止存取)。",
                    ErrorCategory.RATE_LIMITED: "TikTok 暫時對目前網路連線施加了請求頻率限制 (HTTP 429)。",
                    ErrorCategory.BOT_VERIFICATION: "TikTok 偵測到異常請求，要求進行人機身分安全驗證。",
                    ErrorCategory.LOGIN_REQUIRED: "該影片需要登入 TikTok 帳號，或是私密/僅好友可見內容。",
                    ErrorCategory.PRIVATE_VIDEO: "該 TikTok 影片已被創作者設為私密，無法公開存取。",
                    ErrorCategory.VIDEO_UNAVAILABLE: "該 TikTok 影片無法播放，或已被創作者/平台刪除。",
                    ErrorCategory.REGION_RESTRICTED: "影片上傳者限制了該 TikTok 內容在您所在國家或地區的播放權限。",
                    ErrorCategory.FORMAT_ERROR: "TikTok 未提供所選擇的格式或解析度。",
                    ErrorCategory.FFMPEG_ERROR: "FFmpeg 在進行音訊與視訊合併、轉檔或後期封裝處理時發生異常。",
                    ErrorCategory.TIMEOUT: "連線 TikTok 伺服器逾時，網路未能在規定時間內回應。",
                    ErrorCategory.NETWORK_ERROR: "無法與 TikTok 伺服器建立穩定的網路連線。",
                    ErrorCategory.DISK_SPACE_ERROR: "目標磁碟剩餘空間不足，無法儲存下載內容。",
                    ErrorCategory.PERMISSION_ERROR: "Channel Harvest 沒有向目標資料夾寫入檔案的權限。",
                    ErrorCategory.FILE_SYSTEM_ERROR: "檔案儲存路徑或影片標題中包含系統不支援的特殊字元，或超出了 Windows 的路徑長度限制。",
                    ErrorCategory.FILE_LOCKED: "由於受到 Windows 其他處理程序的暫時佔用，下載檔案無法完成最終重新命名。",
                    ErrorCategory.UNKNOWN_ERROR: "未能明確識別本次下載失敗的具體成因。",
                }
                if self.category in tiktok_tw_messages:
                    return tiktok_tw_messages[self.category]

            if self.platform == "bilibili":
                bilibili_tw_messages = {
                    ErrorCategory.CANCELLED: "下載已由使用者主動取消。",
                    ErrorCategory.HTTP_403: "嗶哩嗶哩拒絕了請求 (HTTP 403 禁止存取)。",
                    ErrorCategory.RATE_LIMITED: "嗶哩嗶哩伺服器暫時攔截了請求 (HTTP 412 條件未滿足 / 反爬頻率限制)。建議設定 Cookie 檔案或稍後再試。",
                    ErrorCategory.LOGIN_REQUIRED: "該影片或畫質需要登入嗶哩嗶哩帳號，或屬於大會員專享內容。",
                    ErrorCategory.PRIVATE_VIDEO: "該嗶哩嗶哩影片已被設為私密，無法存取。",
                    ErrorCategory.VIDEO_UNAVAILABLE: "該嗶哩嗶哩影片無法播放，或已被刪除/地區限制。",
                    ErrorCategory.REGION_RESTRICTED: "影片上傳者限制了該內容在您所在地區的播放權限。",
                    ErrorCategory.FORMAT_ERROR: "嗶哩嗶哩未提供所選擇的格式或解析度。",
                    ErrorCategory.FFMPEG_ERROR: "FFmpeg 在進行音訊與視訊合併、轉檔或後期封裝處理時發生異常。",
                    ErrorCategory.TIMEOUT: "連線嗶哩嗶哩伺服器逾時，請檢查網路連線。",
                    ErrorCategory.NETWORK_ERROR: "無法與嗶哩嗶哩伺服器建立穩定的網路連線。",
                    ErrorCategory.DISK_SPACE_ERROR: "目標磁碟剩餘空間不足，無法儲存下載內容。",
                    ErrorCategory.PERMISSION_ERROR: "Channel Harvest 沒有向目標資料夾寫入檔案的權限。",
                    ErrorCategory.FILE_SYSTEM_ERROR: "檔案儲存路徑或影片標題中包含系統不支援的特殊字元，或超出了 Windows 的路徑長度限制。",
                    ErrorCategory.FILE_LOCKED: "由於受到 Windows 其他處理程序的暫時佔用，下載檔案無法完成最終重新命名。",
                    ErrorCategory.COOKIE_FILE_INVALID: "所指定的嗶哩嗶哩 Cookie 檔案不存在、為空或格式無效（需為 Netscape 格式）。",
                    ErrorCategory.BILIBILI_API_BLOCKED: "嗶哩嗶哩伺服器觸發了安全風控機制並拒絕了此請求 (錯誤碼 352)。該創作者主頁或內容需要有效的登入工作階段 Cookies 方可存取。",
                    ErrorCategory.UNKNOWN_ERROR: "未能明確識別本次下載失敗的具體成因。",
                }
                if self.category in bilibili_tw_messages:
                    return bilibili_tw_messages[self.category]

            if self.platform == "douyin":
                douyin_tw_messages = {
                    ErrorCategory.CANCELLED: "下載已由使用者主動取消。",
                    ErrorCategory.HTTP_403: "抖音拒絕了請求 (HTTP 403 禁止存取)。",
                    ErrorCategory.RATE_LIMITED: "抖音暫時對目前網路連線施加了請求頻率限制 (HTTP 429)。",
                    ErrorCategory.BOT_VERIFICATION: "抖音需要有效的工作階段 Cookies（Fresh cookies）以取得影片詳情。請在「設定」中設定抖音身分驗證（瀏覽器 Cookies 或自訂 Cookie 檔案）。",
                    ErrorCategory.LOGIN_REQUIRED: "該影片需要登入抖音帳號，或是私密/僅互關好友可見內容。",
                    ErrorCategory.PRIVATE_VIDEO: "該抖音影片已被創作者設為私密，無法公開存取。",
                    ErrorCategory.VIDEO_UNAVAILABLE: "該抖音影片無法播放，或已被創作者/平台下架刪除。",
                    ErrorCategory.REGION_RESTRICTED: "影片上傳者限制了該抖音內容在您所在地區的播放權限。",
                    ErrorCategory.FORMAT_ERROR: "抖音未提供所選擇的格式或解析度。",
                    ErrorCategory.FFMPEG_ERROR: "FFmpeg 在進行音訊與視訊合併、轉檔或後期封裝處理時發生異常。",
                    ErrorCategory.TIMEOUT: "連線抖音伺服器逾時，網路未能在規定時間內回應。",
                    ErrorCategory.NETWORK_ERROR: "無法與抖音伺服器建立穩定的網路連線。",
                    ErrorCategory.DISK_SPACE_ERROR: "目標磁碟剩餘空間不足，無法儲存下載內容。",
                    ErrorCategory.PERMISSION_ERROR: "Channel Harvest 沒有向目標資料夾寫入檔案的權限。",
                    ErrorCategory.FILE_SYSTEM_ERROR: "檔案儲存路徑或影片標題中包含系統不支援的特殊字元，或超出了 Windows 的路徑長度限制。",
                    ErrorCategory.FILE_LOCKED: "由於受到 Windows 其他處理程序的暫時佔用，下載檔案無法完成最終重新命名。",
                    ErrorCategory.COOKIE_FILE_INVALID: "所指定的抖音 Cookie 檔案不存在、為空或格式無效（需為 Netscape 格式）。",
                    ErrorCategory.COOKIE_NOT_APPLIED: "未能成功將 Cookie 設定傳遞給下載引擎或未偵測到可用憑證。",
                    ErrorCategory.DOUYIN_SESSION_REQUIRED: "抖音需要有效的工作階段 Cookies（Fresh cookies）以取得影片詳情。目前未設定任何有效的抖音 Cookies。",
                    ErrorCategory.DOUYIN_API_BLOCKED: "抖音伺服器安全防護元件 (ArgusSecurityPlugin) 攔截了詳情請求（缺少有效的裝置安全識別碼 UIFID 或觸發了反爬驗證）。即使已載入 Cookie 檔案，若缺少完整的裝置安全挑戰權杖亦無法略過。",
                    ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: "yt-dlp 的抖音解析元件 (DouyinIE) 與目前抖音網頁介面不相容或未實作安全挑戰求解支援。",
                    ErrorCategory.UNKNOWN_EXTRACTION_ERROR: "未能從抖音伺服器提取到影片中繼資料或下載網址。",
                    ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: "抖音暫時無法使用 — 等待 yt-dlp 上游修復。目前抖音伺服器端的 ArgusSecurityPlugin 安全防護機制 (HTTP 403) 阻止了影片詳細資訊解析。",
                    ErrorCategory.UNKNOWN_ERROR: "未能明確識別本次下載失敗的具體成因。",
                }
                if self.category in douyin_tw_messages:
                    return douyin_tw_messages[self.category]

            cat_tw_messages = {
                ErrorCategory.CANCELLED: "下載已由使用者主動取消。",
                ErrorCategory.FILE_LOCKED: "由於受到 Windows 其他處理程序（如防毒軟體掃描、檔案索引或雲端硬碟同步）的暫時佔用，下載檔案無法完成最終重新命名。",
                ErrorCategory.DISK_SPACE_ERROR: "目標磁碟剩餘空間不足，無法儲存下載內容。",
                ErrorCategory.PERMISSION_ERROR: "Channel Harvest 沒有向目標資料夾寫入檔案的權限。",
                ErrorCategory.FILE_SYSTEM_ERROR: "檔案儲存路徑或影片標題中包含系統不支援的特殊字元，或超出了 Windows 的路徑長度限制。",
                ErrorCategory.COOKIE_FILE_INVALID: "所指定的 Cookie 檔案不存在、為空或格式無效（需為 Netscape 格式）。",
                ErrorCategory.COOKIE_NOT_APPLIED: "未能成功將 Cookie 設定傳遞給下載引擎。",
                ErrorCategory.DOUYIN_SESSION_REQUIRED: "抖音需要有效的工作階段 Cookies 以取得影片詳情。目前未設定任何有效的抖音 Cookies。",
                ErrorCategory.DOUYIN_API_BLOCKED: "抖音伺服器安全防護元件 (ArgusSecurityPlugin) 攔截了詳情請求（缺少有效的裝置安全識別碼 UIFID 或觸發了反爬驗證）。",
                ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: "yt-dlp 的抖音解析元件與目前抖音網頁介面不相容。",
                ErrorCategory.UNKNOWN_EXTRACTION_ERROR: "解析影片資訊失敗。",
                ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: "該平台目前處於暫時停用狀態 — 等待上游修復更新。",
                ErrorCategory.JS_RUNTIME_ERROR: "yt-dlp 需要 JavaScript 執行環境 (Deno) 來解析 YouTube 影片請求驗證。",
                ErrorCategory.EJS_ERROR: "YouTube JavaScript 驗證求解元件執行失敗或未能成功載入。",
                ErrorCategory.PO_TOKEN_ERROR: "YouTube 要求提供有效的 Proof of Origin (PO) Token 或訪客識別資料方可取得影片串流。",
                ErrorCategory.BOT_VERIFICATION: "YouTube 偵測到頻繁請求，要求進行人機身分驗證。",
                ErrorCategory.AGE_RESTRICTED: "該影片已被標記為年齡限制內容，需要登入已滿法定年齡的 YouTube 帳號方可觀看。",
                ErrorCategory.LOGIN_REQUIRED: "該影片需要登入 YouTube 帳號，或是頻道會員專屬內容。",
                ErrorCategory.PRIVATE_VIDEO: "該影片已被創作者設為私人（Private），無法公開存取。",
                ErrorCategory.VIDEO_UNAVAILABLE: "該影片無法播放，或已被創作者/平台下架刪除。",
                ErrorCategory.REGION_RESTRICTED: "影片上傳者限制了該內容在您所在國家或地區的播放權限。",
                ErrorCategory.FORMAT_ERROR: "YouTube 伺服器未提供所選擇的解析度或封裝格式。",
                ErrorCategory.FFMPEG_ERROR: "FFmpeg 在進行音訊與視訊合併、轉檔或後期封裝處理時發生異常。",
                ErrorCategory.RANGE_NOT_SATISFIABLE: "斷點續傳失敗：伺服器拒絕了請求的檔案位元組範圍。Channel Harvest 已自動重設損毀的暫存分塊並嘗試重新完整下載。若仍失敗，建議稍後重試。",
                ErrorCategory.RATE_LIMITED: "YouTube 暫時對目前網路連線施加了請求頻率限制 (HTTP 429)。",
                ErrorCategory.HTTP_403: "YouTube 伺服器暫時拒絕了視訊與音訊串流的擷取請求 (HTTP 403 Forbidden)。",
                ErrorCategory.HTTP_404: "在遠端伺服器上未找到請求的媒體串流或資源 (HTTP 404)。",
                ErrorCategory.HTTP_500: "YouTube 伺服器端暫時發生內部錯誤或服務無法使用 (HTTP 500)。",
                ErrorCategory.HTTP_502: "YouTube 伺服器閘道異常 (HTTP 502 Bad Gateway)。",
                ErrorCategory.HTTP_503: "YouTube 伺服器目前服務無法使用或過載 (HTTP 503)。",
                ErrorCategory.TIMEOUT: "連線 YouTube 伺服器逾時，網路未能在規定時間內回應。",
                ErrorCategory.NETWORK_ERROR: "無法與 YouTube 伺服器建立穩定的網路連線。",
                ErrorCategory.UNKNOWN_ERROR: "未能明確識別本次下載失敗的具體成因。",
            }
            return cat_tw_messages.get(self.category, self.user_message)

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

        if self.platform == "bilibili":
            bilibili_zh_messages = {
                ErrorCategory.CANCELLED: "下载已由用户主动取消。",
                ErrorCategory.HTTP_403: "哔哩哔哩拒绝了请求 (HTTP 403 禁止访问)。",
                ErrorCategory.RATE_LIMITED: "哔哩哔哩服务器暂时拦截了请求 (HTTP 412 前提条件失败 / 反爬频率限制)。建议配置 Cookie 文件或稍后再试。",
                ErrorCategory.LOGIN_REQUIRED: "该视频或画质需要登录哔哩哔哩账号，或属于大会员专享内容。",
                ErrorCategory.PRIVATE_VIDEO: "该哔哩哔哩视频已被设为私密，无法访问。",
                ErrorCategory.VIDEO_UNAVAILABLE: "该哔哩哔哩视频不可用，或已被删除/地区限制。",
                ErrorCategory.REGION_RESTRICTED: "视频上传者限制了该内容在您所在地区的播放权限。",
                ErrorCategory.FORMAT_ERROR: "哔哩哔哩未提供所选择的格式或分辨率。",
                ErrorCategory.FFMPEG_ERROR: "FFmpeg 在进行音视频合并、转码或后期封装处理时发生异常。",
                ErrorCategory.TIMEOUT: "连接哔哩哔哩服务器超时，请检查网络连接。",
                ErrorCategory.NETWORK_ERROR: "无法与哔哩哔哩服务器建立稳定的网络连接。",
                ErrorCategory.DISK_SPACE_ERROR: "目标磁盘剩余空间不足，无法保存下载内容。",
                ErrorCategory.PERMISSION_ERROR: "Channel Harvest 没有向目标文件夹写入文件的权限。",
                ErrorCategory.FILE_SYSTEM_ERROR: "文件保存路径或视频标题中包含系统不支持的特殊字符，或超出了 Windows 的最长路径限制。",
                ErrorCategory.FILE_LOCKED: "由于受到 Windows 其他进程的临时占用，下载文件无法完成最终重命名。",
                ErrorCategory.COOKIE_FILE_INVALID: "所指定的哔哩哔哩 Cookie 文件不存在、为空或格式无效（需为 Netscape 格式）。",
                ErrorCategory.BILIBILI_API_BLOCKED: "哔哩哔哩服务器触发了安全风控机制并拒绝了此请求 (错误码 352)。该创作者主页或内容需要有效的登录会话 Cookie 方可访问。",
                ErrorCategory.UNKNOWN_ERROR: "未能明确识别本次下载失败的具体成因。",
            }
            if self.category in bilibili_zh_messages:
                return bilibili_zh_messages[self.category]

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
        if lang is None:
            lang = I18nManager.get_language()
        if lang == I18nManager.LANG_ZH_TW or (lang is None and I18nManager.is_traditional_chinese()):
            if self.title == "Temporary file permission denied" or "temporary directory is not writable" in self.user_message.lower():
                return (
                    "• 檢查 Windows 使用者暫存目錄 (%TEMP%) 的讀寫權限。\n"
                    "• 重啟 Channel Harvest 以重設暫存工作區。\n"
                    "• 避免在受限的系統目錄中執行本軟體。"
                )

            if self.category == ErrorCategory.IMPERSONATION_ERROR:
                return (
                    "• 確保應用程式執行環境中已安裝 curl_cffi 核心元件。\n"
                    "• 請前往「設定」>「下載元件」檢查瀏覽器模擬支援狀態。\n"
                    "• 重啟 Channel Harvest 以重新載入執行元件。"
                )

            if self.platform == "tiktok":
                tiktok_tw_actions = {
                    ErrorCategory.CANCELLED: "您可以隨時繼續或重新啟動下載佇列。",
                    ErrorCategory.HTTP_403: (
                        "• TikTok 伺服器暫時拒絕了該請求或對目前 IP 施加了存取限制。\n"
                        "• 請稍候片刻重試，等待伺服器暫時限制解除。\n"
                        "• 避免短時間內連續並行下載大量 TikTok 影片。\n"
                        "• 若問題持續，請在瀏覽器中開啟連結確認影片是否能正常公開播放。"
                    ),
                    ErrorCategory.RATE_LIMITED: (
                        "• 請稍等數分鐘後再繼續下載。\n"
                        "• Channel Harvest 會自動依策略退避並進行重試。"
                    ),
                    ErrorCategory.BOT_VERIFICATION: (
                        "• 請在常用瀏覽器中開啟 TikTok 並完成安全驗證提示。\n"
                        "• 請稍候數分鐘後再嘗試下載。\n"
                        "• 避免短時間內發起極高頻率的批次下載請求。"
                    ),
                    ErrorCategory.LOGIN_REQUIRED: (
                        "• 請確認該影片是否需要登入 TikTok 帳號方可觀看。\n"
                        "• 檢查該影片或創作者主頁是否已設為僅好友可見或存取受限。"
                    ),
                    ErrorCategory.PRIVATE_VIDEO: (
                        "• 請確認創作者是否已將該影片設為私密狀態。"
                    ),
                    ErrorCategory.VIDEO_UNAVAILABLE: (
                        "• 請在瀏覽器中開啟連結，確認該影片是否仍然存在且能正常存取。"
                    ),
                    ErrorCategory.REGION_RESTRICTED: (
                        "• 該內容在您目前的地理區域無法使用。\n"
                        "• 若正在使用代理伺服器或 VPN，可嘗試切換至內容支援的地區節點。"
                    ),
                    ErrorCategory.TIMEOUT: (
                        "• 請檢查目前網路連線的順暢度與連線速度。\n"
                        "• Channel Harvest 會自動安排延遲重試。"
                    ),
                    ErrorCategory.NETWORK_ERROR: (
                        "• 請檢查本機網路或 Wi-Fi 連線是否正常。\n"
                        "• 若開啟了系統代理伺服器、防火牆或 VPN，請檢查其設定是否正常。"
                    ),
                }
                if self.category in tiktok_tw_actions:
                    return tiktok_tw_actions[self.category]

            if self.platform == "bilibili":
                bilibili_tw_actions = {
                    ErrorCategory.CANCELLED: "您可以隨時繼續或重新啟動下載佇列。",
                    ErrorCategory.BILIBILI_API_BLOCKED: (
                        "• 嗶哩嗶哩安全風控系統攔截了未經驗證的存取請求 (錯誤 352)。\n"
                        "• 請前往「設定」>「身分驗證」>「嗶哩嗶哩」，選擇並套用包含有效登入工作階段的 Cookie 檔案 (cookies.txt)。\n"
                        "• 若已設定 Cookie 檔案，請確認 Cookie 是否過期，可在瀏覽器重新登入 bilibili.com 並匯出最新 Cookies。\n"
                        "• 避免極高頻率的連續掃描以防止觸發臨時 IP 風控防禦。"
                    ),
                    ErrorCategory.RATE_LIMITED: (
                        "• 嗶哩嗶哩伺服器暫時攔截了請求 (HTTP 412 前提條件失敗 / 反爬頻率限制)。\n"
                        "• 請在「設定」>「身分驗證」中設定有效的嗶哩嗶哩 Cookie 檔案。\n"
                        "• 或請稍候數分鐘再重試，等待伺服器頻率限制解除。"
                    ),
                    ErrorCategory.HTTP_403: (
                        "• 嗶哩嗶哩伺服器拒絕了該請求或對目前 IP 施加了存取限制 (HTTP 403)。\n"
                        "• 請稍候片刻重試，等待伺服器限制解除。\n"
                        "• 若該內容需要登入或大會員權限，請在「設定」中設定 Cookie 檔案。"
                    ),
                    ErrorCategory.LOGIN_REQUIRED: (
                        "• 該影片或高畫質串流需要登入嗶哩嗶哩帳號（或大會員）。\n"
                        "• 請前往「設定」>「身分驗證」>「嗶哩嗶哩」匯入已登入帳號的 Cookie 檔案。"
                    ),
                    ErrorCategory.COOKIE_FILE_INVALID: (
                        "• 請確認在「設定」>「身分驗證」中選擇的嗶哩嗶哩 Cookie 檔案路徑正確且檔案存在。\n"
                        "• 確保匯出的 Cookie 檔案為標準 Netscape HTTP Cookie 格式且包含 SESSDATA。\n"
                        "• 避免使用空白或損毀的文字檔案。"
                    ),
                    ErrorCategory.VIDEO_UNAVAILABLE: (
                        "• 請在瀏覽器中開啟連結，確認該嗶哩嗶哩影片是否仍然存在且能公開觀看。"
                    ),
                    ErrorCategory.REGION_RESTRICTED: (
                        "• 該內容僅限特定地區播放（如僅限港澳台或中國大陸）。\n"
                        "• 若正在使用代理伺服器或 VPN，可嘗試切換至支援該內容的地區節點。"
                    ),
                    ErrorCategory.TIMEOUT: (
                        "• 請檢查目前網路連線狀態。\n"
                        "• Channel Harvest 會自動安排延遲重試。"
                    ),
                    ErrorCategory.NETWORK_ERROR: (
                        "• 請檢查本機網路或 Wi-Fi 連線是否正常。\n"
                        "• 若開啟了系統代理伺服器、防火牆或 VPN，請檢查其設定是否正常。"
                    ),
                }
                if self.category in bilibili_tw_actions:
                    return bilibili_tw_actions[self.category]

            if self.platform == "douyin":
                douyin_tw_actions = {
                    ErrorCategory.CANCELLED: "您可以隨時繼續或重新啟動下載佇列。",
                    ErrorCategory.HTTP_403: (
                        "• 抖音伺服器暫時拒絕了該請求或對目前 IP 施加了存取限制。\n"
                        "• 請稍候片刻重試，等待伺服器暫時限制解除。\n"
                        "• 避免短時間內連續並行下載大量抖音影片。\n"
                        "• 若問題持續，請在瀏覽器中開啟連結確認影片是否能正常公開播放。"
                    ),
                    ErrorCategory.RATE_LIMITED: (
                        "• 請稍等數分鐘後再繼續下載。\n"
                        "• Channel Harvest 會自動依策略退避並進行重試。"
                    ),
                    ErrorCategory.BOT_VERIFICATION: (
                        "• 請前往「設定」>「身分驗證」，選擇「抖音」。\n"
                        "• 選擇「瀏覽器 Cookies」（Chrome/Edge/Firefox）或匯入有效的 Cookie 檔案 (cookies.txt)。\n"
                        "• 若 Cookie 已過期，請在瀏覽器中開啟 douyin.com 重新整理登入狀態。"
                    ),
                    ErrorCategory.LOGIN_REQUIRED: (
                        "• 請確認該影片是否需要登入抖音帳號方可觀看。\n"
                        "• 檢查該影片是否已設為私密或僅互關好友可見。"
                    ),
                    ErrorCategory.PRIVATE_VIDEO: (
                        "• 請確認創作者是否已將該抖音影片設為私密狀態。"
                    ),
                    ErrorCategory.VIDEO_UNAVAILABLE: (
                        "• 請在瀏覽器中開啟連結，確認該影片是否仍然存在且能正常存取。"
                    ),
                    ErrorCategory.REGION_RESTRICTED: (
                        "• 該內容在您目前的地理區域無法使用。\n"
                        "• 若正在使用代理伺服器或 VPN，可嘗試切換至內容支援的地區節點。"
                    ),
                    ErrorCategory.TIMEOUT: (
                        "• 請檢查目前網路連線的順暢度與連線速度。\n"
                        "• Channel Harvest 會自動安排延遲重試。"
                    ),
                    ErrorCategory.NETWORK_ERROR: (
                        "• 請檢查本機網路或 Wi-Fi 連線是否正常。\n"
                        "• 若開啟了系統代理伺服器、防火牆或 VPN，請檢查其設定是否正常。"
                    ),
                    ErrorCategory.COOKIE_FILE_INVALID: (
                        "• 請確認在「設定」>「身分驗證」中選擇的 Cookie 檔案路徑正確且檔案可讀取。\n"
                        "• 確保匯出的 Cookie 檔案為標準的 Netscape HTTP Cookie 格式。\n"
                        "• 避免使用空白或損毀的文字檔案。"
                    ),
                    ErrorCategory.COOKIE_NOT_APPLIED: (
                        "• 請在「設定」>「身分驗證」中重新選擇並儲存抖音 Cookie 設定。\n"
                        "• 重啟 Channel Harvest 以確保驗證設定生效。"
                    ),
                    ErrorCategory.DOUYIN_SESSION_REQUIRED: (
                        "• 請前往「設定」>「身分驗證」，選擇「抖音」。\n"
                        "• 選擇「瀏覽器 Cookies」（Chrome/Edge/Firefox）或匯入有效的 Cookie 檔案 (cookies.txt)。\n"
                        "• 若 Cookie 已過期，請在瀏覽器中開啟 douyin.com 重新整理登入狀態。"
                    ),
                    ErrorCategory.DOUYIN_API_BLOCKED: (
                        "• 抖音目前透過 ArgusSecurityPlugin 及裝置安全識別碼 (UIFID / x-tt-argus) 進行反爬防護。\n"
                        "• 請在瀏覽器中存取該抖音影片並完成滑動驗證/安全校驗後，重新匯出最新的完整 Cookie 檔案。\n"
                        "• 確認 Cookie 檔案中包含經過校驗的 UIFID 或 sessionid 欄位。\n"
                        "• 關注 yt-dlp 後續版本更新（yt-dlp 暫未內建針對抖音安全外掛的 challenge 求解器）。"
                    ),
                    ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: (
                        "• 請檢查軟體是否執行最新相容版本的 yt-dlp 元件。\n"
                        "• 在瀏覽器中確認該連結是否能在網頁端正常播放。\n"
                        "• 可向 yt-dlp 或 Channel Harvest 回報該影片連結以取得支援更新。"
                    ),
                    ErrorCategory.UNKNOWN_EXTRACTION_ERROR: (
                        "• 請稍後重試，或在瀏覽器中開啟影片確認播放狀態。\n"
                        "• 檢查網路連線是否正常。"
                    ),
                    ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: (
                        "• 抖音支援目前處於暫時凍結狀態，等待 yt-dlp 官方提供支援安全挑戰求解的解析器更新。\n"
                        "• 請切換至 YouTube 或 TikTok 進行媒體下載。"
                    ),
                }
                if self.category in douyin_tw_actions:
                    return douyin_tw_actions[self.category]

            cat_tw_actions = {
                ErrorCategory.CANCELLED: "您可以隨時繼續或重新啟動下載佇列。",
                ErrorCategory.BILIBILI_API_BLOCKED: "• 嗶哩嗶哩風控系統攔截了請求 (錯誤 352)。\n• 請在「設定」>「身分驗證」中設定包含有效登入狀態的 Cookie 檔案。\n• 若 Cookie 已過期，請在瀏覽器中重新登入 bilibili.com 並重新匯出。",
                ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE: "• 該平台目前處於暫時停用狀態。\n• 請切換至其他可用平台進行媒體下載。",
                ErrorCategory.COOKIE_FILE_INVALID: "• 請確認選擇的 Cookie 檔案路徑正確且為標準的 Netscape 格式。\n• 避免使用空白或損毀的文字檔案。",
                ErrorCategory.COOKIE_NOT_APPLIED: "• 請在設定中重新選擇並儲存 Cookie 設定。\n• 重啟軟體後重試。",
                ErrorCategory.DOUYIN_SESSION_REQUIRED: "• 請前往「設定」>「身分驗證」，選擇「抖音」並設定 Cookie。\n• 在瀏覽器中開啟 douyin.com 重新整理登入狀態。",
                ErrorCategory.DOUYIN_API_BLOCKED: "• 抖音安全防護元件 (ArgusSecurityPlugin) 攔截了請求。\n• 請在瀏覽器中完成安全驗證後重新匯出包含 UIFID 的 Cookie。\n• 關注 yt-dlp 解析器後續更新。",
                ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE: "• 請檢查 yt-dlp 元件版本。\n• 確認該連結在瀏覽器中能否正常播放。",
                ErrorCategory.UNKNOWN_EXTRACTION_ERROR: "• 請稍後重試，或在瀏覽器中開啟影片確認播放狀態。\n• 檢查網路連線是否正常。",
                ErrorCategory.FILE_LOCKED: "• 請稍候片刻，等待 Windows 或防毒軟體完成對檔案的掃描。\n• 可暫時將下載目標資料夾加入防毒軟體的即時掃描排除清單。\n• 若開啟了雲端硬碟同步（如 OneDrive、Google Drive 等），可暫時暫停同步。\n• 請關閉可能已開啟該暫存檔案的播放器或檔案總管。",
                ErrorCategory.DISK_SPACE_ERROR: "• 請清理目標磁碟機的儲存空間。\n• 或在軟體設定中將下載儲存路徑變更為空間充足的磁碟。",
                ErrorCategory.PERMISSION_ERROR: "• 請選擇擁有寫入權限的儲存目錄（例如系統的「下載」或「影片」資料夾）。\n• 檢查目標檔案是否被其他應用程式佔用或設為唯讀。",
                ErrorCategory.FILE_SYSTEM_ERROR: "• 請選擇路徑較短的儲存資料夾（例如 C:\\Downloads）。\n• 檢查下載目錄設定。",
                ErrorCategory.JS_RUNTIME_ERROR: "• 請開啟「設定」>「下載元件」檢查 Deno 元件狀態。\n• 確保軟體目錄下的 runtime/deno.exe 完整存在。",
                ErrorCategory.EJS_ERROR: "• 請檢查目前網路連線是否順暢。\n• 可在「設定」>「下載元件」中檢查並更新 yt-dlp 及 EJS 核心元件。",
                ErrorCategory.PO_TOKEN_ERROR: "• 請前往「設定」>「YOUTUBE 登入驗證」設定本機瀏覽器 Cookie 工作階段。\n• 或在預設瀏覽器中登入 YouTube 後重試。",
                ErrorCategory.BOT_VERIFICATION: "• 請在常用瀏覽器中開啟 YouTube 並完成人機驗證提示。\n• 前往「設定」>「YOUTUBE 登入驗證」選擇匯入瀏覽器的 Cookies。\n• 避免短時間內發起極高頻率的批次下載請求。",
                ErrorCategory.AGE_RESTRICTED: "• 請在「設定」>「YOUTUBE 登入驗證」中選擇已登入成年帳號的瀏覽器 Cookies。\n• 請確認在瀏覽器中能夠正常播放該影片。",
                ErrorCategory.LOGIN_REQUIRED: "• 請在「設定」>「YOUTUBE 登入驗證」中設定瀏覽器 Cookies。\n• 請確認該影片是否為付費會員專屬或需要額外訂閱權限。",
                ErrorCategory.PRIVATE_VIDEO: "• 請確認影片創作者是否將其設為了非公開或私人狀態。",
                ErrorCategory.VIDEO_UNAVAILABLE: "• 請在瀏覽器中開啟連結，確認該影片是否仍然存在且能正常播放。",
                ErrorCategory.REGION_RESTRICTED: "• 該影片在您目前的地理區域無法使用。\n• 若正在使用代理伺服器或 VPN，可嘗試切換至影片支援的地區節點。",
                ErrorCategory.FORMAT_ERROR: "• 在主介面的「下載選項」中，將影片解析度調整為「最高解析度」。\n• 或嘗試將影片格式由 MOV/WEBM 改選為 MP4。",
                ErrorCategory.FFMPEG_ERROR: "• 請前往「設定」>「下載元件」，確認 FFmpeg 元件已正常就緒。\n• 檢查目標儲存磁碟是否可寫入且有足夠的剩餘容量。",
                ErrorCategory.RANGE_NOT_SATISFIABLE: "• 軟體已自動清理衝突的斷點續傳快取並重試。\n• 若問題依然存在，可能是該影片串流暫存下載網址已過期，建議稍後重新下載該影片。",
                ErrorCategory.RATE_LIMITED: "• 請稍等數分鐘後再繼續下載。\n• Channel Harvest 會自動依策略退避並進行重試。",
                ErrorCategory.HTTP_403: "• 請稍後重試，或避免同時並行下載大量影片。\n• 若頻繁出現，建議在「設定」>「YOUTUBE 登入驗證」中匯入瀏覽器 Cookies。",
                ErrorCategory.HTTP_404: "• 請在瀏覽器中檢查該影片是否已被刪除或替換。\n• 重新掃描頻道或重新整理影片列表後重試。",
                ErrorCategory.HTTP_500: "• YouTube 伺服器目前可能正遭遇短暫故障。\n• 軟體會自動重試，您也可以稍後再次嘗試。",
                ErrorCategory.HTTP_502: "• YouTube 伺服器目前可能正遭遇短暫故障。\n• 軟體會自動重試，您也可以稍後再次嘗試。",
                ErrorCategory.HTTP_503: "• YouTube 伺服器目前可能正遭遇短暫故障。\n• 軟體會自動重試，您也可以稍後再次嘗試。",
                ErrorCategory.TIMEOUT: "• 請檢查目前網路連線的順暢度與連線速度。\n• Channel Harvest 會自動安排延遲重試。",
                ErrorCategory.NETWORK_ERROR: "• 請檢查本機網路或 Wi-Fi 連線是否正常。\n• 若開啟了系統代理伺服器、防火牆或 VPN，請檢查其設定與規則是否正常。",
                ErrorCategory.UNKNOWN_ERROR: "• 請查看下方的技術詳情，或複製錯誤報告以便進一步排查。\n• 建議重新嘗試下載，或在瀏覽器中開啟影片確認播放狀態。",
            }
            return cat_tw_actions.get(self.category, self.suggested_action)

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

        if self.platform == "bilibili":
            bilibili_zh_actions = {
                ErrorCategory.CANCELLED: "您可以随时恢复或重新启动下载队列。",
                ErrorCategory.BILIBILI_API_BLOCKED: (
                    "• 哔哩哔哩安全风控系统拦截了未经身份验证的访问请求 (错误 352)。\n"
                    "• 请前往“设置”>“身份验证”>“哔哩哔哩”，选择并应用包含有效登录会话的 Cookie 文件 (cookies.txt)。\n"
                    "• 若已配置 Cookie 文件，请确认 Cookie 是否过期，可在浏览器中重新登录 bilibili.com 并导出最新 Cookie。\n"
                    "• 避免极高频次的连续扫描以防止触发临时 IP 风控防御。"
                ),
                ErrorCategory.RATE_LIMITED: (
                    "• 哔哩哔哩服务器暂时拦截了请求 (HTTP 412 前提条件失败 / 反爬频率限制)。\n"
                    "• 请在“设置”>“身份验证”中配置有效的哔哩哔哩 Cookie 文件。\n"
                    "• 或请稍候几分钟再重试，等待服务器频率限制解除。"
                ),
                ErrorCategory.HTTP_403: (
                    "• 哔哩哔哩服务器拒绝了该请求或对当前 IP 施加了访问限制 (HTTP 403)。\n"
                    "• 请稍候片刻重试，等待服务器限制解除。\n"
                    "• 若该内容需要登录或大会员权限，请在“设置”中配置 Cookie 文件。"
                ),
                ErrorCategory.LOGIN_REQUIRED: (
                    "• 该视频或高画质流需要登录哔哩哔哩账号（或大会员）。\n"
                    "• 请前往“设置”>“身份验证”>“哔哩哔哩”导入已登录账号的 Cookie 文件。"
                ),
                ErrorCategory.COOKIE_FILE_INVALID: (
                    "• 请确认在“设置”>“身份验证”中选择的哔哩哔哩 Cookie 文件路径正确且文件存在。\n"
                    "• 确保导出的 Cookie 文件为标准 Netscape HTTP Cookie 格式且包含 SESSDATA。\n"
                    "• 避免使用空白或已损坏的文本文件。"
                ),
                ErrorCategory.VIDEO_UNAVAILABLE: (
                    "• 请在浏览器中打开链接，确认该哔哩哔哩视频是否仍然存在且能公开观看。"
                ),
                ErrorCategory.REGION_RESTRICTED: (
                    "• 该内容仅限特定地区播放（如仅限港澳台或中国大陆）。\n"
                    "• 若正在使用代理或 VPN，可尝试切换至支持该内容的地区节点。"
                ),
                ErrorCategory.TIMEOUT: (
                    "• 请检查当前网络连接状态。\n"
                    "• Channel Harvest 会自动安排延时重试。"
                ),
                ErrorCategory.NETWORK_ERROR: (
                    "• 请检查本地网络或 Wi-Fi 连接是否正常。\n"
                    "• 若开启了系统代理、防火墙或 VPN，请检查其配置是否正常。"
                ),
            }
            if self.category in bilibili_zh_actions:
                return bilibili_zh_actions[self.category]

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
            ErrorCategory.BILIBILI_API_BLOCKED: "• 哔哩哔哩风控系统拦截了请求 (错误 352)。\n• 请在“设置”>“身份验证”中配置包含有效登录状态的 Cookie 文件。\n• 若 Cookie 已过期，请在浏览器中重新登录 bilibili.com 并重新导出。",
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
        technical_details: Optional[str] = None,
    ) -> DownloadError:
        """
        Classifies raw error string into a structured DownloadError.
        Strictly evidence-based: does not overclaim.
        """
        from core.diagnostics import PrivacySanitizer

        raw_clean = str(raw_error or "").strip()
        sanitized_raw = PrivacySanitizer.sanitize_message(raw_clean)
        low = sanitized_raw.lower()

        tech_info = PrivacySanitizer.sanitize_message(str(technical_details or "")).strip()
        if not tech_info:
            tech_info = sanitized_raw

        # Detect platform context
        plat = (platform or "").lower().strip()
        if not plat:
            if any(term in low for term in ("[tiktok]", "tiktok.com", "api.tiktokv.com", "tiktok extractor")):
                plat = "tiktok"
            elif any(term in low for term in ("[douyin]", "douyin.com", "iesdouyin.com", "douyin extractor")):
                plat = "douyin"
            elif any(term in low for term in ("[bilibili", "bilibili.com", "b23.tv", "bilibilispace", "bilibili extractor")):
                plat = "bilibili"
            elif any(term in low for term in ("[facebook", "facebook.com", "fb.watch", "fb.me", "facebook extractor")):
                plat = "facebook"
            elif any(term in low for term in ("[instagram", "instagram.com", "instagr.am", "instagram extractor")):
                plat = "instagram"
            elif any(term in low for term in ("[twitter", "[x", "twitter.com", "x.com", "twitter extractor", "x extractor")):
                plat = "x"
            else:
                plat = "youtube"
        is_tiktok = (plat == "tiktok")
        is_douyin = (plat == "douyin")
        is_bilibili = (plat == "bilibili")
        is_facebook = (plat == "facebook")
        is_instagram = (plat == "instagram")
        is_x = (plat in ("x", "twitter"))

        # Infer execution stage if not explicitly provided
        st = (stage or "").lower()
        if not st or st == "video":
            if any(term in low for term in ("postprocessing:", "conversion failed", "could not write header", "incorrect codec parameters", "only supported in", "[merger]", "[videoconvertor]")):
                st = "conversion"
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
        # 0.6 Bilibili Risk-Control Rejection (API Error 352)
        # ---------------------------------------------------------------------
        if is_bilibili and ("352" in sanitized_raw or "rejected by server (352)" in low or "code=-352" in low or "code: -352" in low):
            return DownloadError(
                category=ErrorCategory.BILIBILI_API_BLOCKED,
                title=f"{stage_title} (Error 352)",
                user_message="Bilibili rejected the request due to risk-control validation (API Error 352).",
                suggested_action=(
                    "• Bilibili's risk-control system rejected unauthenticated or unverified requests to this creator space.\n"
                    "• Configure a valid Bilibili cookie file with an active session in Settings > Authentication > Bilibili.\n"
                    "• If a cookie file is already selected, verify that the cookies have not expired by logging in again at bilibili.com and exporting fresh cookies.\n"
                    "• Avoid making rapid successive scans to prevent triggering Bilibili's rate-limiting defense."
                ),
                technical_details=sanitized_raw,
                component="Bilibili / yt-dlp",
                stage=st,
                http_status=None,
                retryable=True,
                concise_status="Failed — Bilibili Error 352",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="bilibili",
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

        if st == "path_validation" or any(term in low for term in ("path validation failed", "exceeds windows", "reserved", "filename too long", "invalid argument", "errno 22", "illegal byte sequence")):
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
            "log in to continue",
            "you must log in",
            "log in to facebook",
            "log in to instagram",
            "log in to watch",
            "main webpage is locked behind the login page",
        )):
            return DownloadError(
                category=ErrorCategory.LOGIN_REQUIRED,
                title="Sign-in required",
                user_message=(
                    "This Douyin video requires an active login or permission to view."
                    if is_douyin else
                    ("This X (Twitter) post requires an active login or valid cookie file."
                    if is_x else
                    ("This Instagram post or video requires an active login or valid cookie file."
                    if is_instagram else
                    ("This Facebook video requires an active login or valid cookie file." if is_facebook else ("This TikTok video requires an active login or permission to view." if is_tiktok else "This video requires an active login or paid membership."))))
                ),
                suggested_action=(
                    "• Verify whether this video requires logging into Douyin in your web browser.\n• Check if the video is set to friends-only or private."
                    if is_douyin else
                    ("• Provide a valid X (Twitter) cookie file in Settings > Authentication.\n• Verify that you are signed in and have permission to view this content."
                    if is_x else
                    ("• Provide a valid Instagram cookie file in Settings > Authentication.\n• Verify that you are signed in and have permission to view this content."
                    if is_instagram else
                    ("• Provide a valid Facebook cookie file in Settings > Authentication.\n• Verify that you are signed in and have permission to view this video."
                    if is_facebook else
                    ("• Verify whether this video requires logging into TikTok in your web browser.\n• Check if the video or creator profile is set to friends-only or private."
                    if is_tiktok else
                    "• Configure browser authentication in Settings > YouTube Authentication.\n• Verify whether this video is members-only or requires subscription."))))
                ),
                technical_details=sanitized_raw,
                component="X / yt-dlp" if is_x else ("Instagram / yt-dlp" if is_instagram else ("Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"))),
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
        # 8. Private Video
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "private video",
            "this video is private",
            "video is private",
            "[private video]",
            "private post",
            "this post is private",
            "post is private",
            "private account",
            "only visible to an audience",
            "may only be visible to an audience",
            "permission to view this post",
            "this account is private",
            "account is private",
            "protected account",
            "this tweet is from a protected account",
            "account is protected",
            "protected tweet",
            "sign in if you've been granted access",
            "私享视频",
            "私有视频",
            "私密视频",
            "[私享视频]",
            "[私密视频]",
            "私人影片",
            "私密影片",
            "[私人影片]",
            "[私密影片]",
        )):
            return DownloadError(
                category=ErrorCategory.PRIVATE_VIDEO,
                title="Private video",
                user_message=(
                    "This Douyin video is marked private by the creator and cannot be accessed."
                    if is_douyin else
                    ("This X (Twitter) account is protected or the post is private."
                    if is_x else
                    ("This Instagram post or account is marked private and cannot be accessed without authorization."
                    if is_instagram else
                    ("This Facebook video is marked private or restricted." if is_facebook else ("This TikTok video is marked private by the creator and cannot be accessed." if is_tiktok else "This video is marked private by the channel owner and cannot be accessed."))))
                ),
                suggested_action="• Check whether the video has been made public or moved to an unlisted/private state.",
                technical_details=sanitized_raw,
                component="X / yt-dlp" if is_x else ("Instagram / yt-dlp" if is_instagram else ("Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"))),
                stage=st,
                http_status=http_code,
                retryable=False,
                concise_status="Failed — Private video",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform=plat,
            )

        # ---------------------------------------------------------------------
        # 9. Region / Geo Restriction (Checked before generic unavailability)
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
        # 10. Video Unavailable / Deleted
        # ---------------------------------------------------------------------
        if any(term in low for term in (
            "video unavailable",
            "this video is unavailable",
            "content is not available",
            "content isn't available",
            "this content is not available",
            "this content isn't available",
            "video is unavailable",
            "[unavailable video]",
            "[deleted video]",
            "deleted video",
            "video does not exist",
            "video has been deleted",
            "tweet has been deleted",
            "this tweet was deleted",
            "tweet was deleted",
            "tweet is unavailable",
            "this tweet is unavailable",
            "sorry, that page doesn't exist",
            "sorry, that page does not exist",
            "status not found",
            "no status found",
            "this video has been removed",
            "video has been removed",
            "has been removed by the uploader",
            "has been removed for violating",
            "removed by the user",
            "this video is not available",
            "video is not available",
            "no longer available",
            "premiere will begin",
            "live stream recording is not available",
            "keyerror: 'bvid'",
            "keyerror('bvid')",
            "this video may be deleted",
            "this video may be deleted or geo-restricted",
            "video may be deleted",
            "bilibili video is unavailable",
            "视频已被删除",
            "视频已删除",
            "已删除",
            "视频不可用",
            "无法访问",
            "已删除视频",
            "[已删除视频]",
            "[不可用视频]",
            "影片已被刪除",
            "影片已刪除",
            "已刪除",
            "影片無法播放",
            "影片無法存取",
            "無法存取",
            "無法播放",
            "已刪除影片",
            "[已刪除影片]",
            "[無法播放影片]",
            "[無法存取影片]",
        )):
            return DownloadError(
                category=ErrorCategory.VIDEO_UNAVAILABLE,
                title="Video unavailable",
                user_message=(
                    "This video is unavailable or has been removed from Douyin."
                    if is_douyin else
                    ("This video is unavailable or has been removed from Bilibili."
                     if is_bilibili else
                     ("This video is unavailable or has been removed from Instagram."
                     if is_instagram else
                     ("This video is unavailable or has been removed from X (Twitter)."
                     if is_x else
                     ("This video is unavailable or has been removed from Facebook." if is_facebook else ("This video is unavailable or has been removed from TikTok." if is_tiktok else "This video is unavailable or has been removed from YouTube.")))))
                ),
                suggested_action="• Verify that the video still exists and can be watched in your browser.",
                technical_details=sanitized_raw,
                component="X / yt-dlp" if is_x else ("Instagram / yt-dlp" if is_instagram else ("Douyin / yt-dlp" if is_douyin else ("TikTok / yt-dlp" if is_tiktok else "yt-dlp"))),
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
        # 9.5 Unsupported URL
        # ---------------------------------------------------------------------
        if any(term in low for term in ("unsupported url", "unsupportederror")):
            plat_name = "X (Twitter)" if is_x else ("Instagram" if is_instagram else ("Facebook" if is_facebook else ("Douyin" if is_douyin else ("TikTok" if is_tiktok else ("Bilibili" if is_bilibili else "YouTube")))))
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
            "could not write header",
            "only supported in",
            "[mov @",
            "[mp4 @",
            "[merger]",
            "[videoconvertor]",
        )):
            # 11a. Incompatible Container / Codec combination (e.g. AV1 in MOV)
            if any(term in low for term in (
                "only supported in",
                "could not write header",
                "incorrect codec parameters",
                "tag is not found",
                "codec not currently supported in container",
                "unsupported codec",
            )):
                return DownloadError(
                    category=ErrorCategory.FFMPEG_ERROR,
                    title="Unsupported Container / Codec Combination (FFmpeg)",
                    user_message="The stream codec cannot be placed into the chosen container without transcoding.",
                    suggested_action="• Select MP4 or MKV container for modern codecs like AV1.\n• Channel Harvest automatically transcodes incompatible streams when compatible encoders are available.",
                    technical_details=tech_info,
                    component="FFmpeg / Muxer",
                    stage=st,
                    http_status=None,
                    retryable=False,
                    concise_status="Failed — Incompatible Codec",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                )

            # 11b. Corrupted or truncated media input
            if any(term in low for term in (
                "invalid data found when processing input",
                "moov atom not found",
                "corrupt input packet",
                "header missing",
            )):
                return DownloadError(
                    category=ErrorCategory.FFMPEG_ERROR,
                    title="Corrupted / Incomplete Media Stream (FFmpeg)",
                    user_message="FFmpeg detected corrupted or truncated input data from the downloaded stream.",
                    suggested_action="• The download stream was interrupted or truncated by the platform server. Try downloading this video again.",
                    technical_details=tech_info,
                    component="FFmpeg / Demuxer",
                    stage=st,
                    http_status=None,
                    retryable=False,
                    concise_status="Failed — Stream corrupted",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                )

            # 11c. Generic FFmpeg Processing Error
            return DownloadError(
                category=ErrorCategory.FFMPEG_ERROR,
                title=f"{stage_title} (FFmpeg)",
                user_message="FFmpeg encountered an error while merging, converting, or processing media files.",
                suggested_action="• Verify that FFmpeg is properly installed and accessible in Settings > Runtime Manager.\n• Verify that the destination drive is writable and has free space.",
                technical_details=tech_info,
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
            plat_name = "X (Twitter)" if is_x else ("Instagram" if is_instagram else ("Facebook" if is_facebook else ("Douyin" if is_douyin else ("TikTok" if is_tiktok else ("Bilibili" if is_bilibili else "YouTube")))))
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

        # HTTP 412: Precondition Failed / Anti-scraping block (Bilibili)
        if (http_code == 412 or "412" in sanitized_raw or "blocked by server (412)" in low or "precondition failed" in low) and is_bilibili:
            return DownloadError(
                category=ErrorCategory.RATE_LIMITED,
                title=f"{stage_title} (HTTP 412)",
                user_message="Bilibili rejected the request (HTTP 412 Precondition Failed / Anti-scraping block).",
                suggested_action=(
                    "• Bilibili's anti-scraping system has restricted access to this request or space.\n"
                    "• Configure a valid Bilibili cookie file in Settings > Authentication to authenticate requests.\n"
                    "• Or wait a few minutes before retrying to allow the rate limit to expire."
                ),
                technical_details=sanitized_raw,
                component="Bilibili / yt-dlp",
                stage=st,
                http_status=412,
                retryable=True,
                concise_status="Failed — Bilibili 412",
                raw_error=sanitized_raw,
                video_id=video_id,
                video_title=video_title,
                platform="bilibili",
            )

        # HTTP 403: Forbidden
        if http_code == 403 or "403" in sanitized_raw or "forbidden" in low:
            if is_bilibili:
                return DownloadError(
                    category=ErrorCategory.HTTP_403,
                    title=f"{stage_title} (HTTP 403)",
                    user_message="Bilibili rejected the request (HTTP 403 Forbidden).",
                    suggested_action=(
                        "• Bilibili has restricted access for this request or IP address.\n"
                        "• Wait a few minutes before trying again to allow temporary restrictions to lift.\n"
                        "• If this video requires login or membership, provide a Bilibili cookie file in Settings."
                    ),
                    technical_details=sanitized_raw,
                    component="Bilibili / yt-dlp",
                    stage=st,
                    http_status=403,
                    retryable=True,
                    concise_status="Failed — Bilibili 403",
                    raw_error=sanitized_raw,
                    video_id=video_id,
                    video_title=video_title,
                    platform="bilibili",
                )
            elif is_douyin:
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
                if st in ("scan", "metadata") or "extract" in low:
                    yt_403_msg = "YouTube rejected metadata extraction for this video (HTTP 403 Forbidden)."
                    yt_403_action = (
                        "• The request was blocked or throttled by YouTube. Wait a moment before retrying.\n"
                        "• The queue will automatically proceed to subsequent items."
                    )
                else:
                    yt_403_msg = f"YouTube temporarily rejected the media stream request during {st} download (HTTP 403 Forbidden)."
                    yt_403_action = (
                        "• YouTube may have temporarily throttled media stream requests or revoked the stream signature.\n"
                        "• The queue will automatically proceed to subsequent items."
                    )
                return DownloadError(
                    category=ErrorCategory.HTTP_403,
                    title=f"{stage_title} (HTTP 403)",
                    user_message=yt_403_msg,
                    suggested_action=yt_403_action,
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
            plat_name = "X (Twitter)" if is_x else ("Instagram" if is_instagram else ("Facebook" if is_facebook else ("Douyin" if is_douyin else ("TikTok" if is_tiktok else ("Bilibili" if is_bilibili else "YouTube")))))
            return DownloadError(
                category=ErrorCategory.HTTP_404,
                title=f"{stage_title} (HTTP 404)",
                user_message=(
                    f"The media stream or resource was not found on {plat_name} (HTTP 404)."
                    if (is_tiktok or is_douyin or is_instagram or is_x) else
                    "The media stream or resource was not found on the remote server (HTTP 404)."
                ),
                suggested_action=(
                    f"• Verify that the video still exists on {plat_name}.\n• If this video was recently deleted or made private, verify in your browser."
                    if (is_tiktok or is_douyin or is_instagram or is_x) else
                    "• Verify that the video still exists on YouTube.\n• If this video was recently uploaded or deleted, refresh the channel list."
                ),
                technical_details=sanitized_raw,
                component=f"{plat_name} / yt-dlp" if (is_tiktok or is_douyin or is_instagram or is_x) else "yt-dlp",
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
        if http_code in (500, 502, 503) or any(term in low for term in (
            "500 internal", "500: internal", "http error 500", "http 500", "500 server error",
            "502 bad gateway", "502: bad gateway", "http error 502", "http 502",
            "503 service unavailable", "503: service", "http error 503", "http 503",
        )):
            code_val = http_code or (500 if "500" in sanitized_raw else 502 if "502" in sanitized_raw else 503)
            cat_val = ErrorCategory.HTTP_500 if code_val == 500 else ErrorCategory.HTTP_502 if code_val == 502 else ErrorCategory.HTTP_503
            plat_name = "X (Twitter)" if is_x else ("Instagram" if is_instagram else ("Facebook" if is_facebook else ("Douyin" if is_douyin else ("TikTok" if is_tiktok else ("Bilibili" if is_bilibili else "YouTube")))))
            return DownloadError(
                category=cat_val,
                title=f"{plat_name} server error (HTTP {code_val})",
                user_message=f"{plat_name} servers encountered a temporary internal error (HTTP {code_val}).",
                suggested_action=f"• {plat_name} servers are currently experiencing temporary issues.\n• Channel Harvest will retry automatically, or you can try again later.",
                technical_details=sanitized_raw,
                component=f"{plat_name} / yt-dlp" if (is_tiktok or is_douyin or is_instagram or is_x) else "yt-dlp",
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
            plat_name = "X (Twitter)" if is_x else ("Instagram" if is_instagram else ("Facebook" if is_facebook else ("Douyin" if is_douyin else ("TikTok" if is_tiktok else ("Bilibili" if is_bilibili else "YouTube")))))
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
            plat_name = "X (Twitter)" if is_x else ("Instagram" if is_instagram else ("Facebook" if is_facebook else ("Douyin" if is_douyin else ("TikTok" if is_tiktok else ("Bilibili" if is_bilibili else "YouTube")))))
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

    @classmethod
    def is_private_video(cls, raw_error: str) -> bool:
        """Determines whether an error message or identifier specifically denotes a private video."""
        low = str(raw_error or "").lower()
        return any(term in low for term in (
            "private video",
            "this video is private",
            "video is private",
            "[private video]",
            "private post",
            "this post is private",
            "post is private",
            "private account",
            "this account is private",
            "account is private",
            "protected account",
            "this tweet is from a protected account",
            "account is protected",
            "protected tweet",
            "sign in if you've been granted access",
            "私享视频",
            "私有视频",
            "私密视频",
            "[私享视频]",
            "[私密视频]",
            "私人影片",
            "私密影片",
            "[私人影片]",
            "[私密影片]",
        ))

    @classmethod
    def is_unavailable_video(cls, raw_error: str) -> bool:
        """Determines whether an error message specifically denotes a deleted or unavailable video."""
        low = str(raw_error or "").lower()
        if cls.is_private_video(low):
            return False
        # Region restrictions should not be lumped into general unavailable
        if any(term in low for term in (
            "not available in your country",
            "region restricted",
            "geo restricted",
            "geoblocked",
            "blocked in your country",
            "uploader has not made this video available in your country",
        )):
            return False
        return any(term in low for term in (
            "video unavailable",
            "this video is unavailable",
            "video is unavailable",
            "[unavailable video]",
            "[deleted video]",
            "deleted video",
            "video does not exist",
            "video has been deleted",
            "tweet has been deleted",
            "this tweet was deleted",
            "tweet was deleted",
            "tweet is unavailable",
            "this tweet is unavailable",
            "sorry, that page doesn't exist",
            "sorry, that page does not exist",
            "status not found",
            "no status found",
            "this video has been removed",
            "video has been removed",
            "has been removed by the uploader",
            "has been removed for violating",
            "removed by the user",
            "this video is not available",
            "video is not available",
            "no longer available",
            "premiere will begin",
            "live stream recording is not available",
            "keyerror: 'bvid'",
            "keyerror('bvid')",
            "this video may be deleted",
            "this video may be deleted or geo-restricted",
            "video may be deleted",
            "bilibili video is unavailable",
            "视频已被删除",
            "视频已删除",
            "已删除",
            "视频不可用",
            "无法访问",
            "已删除视频",
            "[已删除视频]",
            "[不可用视频]",
            "影片已被刪除",
            "影片已刪除",
            "已刪除",
            "影片無法播放",
            "影片無法存取",
            "無法存取",
            "無法播放",
            "已刪除影片",
            "[已刪除影片]",
            "[無法播放影片]",
            "[無法存取影片]",
        ))

    @classmethod
    def is_inaccessible_video(cls, raw_error: str) -> bool:
        """Returns True if the error indicates a confirmed private or unavailable video."""
        return cls.is_private_video(raw_error) or cls.is_unavailable_video(raw_error)

