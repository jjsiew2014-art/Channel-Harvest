"""
i18n.py
Internationalization (i18n) manager for Channel Harvest.
Provides translation lookup, language state management, and dynamic retranslation listeners
supporting English (en) and Simplified Chinese (zh_CN).
"""

from typing import Callable, Dict, List, Optional, Any
from core.models import (
    DownloadMode,
    SubtitleSource,
    SubtitleLanguage,
    ThumbnailFormat,
    VideoStatus,
)


class I18nManager:
    """
    Central manager for application localization.
    Patterned after ThemeManager with listener registration for live retranslation.
    """

    LANG_EN = "en"
    LANG_ZH = "zh_CN"

    LANG_ZH_TW = "zh_TW"
    # Supported language choices for UI dropdown
    LANGUAGES = [
        ("English", LANG_EN),
        ("简体中文", LANG_ZH),
        ("繁體中文", LANG_ZH_TW),
    ]

    _current_language: str = LANG_EN
    _listeners: List[Callable[[str], None]] = []

    # -------------------------------------------------------------------------
    # Translation Dictionaries
    # -------------------------------------------------------------------------
    _STRINGS: Dict[str, Dict[str, str]] = {
        
        # General & Branding
        "app_title": {
            "en": "Channel Harvest",
            "zh_CN": "Channel Harvest",
            "zh_TW": "Channel Harvest",
        },
        "app_subtitle": {
            "en": "Harvest your channel. Keep every video.",
            "zh_CN": "批量归档频道视频，完整留存每一份精彩。",
            "zh_TW": "批次封存頻道影片，完整留存每一份精彩。",
        },
        "settings_tooltip": {
            "en": "Settings",
            "zh_CN": "设置",
            "zh_TW": "設定",
        },
        "close": {
            "en": "Close",
            "zh_CN": "关闭",
            "zh_TW": "關閉",
        },
        "error": {
            "en": "Error",
            "zh_CN": "错误",
            "zh_TW": "錯誤",
        },

        # Section 1: YouTube Link
        "section_youtube_link": {
            "en": "YOUTUBE LINK",
            "zh_CN": "YOUTUBE 链接",
            "zh_TW": "YOUTUBE 連結",
        },
        "channel_url_label": {
            "en": "YouTube Channel / Playlist URL",
            "zh_CN": "YouTube 频道或播放列表链接",
            "zh_TW": "YouTube 頻道或播放清單連結",
        },
        "channel_url_placeholder": {
            "en": "https://www.youtube.com/@channel or playlist URL",
            "zh_CN": "https://www.youtube.com/@频道名 或播放列表链接",
            "zh_TW": "https://www.youtube.com/@頻道名稱 或播放清單連結",
        },
        "scan_channel": {
            "en": "Scan Channel",
            "zh_CN": "扫描频道",
            "zh_TW": "掃描頻道",
        },
        "scanning": {
            "en": "Scanning...",
            "zh_CN": "扫描中...",
            "zh_TW": "掃描中…",
        },
        "stop_scanning": {
            "en": "Stop Scanning",
            "zh_CN": "停止扫描",
            "zh_TW": "停止掃描",
        },
        "btn_stop_scanning": {
            "en": "Stop Scanning",
            "zh_CN": "停止扫描",
            "zh_TW": "停止掃描",
        },
        "status_scan_stopped": {
            "en": "Scan stopped by user",
            "zh_CN": "用户已停止扫描",
            "zh_TW": "使用者已停止掃描",
        },
        "log_scan_stopped": {
            "en": "[INFO] Scan stopped by user.",
            "zh_CN": "[INFO] 用户已停止扫描。",
            "zh_TW": "[INFO] 使用者已停止掃描。",
        },

        # Platform switching & TikTok
        "platform_label": {
            "en": "Platform",
            "zh_CN": "平台",
            "zh_TW": "平台",
        },
        "platform_all": {
            "en": "All",
            "zh_CN": "全部 (All)",
            "zh_TW": "全部 (All)",
        },
        "platform_youtube": {
            "en": "YouTube",
            "zh_CN": "YouTube",
            "zh_TW": "YouTube",
        },
        "platform_youtubemusic": {
            "en": "YouTube Music",
            "zh_CN": "YouTube Music",
            "zh_TW": "YouTube Music",
        },
        "section_youtubemusic_link": {
            "en": "YOUTUBE MUSIC LINK",
            "zh_CN": "YOUTUBE MUSIC 链接",
            "zh_TW": "YOUTUBE MUSIC 連結",
        },
        "youtubemusic_url_label": {
            "en": "YouTube Music Album / Song / Playlist URL",
            "zh_CN": "YouTube Music 专辑、单曲或播放列表链接",
            "zh_TW": "YouTube Music 專輯、單曲或播放清單連結",
        },
        "youtubemusic_url_placeholder": {
            "en": "https://music.youtube.com/playlist?list=... or song URL",
            "zh_CN": "https://music.youtube.com/playlist?list=... 或单曲链接",
            "zh_TW": "https://music.youtube.com/playlist?list=... 或單曲連結",
        },
        "scan_youtubemusic": {
            "en": "Scan Music",
            "zh_CN": "扫描音乐",
            "zh_TW": "掃描音樂",
        },
        "status_scanning_youtubemusic": {
            "en": "Connecting to YouTube Music and extracting tracks...",
            "zh_CN": "正在连接 YouTube Music 并解析曲目...",
            "zh_TW": "正在連線至 YouTube Music 並解析曲目…",
        },
        "platform_tiktok": {
            "en": "TikTok",
            "zh_CN": "TikTok",
            "zh_TW": "TikTok",
        },
        "platform_bilibili": {
            "en": "Bilibili",
            "zh_CN": "哔哩哔哩",
            "zh_TW": "嗶哩嗶哩",
        },
        "platform_douyin": {
            "en": "Douyin",
            "zh_CN": "抖音",
            "zh_TW": "抖音",
        },
        "platform_douyin_unavailable_tooltip": {
            "en": "Temporarily unavailable — waiting for an upstream yt-dlp fix.",
            "zh_CN": "暂时不可用 — 等待 yt-dlp 上游修复。",
            "zh_TW": "暫時無法使用 — 等待 yt-dlp 上游修復。",
        },
        "platform_temporarily_unavailable_title": {
            "en": "Platform Temporarily Unavailable",
            "zh_CN": "平台暂时不可用",
            "zh_TW": "平台暫時無法使用",
        },
        "platform_douyin_unavailable_msg": {
            "en": "Douyin is temporarily unavailable — waiting for an upstream yt-dlp fix.\n\nServer-side ArgusSecurityPlugin HTTP 403 blocking currently prevents metadata extraction without an upstream verification challenge solver.",
            "zh_CN": "抖音暂时不可用 — 等待 yt-dlp 上游修复。\n\n由于抖音服务器端 ArgusSecurityPlugin 施加的 HTTP 403 安全拦截，在缺少上游安全验证挑战求解器的情况下暂无法解析视频详情。",
            "zh_TW": (
                "抖音暫時無法使用 — 等待 yt-dlp 上游修復。\\n"
                "\\n"
                "由於抖音伺服器端 ArgusSecurityPlugin 施加的 HTTP 403 安全攔截，在缺少上游安全驗證挑戰求解元件的情況下暫時無法解析影片詳細資訊。"
            ),
        },
        "section_tiktok_link": {
            "en": "TIKTOK LINK",
            "zh_CN": "TIKTOK 链接",
            "zh_TW": "TIKTOK 連結",
        },
        "section_bilibili_link": {
            "en": "BILIBILI LINK",
            "zh_CN": "哔哩哔哩链接",
            "zh_TW": "嗶哩嗶哩連結",
        },
        "section_douyin_link": {
            "en": "DOUYIN LINK",
            "zh_CN": "抖音链接",
            "zh_TW": "抖音連結",
        },
        "tiktok_url_label": {
            "en": "TikTok Video / Profile URL",
            "zh_CN": "TikTok 视频或主页链接",
            "zh_TW": "TikTok 影片或個人主頁連結",
        },
        "bilibili_url_label": {
            "en": "Bilibili Video / UP Space / Playlist URL",
            "zh_CN": "哔哩哔哩视频 / UP主空间 / 播放列表链接",
            "zh_TW": "嗶哩嗶哩影片 / UP主空間 / 播放清單連結",
        },
        "douyin_url_label": {
            "en": "Douyin Video / Profile URL",
            "zh_CN": "抖音视频或主页链接",
            "zh_TW": "抖音影片或個人主頁連結",
        },
        "tiktok_url_placeholder": {
            "en": "https://www.tiktok.com/@creator/video/... or profile URL",
            "zh_CN": "https://www.tiktok.com/@作者/video/... 或主页链接",
            "zh_TW": "https://www.tiktok.com/@創作者/video/... 或主頁連結",
        },
        "bilibili_url_placeholder": {
            "en": "https://www.bilibili.com/video/BV... or space URL",
            "zh_CN": "https://www.bilibili.com/video/BV... 或个人空间链接",
            "zh_TW": "https://www.bilibili.com/video/BV... 或個人空間連結",
        },
        "douyin_url_placeholder": {
            "en": "https://www.douyin.com/video/... or share URL",
            "zh_CN": "https://www.douyin.com/video/... 或分享链接",
            "zh_TW": "https://www.douyin.com/video/... 或分享連結",
        },
        "scan_tiktok": {
            "en": "Scan TikTok",
            "zh_CN": "解析视频",
            "zh_TW": "解析影片",
        },
        "scan_bilibili": {
            "en": "Scan Bilibili",
            "zh_CN": "扫描哔哩哔哩",
            "zh_TW": "掃描嗶哩嗶哩",
        },
        "scan_douyin": {
            "en": "Scan Douyin",
            "zh_CN": "解析视频",
            "zh_TW": "解析影片",
        },
        "tooltip_tiktok_no_subs": {
            "en": "TikTok does not provide separate subtitle tracks.",
            "zh_CN": "TikTok 不提供独立外挂字幕文件。",
            "zh_TW": "TikTok 不提供獨立外掛字幕檔案。",
        },
        "tooltip_douyin_no_subs": {
            "en": "Douyin does not provide separate subtitle tracks.",
            "zh_CN": "抖音不提供独立外挂字幕文件。",
            "zh_TW": "抖音不提供獨立外掛字幕檔案。",
        },
        "tooltip_tiktok_no_chapters": {
            "en": "TikTok videos do not support chapter markers.",
            "zh_CN": "TikTok 短视频不支持章节标记。",
            "zh_TW": "TikTok 短影音不支援章節標記。",
        },
        "tooltip_douyin_no_chapters": {
            "en": "Douyin videos do not support chapter markers.",
            "zh_CN": "抖音短视频不支持章节标记。",
            "zh_TW": "抖音短影音不支援章節標記。",
        },
        "dialog_invalid_tiktok_url_title": {
            "en": "Invalid TikTok URL",
            "zh_CN": "无效的 TikTok 链接",
            "zh_TW": "TikTok 連結格式錯誤",
        },
        "dialog_invalid_bilibili_url_title": {
            "en": "Invalid Bilibili URL",
            "zh_CN": "无效的哔哩哔哩链接",
            "zh_TW": "無效的嗶哩嗶哩連結",
        },
        "dialog_invalid_bilibili_url_msg": {
            "en": "Please enter a valid Bilibili video (BV/AV), UP space, or playlist link, for example:\nhttps://www.bilibili.com/video/BV1xx411c7mD",
            "zh_CN": "请输入有效的哔哩哔哩视频 (BV/AV)、UP主空间或播放列表链接，例如：\nhttps://www.bilibili.com/video/BV1xx411c7mD",
            "zh_TW": "請輸入有效的嗶哩嗶哩影片 (BV/AV)、UP主空間或播放清單連結，例如：\nhttps://www.bilibili.com/video/BV1xx411c7mD",
        },
        "dialog_invalid_douyin_url_title": {
            "en": "Invalid Douyin URL",
            "zh_CN": "无效的抖音链接",
            "zh_TW": "抖音連結格式錯誤",
        },
        "dialog_invalid_tiktok_url_msg": {
            "en": "Please enter a valid TikTok video or profile link, for example:\nhttps://www.tiktok.com/@creator/video/1234567890123456789",
            "zh_CN": "请输入有效的 TikTok 视频或作者主页链接，例如：\nhttps://www.tiktok.com/@creator/video/1234567890123456789",
            "zh_TW": (
                "請輸入有效的 TikTok 影片或創作者主頁連結，例如：\\n"
                "https://www.tiktok.com/@creator/video/1234567890123456789"
            ),
        },
        "dialog_invalid_douyin_url_msg": {
            "en": "Please enter a valid Douyin video or share link, for example:\nhttps://www.douyin.com/video/1234567890123456789",
            "zh_CN": "请输入有效的抖音视频或分享链接，例如：\nhttps://www.douyin.com/video/1234567890123456789",
            "zh_TW": (
                "請輸入有效的抖音影片或分享連結，例如：\\n"
                "https://www.douyin.com/video/1234567890123456789"
            ),
        },

        # Section 2: Available Videos
        "section_available_videos": {
            "en": "AVAILABLE VIDEOS",
            "zh_CN": "视频列表",
            "zh_TW": "可下載影片",
        },
        "source_title_badge": {
            "en": "SOURCE TITLE",
            "zh_CN": "来源名称",
            "zh_TW": "來源名稱",
        },
        "source_title_empty": {
            "en": "No source loaded",
            "zh_CN": "未加载来源",
            "zh_TW": "未載入來源",
        },
        "source_title_scanning": {
            "en": "Scanning source…",
            "zh_CN": "正在扫描来源…",
            "zh_TW": "正在掃描來源…",
        },
        "source_title_unavailable": {
            "en": "Source unavailable",
            "zh_CN": "来源不可用",
            "zh_TW": "來源無法使用",
        },
        "header_select": {
            "en": "",
            "zh_CN": "",
            "zh_TW": "",
        },
        "header_index": {
            "en": "#",
            "zh_CN": "#",
            "zh_TW": "#",
        },
        "header_title": {
            "en": "Video Title",
            "zh_CN": "视频标题",
            "zh_TW": "影片標題",
        },
        "header_duration": {
            "en": "Duration",
            "zh_CN": "时长",
            "zh_TW": "時長",
        },
        "header_subtitle": {
            "en": "Subtitle",
            "zh_CN": "字幕",
            "zh_TW": "字幕",
        },
        "header_video_id": {
            "en": "Video ID",
            "zh_CN": "视频 ID",
            "zh_TW": "影片 ID",
        },
        "header_status": {
            "en": "Status",
            "zh_CN": "状态",
            "zh_TW": "狀態",
        },
        "subtitle_yes": {
            "en": "Yes",
            "zh_CN": "有",
            "zh_TW": "有",
        },
        "subtitle_no": {
            "en": "No",
            "zh_CN": "无",
            "zh_TW": "無",
        },
        "subtitle_checking": {
            "en": "Checking...",
            "zh_CN": "检测中...",
            "zh_TW": "偵測中…",
        },
        "videos_found_fmt": {
            "en": "{found} media found",
            "zh_CN": "找到 {found} 个媒体",
            "zh_TW": "找到 {found} 個媒體",
        },
        "videos_selected_fmt": {
            "en": "{selected} selected",
            "zh_CN": "已选择 {selected} 个",
            "zh_TW": "已選取 {selected} 部",
        },
        "select_all": {
            "en": "Select All",
            "zh_CN": "全选",
            "zh_TW": "全選",
        },
        "deselect_all": {
            "en": "Deselect All",
            "zh_CN": "取消全选",
            "zh_TW": "全部取消選取",
        },
        "clear_list": {
            "en": "Clear List",
            "zh_CN": "清空列表",
            "zh_TW": "清空列表",
        },
        "clear_list_tooltip": {
            "en": "Clear all videos from the table",
            "zh_CN": "清空表格中的所有视频",
            "zh_TW": "從列表中清除所有影片",
        },
        "search_placeholder": {
            "en": "🔍 Search videos...",
            "zh_CN": "🔍 搜索视频...",
            "zh_TW": "🔍 搜尋影片…",
        },
        "empty_title": {
            "en": "No media available",
            "zh_CN": "暂无媒体",
            "zh_TW": "尚無可用媒體",
        },
        "empty_subtitle": {
            "en": "Scan a YouTube channel or playlist to load videos.",
            "zh_CN": "扫描 YouTube 频道或播放列表以加载视频。",
            "zh_TW": "請在上方輸入 YouTube 頻道或播放清單網址，然後點擊「掃描頻道」",
        },
        "empty_subtitle_tiktok": {
            "en": "Scan a TikTok video URL to load videos.",
            "zh_CN": "扫描 TikTok 视频链接以加载视频。",
            "zh_TW": "請在上方輸入 TikTok 影片連結，然後點擊「解析影片」",
        },
        "empty_subtitle_bilibili": {
            "en": "Scan a Bilibili video or UP space URL to load videos.",
            "zh_CN": "扫描哔哩哔哩视频或 UP 主空间链接以加载视频列表。",
            "zh_TW": "請在上方輸入嗶哩嗶哩影片或 UP 主空間連結，然後點擊「掃描嗶哩嗶哩」",
        },
        "empty_subtitle_douyin": {
            "en": "Scan a Douyin video URL to load videos.",
            "zh_CN": "扫描抖音视频链接以加载视频。",
            "zh_TW": "請在上方輸入抖音影片連結，然後點擊「解析影片」",
        },

        # Video Table Context Menu
        "ctx_copy_title": {
            "en": "Copy Title",
            "zh_CN": "复制标题",
            "zh_TW": "複製標題",
        },
        "ctx_copy_url": {
            "en": "Copy URL",
            "zh_CN": "复制链接",
            "zh_TW": "複製影片網址",
        },
        "ctx_copy_id": {
            "en": "Copy Video ID",
            "zh_CN": "复制视频 ID",
            "zh_TW": "複製影片 ID",
        },
        "ctx_open_browser": {
            "en": "Open in Browser",
            "zh_CN": "在浏览器中打开",
            "zh_TW": "在瀏覽器中開啟",
        },
        "ctx_view_error_details": {
            "en": "View Error Details...",
            "zh_CN": "查看错误详情...",
            "zh_TW": "檢視錯誤詳情…",
        },
        "ctx_copy_error_details": {
            "en": "Copy Error Details",
            "zh_CN": "复制错误报告",
            "zh_TW": "複製錯誤報告",
        },

        # Section 3: Download Option
        "section_download_option": {
            "en": "DOWNLOAD OPTION",
            "zh_CN": "下载选项",
            "zh_TW": "下載選項",
        },
        "save_to": {
            "en": "Save to:",
            "zh_CN": "保存到：",
            "zh_TW": "儲存至：",
        },
        "browse": {
            "en": "Browse...",
            "zh_CN": "浏览...",
            "zh_TW": "瀏覽…",
        },

        # Sub-panel 1: MEDIA
        "subsection_media": {
            "en": "MEDIA",
            "zh_CN": "视频与音频",
            "zh_TW": "媒體",
        },
        "label_mode": {
            "en": "Mode",
            "zh_CN": "下载内容",
            "zh_TW": "下載模式",
        },
        "label_resolution": {
            "en": "Video Resolution",
            "zh_CN": "视频分辨率",
            "zh_TW": "影片解析度",
        },
        "label_video_format": {
            "en": "Video Format",
            "zh_CN": "视频格式",
            "zh_TW": "影片格式",
        },
        "label_video_bitrate": {
            "en": "Video Bitrate",
            "zh_CN": "视频码率",
            "zh_TW": "影片位元率",
        },
        "label_audio_format": {
            "en": "Audio Format",
            "zh_CN": "音频格式",
            "zh_TW": "音訊格式",
        },
        "label_audio_bitrate": {
            "en": "Audio Bitrate",
            "zh_CN": "音频质量",
            "zh_TW": "音訊位元率",
        },

        # Sub-panel 2: ADDITIONAL ASSETS
        "subsection_assets": {
            "en": "ADDITIONAL ASSETS",
            "zh_CN": "附加内容",
            "zh_TW": "附加內容",
        },
        "cb_subtitles": {
            "en": "Subtitles",
            "zh_CN": "字幕",
            "zh_TW": "下載字幕",
        },
        "label_sub_source": {
            "en": "Source",
            "zh_CN": "字幕来源",
            "zh_TW": "字幕來源",
        },
        "label_sub_lang": {
            "en": "Language",
            "zh_CN": "字幕语言",
            "zh_TW": "字幕語言",
        },
        "label_sub_format": {
            "en": "Subtitle Format",
            "zh_CN": "字幕格式",
            "zh_TW": "字幕格式",
        },
        "cb_thumbnail": {
            "en": "Download thumbnail",
            "zh_CN": "下载封面图",
            "zh_TW": "下載縮圖",
        },
        "cb_thumbnail_tooltip": {
            "en": "Download the video's YouTube thumbnail as a separate image file.",
            "zh_CN": "将视频的 YouTube 封面保存为独立图片文件。",
            "zh_TW": "將 YouTube 影片的縮圖儲存為獨立圖片檔案。",
        },
        "cb_download_cover_art": {
            "en": "Download Cover Art",
            "zh_CN": "下载专辑封面",
            "zh_TW": "下載專輯封面",
        },
        "cb_download_cover_art_with_dims": {
            "en": "Download Cover Art ({width}x{height})",
            "zh_CN": "下载专辑封面 ({width}x{height})",
            "zh_TW": "下載專輯封面 ({width}x{height})",
        },
        "tooltip_download_cover_art": {
            "en": "Download the original 1:1 square album Cover Art image.",
            "zh_CN": "下载 1:1 正方形超清专辑封面图片。",
            "zh_TW": "下載 1:1 正方形超清專輯封面圖片。",
        },
        "cb_embed_cover_art": {
            "en": "Embed Cover Art into Audio Tag",
            "zh_CN": "将 Cover Art 嵌入音频 Tag",
            "zh_TW": "將 Cover Art 嵌入音訊 Tag",
        },
        "tooltip_embed_cover_art": {
            "en": "Embed the 1:1 square Cover Art directly into downloaded audio files.",
            "zh_CN": "将 1:1 正方形专辑封面直接写入下载的音频文件标签。",
            "zh_TW": "將 1:1 正方形專輯封面直接寫入下載的音訊檔案標籤。",
        },
        "tooltip_embed_cover_art_unsupported": {
            "en": "Embedding cover art is supported for MP3, M4A, FLAC, and OPUS audio formats (WAV and AAC do not support embedded cover art).",
            "zh_CN": "内嵌专辑封面支持 MP3、M4A、FLAC 和 OPUS 格式（WAV 与 AAC 格式不支持内嵌封面）。",
            "zh_TW": "內嵌專輯封面支援 MP3、M4A、FLAC 和 OPUS 格式（WAV 與 AAC 格式不支援內嵌封面）。",
        },
        "cb_embed_media_metadata": {
            "en": "Embed Media Metadata into Audio Tag",
            "zh_CN": "将媒体元数据嵌入音频 Tag",
            "zh_TW": "將媒體中繼資料嵌入音訊 Tag",
        },
        "tooltip_embed_media_metadata": {
            "en": "Embed track title, artist, album, date, and other metadata into audio tags (MP3, M4A, FLAC, OPUS).",
            "zh_CN": "将歌名、艺术家、专辑名、发行年份等媒体元数据嵌入音频文件标签（支持 MP3、M4A、FLAC、OPUS）。",
            "zh_TW": "將歌名、演出者、專輯名、發行年份等媒體中繼資料嵌入音訊檔案標籤（支援 MP3、M4A、FLAC、OPUS）。",
        },
        "tooltip_embed_media_metadata_unsupported": {
            "en": "Metadata embedding is supported for MP3, M4A, FLAC, and OPUS audio formats (WAV and AAC do not support embedded tags).",
            "zh_CN": "音频元数据嵌入支持 MP3、M4A、FLAC 和 OPUS 格式（WAV 与 AAC 格式不支持内嵌标签）。",
            "zh_TW": "音訊中繼資料嵌入支援 MP3、M4A、FLAC 與 OPUS 格式（WAV 與 AAC 格式不支援內嵌標籤）。",
        },
        "cb_download_lrc_lyrics": {
            "en": "Download LRC Lyrics",
            "zh_CN": "下载 LRC 同步歌词",
            "zh_TW": "下載 LRC 同步歌詞",
        },
        "tooltip_download_lrc_lyrics": {
            "en": "Download synchronized line-by-line LRC lyrics (.lrc file) alongside the audio.",
            "zh_CN": "检索并下载与音频同名的 LRC 逐行同步歌词文件。",
            "zh_TW": "擷取並下載與音訊同名的 LRC 逐行同步歌詞檔案。",
        },
        "cb_embed_lyrics": {
            "en": "Embed Lyrics into Audio Tag",
            "zh_CN": "将歌词嵌入音频 Tag",
            "zh_TW": "將歌詞嵌入音訊 Tag",
        },
        "tooltip_embed_lyrics": {
            "en": "Embed synchronized LRC lyrics directly into audio file tags (MP3, M4A, FLAC, OPUS).",
            "zh_CN": "将 LRC 同步歌词直接嵌入音频文件标签（支持 MP3、M4A、FLAC、OPUS）。",
            "zh_TW": "將 LRC 同步歌詞直接嵌入音訊檔案標籤（支援 MP3、M4A、FLAC、OPUS）。",
        },
        "tooltip_embed_lyrics_unsupported": {
            "en": "Lyrics embedding is supported for MP3, M4A, FLAC, and OPUS audio formats (WAV and AAC do not support embedded lyrics tags).",
            "zh_CN": "歌词嵌入仅支持 MP3、M4A、FLAC 与 OPUS 格式（WAV 与 AAC 格式不支持嵌入歌词标签）。",
            "zh_TW": "歌詞嵌入僅支援 MP3、M4A、FLAC 與 OPUS 格式（WAV 與 AAC 格式不支援內嵌歌詞標籤）。",
        },
        "label_thumb_format": {
            "en": "Thumbnail Format",
            "zh_CN": "封面格式",
            "zh_TW": "縮圖格式",
        },
        "label_thumb_format_tooltip": {
            "en": "Format for saved thumbnail image.",
            "zh_CN": "保存封面图的图片格式。",
            "zh_TW": "選擇縮圖圖片的儲存格式。",
        },
        "subgroup_info_files": {
            "en": "INFORMATION FILES",
            "zh_CN": "视频信息",
            "zh_TW": "資訊檔案",
        },
        "cb_save_desc": {
            "en": "Save description",
            "zh_CN": "保存视频简介",
            "zh_TW": "儲存影片說明",
        },
        "cb_save_desc_tooltip": {
            "en": "Save original YouTube video description to a .description text file.",
            "zh_CN": "将原始 YouTube 视频简介保存为 .description 文本文件。",
            "zh_TW": "將 YouTube 影片的原始說明欄內容儲存為 .description 純文字檔案。",
        },
        "cb_save_meta": {
            "en": "Save metadata",
            "zh_CN": "保存元数据",
            "zh_TW": "儲存中繼資料",
        },
        "cb_save_meta_tooltip": {
            "en": "Save clean, organized video metadata to a .metadata.txt file.",
            "zh_CN": "将整理后的视频元数据保存为 .metadata.txt 文件。",
            "zh_TW": "將整理後的影片中繼資料儲存為 .metadata.txt 檔案。",
        },
        "cb_save_chapters": {
            "en": "Save chapters",
            "zh_CN": "保存章节",
            "zh_TW": "儲存章節資訊",
        },
        "cb_save_chapters_tooltip": {
            "en": "Save video chapter markers to a .chapters.txt file.",
            "zh_CN": "将视频章节标记保存为 .chapters.txt 文件。",
            "zh_TW": "將影片章節標記儲存為 .chapters.txt 檔案。",
        },

        # Sub-panel 3: FILE ORGANIZATION
        "subsection_org": {
            "en": "FILE ORGANIZATION",
            "zh_CN": "文件整理",
            "zh_TW": "檔案整理",
        },
        "cb_skip_existing": {
            "en": "Skip downloaded videos",
            "zh_CN": "跳过已下载视频",
            "zh_TW": "略過已下載影片",
        },
        "cb_skip_existing_tooltip": {
            "en": "Skip downloading files that already exist in the target folder.",
            "zh_CN": "跳过目标文件夹中已存在的视频文件。",
            "zh_TW": "自動略過目標資料夾中已存在的影片檔案。",
        },
        "cb_channel_folder": {
            "en": "Create channel subfolder",
            "zh_CN": "按频道分类存放",
            "zh_TW": "依頻道建立子資料夾",
        },
        "cb_channel_folder_tooltip": {
            "en": "Store videos inside a folder named after the channel.",
            "zh_CN": "在目标目录中按频道名称建立子文件夹保存。",
            "zh_TW": "在目標路徑下以頻道名稱建立子資料夾存放影片。",
        },
        "cb_individual_folder": {
            "en": "Create individual video folders",
            "zh_CN": "每个视频单独建文件夹",
            "zh_TW": "為每部影片建立獨立資料夾",
        },
        "cb_individual_folder_tooltip": {
            "en": "Store each video's files in its own folder.",
            "zh_CN": "为每个视频创建专属文件夹存放其所有相关文件。",
            "zh_TW": "為每部影片建立專屬資料夾存放其所有關聯檔案。",
        },
        "cb_include_video_id": {
            "en": "Include Video ID in filename",
            "zh_CN": "文件名包含 Video ID",
            "zh_TW": "檔名包含影片 ID",
        },
        "cb_include_video_id_tooltip": {
            "en": "Include YouTube Video ID in downloaded filenames.",
            "zh_CN": "在下载的文件名中包含 Video ID。",
            "zh_TW": "在下載的檔案名稱中加入影片 ID 以防止衝突。",
        },

        # Action Bar Buttons
        "btn_start_download": {
            "en": "Start Download",
            "zh_CN": "开始下载",
            "zh_TW": "開始下載",
        },
        "btn_pause": {
            "en": "Pause",
            "zh_CN": "暂停",
            "zh_TW": "暫停",
        },
        "btn_pause_tooltip": {
            "en": "Pause queue after current media finishes",
            "zh_CN": "在当前媒体下载完成后暂停队列",
            "zh_TW": "在目前媒體下載完成後暫停佇列",
        },
        "btn_resume": {
            "en": "Resume",
            "zh_CN": "继续",
            "zh_TW": "繼續",
        },
        "btn_resume_tooltip": {
            "en": "Resume paused download queue",
            "zh_CN": "恢复已暂停的下载队列",
            "zh_TW": "繼續執行已暫停的下載佇列",
        },
        "btn_cancel": {
            "en": "Cancel",
            "zh_CN": "取消",
            "zh_TW": "取消",
        },
        "btn_cancel_tooltip": {
            "en": "Cancel active download and stop queue",
            "zh_CN": "取消当前下载并停止队列",
            "zh_TW": "取消目前下載並停止佇列",
        },
        "btn_open_folder": {
            "en": "Open Folder",
            "zh_CN": "打开文件夹",
            "zh_TW": "開啟資料夾",
        },
        "btn_open_folder_tooltip": {
            "en": "Open destination directory in Windows Explorer",
            "zh_CN": "在 Windows 资源管理器中打开目标目录",
            "zh_TW": "在 Windows 檔案總管中開啟下載目的地資料夾",
        },

        # Section 4: Download Progress
        "section_download_progress": {
            "en": "DOWNLOAD PROGRESS",
            "zh_CN": "下载进度",
            "zh_TW": "下載進度",
        },
        "current_video_none": {
            "en": "Current Media: None",
            "zh_CN": "当前媒体：无",
            "zh_TW": "目前媒體：無",
        },
        "current_video_fmt": {
            "en": "Current Media: {title}",
            "zh_CN": "当前媒体：{title}",
            "zh_TW": "目前媒體：{title}",
        },
        "overall_progress_fmt": {
            "en": "Overall Progress: {completed} / {total} completed",
            "zh_CN": "总进度：已完成 {completed} / {total}",
            "zh_TW": "總進度：已完成 {completed} / {total}",
        },
        "speed_fmt": {
            "en": "Speed: {speed}",
            "zh_CN": "下载速度：{speed}",
            "zh_TW": "下載速度：{speed}",
        },
        "eta_fmt": {
            "en": "ETA: {eta}",
            "zh_CN": "预计剩余时间：{eta}",
            "zh_TW": "剩餘時間：{eta}",
        },
        "queue_stats_fmt": {
            "en": "Completed: {completed} | Skipped: {skipped} | Failed: {failed} | Remaining: {remaining}",
            "zh_CN": "已完成：{completed} | 已跳过：{skipped} | 失败：{failed} | 剩余：{remaining}",
            "zh_TW": "已完成：{completed} | 已略過：{skipped} | 失敗：{failed} | 剩餘：{remaining}",
        },

        # Section 5: Activity Log
        "section_activity_log": {
            "en": "ACTIVITY LOG",
            "zh_CN": "运行日志",
            "zh_TW": "執行記錄",
        },
        "dialog_activity_log_title": {
            "en": "Activity Log",
            "zh_CN": "活动日志",
            "zh_TW": "活動記錄",
        },
        "btn_activity_log_tooltip": {
            "en": "Activity Log",
            "zh_CN": "活动日志",
            "zh_TW": "活動記錄",
        },
        "btn_copy_log": {
            "en": "Copy All",
            "zh_CN": "复制全部",
            "zh_TW": "複製全部",
        },
        "btn_copied": {
            "en": "Copied!",
            "zh_CN": "已复制!",
            "zh_TW": "已複製!",
        },
        "log_cleared": {
            "en": "Log cleared",
            "zh_CN": "日志已清空",
            "zh_TW": "記錄已清空",
        },
        "log_copied_hint": {
            "en": "Log copied to clipboard",
            "zh_CN": "日志已复制到剪贴板",
            "zh_TW": "記錄已複製至剪貼簿",
        },
        "btn_close": {
            "en": "Close",
            "zh_CN": "关闭",
            "zh_TW": "關閉",
        },
        "log_hint": {
            "en": "Real-time extraction and download output",
            "zh_CN": "实时解析与下载输出",
            "zh_TW": "即時解析與下載輸出",
        },
        "show_log": {
            "en": "Show Log ▾",
            "zh_CN": "显示日志 ▾",
            "zh_TW": "顯示記錄 ▾",
        },
        "hide_log": {
            "en": "Hide Log ▴",
            "zh_CN": "收起日志 ▴",
            "zh_TW": "收起記錄 ▴",
        },
        "clear_log": {
            "en": "Clear Log",
            "zh_CN": "清空日志",
            "zh_TW": "清空記錄",
        },

        # Status Bar Messages
        "status_ready": {
            "en": "Ready • Paste a YouTube channel URL and click 'Scan Channel'",
            "zh_CN": "就绪 • 请粘贴 YouTube 频道或播放列表链接并点击“扫描频道”",
            "zh_TW": "就緒 • 請貼上 YouTube 頻道或播放清單網址並點擊「掃描頻道」",
        },
        "status_scanning": {
            "en": "Scanning channel...",
            "zh_CN": "正在扫描频道...",
            "zh_TW": "正在掃描頻道…",
        },
        "status_scan_complete_fmt": {
            "en": "Scan complete • {count} videos found",
            "zh_CN": "扫描完成 • 找到 {count} 个视频",
            "zh_TW": "掃描完成 • 找到 {count} 部影片",
        },
        "status_scan_empty": {
            "en": "Scan complete • No downloadable videos found.",
            "zh_CN": "扫描完成 • 未找到可下载的视频。",
            "zh_TW": "掃描完成 • 未找到可下載的影片。",
        },
        "status_scan_failed": {
            "en": "Scan failed. Check the channel URL and network connection.",
            "zh_CN": "扫描失败。请检查频道链接与网络连接。",
            "zh_TW": "掃描失敗。請檢查頻道網址與網路連線。",
        },
        "status_downloading_fmt": {
            "en": "Downloading {index}/{total}: {title}",
            "zh_CN": "正在下载 {index}/{total}：{title}",
            "zh_TW": "正在下載 {index}/{total}：{title}",
        },
        "status_paused": {
            "en": "Queue paused.",
            "zh_CN": "下载队列已暂停。",
            "zh_TW": "下載佇列已暫停。",
        },
        "status_resumed": {
            "en": "Queue resumed.",
            "zh_CN": "下载队列已继续。",
            "zh_TW": "下載佇列已繼續。",
        },
        "status_cancelled": {
            "en": "Download cancelled.",
            "zh_CN": "下载已取消。",
            "zh_TW": "下載佇列已取消。",
        },
        "status_finished_fmt": {
            "en": "Download finished • {completed} completed, {failed} failed, {skipped} skipped",
            "zh_CN": "下载已完成 • 成功 {completed}，失败 {failed}，跳过 {skipped}",
            "zh_TW": "下載完成 • 成功 {completed}，失敗 {failed}，已略過 {skipped}",
        },

        # Common Messages & Dialogs
        "dialog_no_selection_title": {
            "en": "No Videos Selected",
            "zh_CN": "未选择视频",
            "zh_TW": "未選取影片",
        },
        "dialog_no_selection_msg": {
            "en": "Please select at least one video to download.",
            "zh_CN": "请至少勾选一个要下载的视频。",
            "zh_TW": "請至少勾選一部要下載的影片。",
        },
        "dialog_no_assets_selected_title": {
            "en": "No Additional Assets Selected",
            "zh_CN": "未选择任何附加内容",
            "zh_TW": "未選取任何附加內容",
        },
        "dialog_no_assets_selected_msg": {
            "en": "You have selected 'Assets Only' download mode, but no items under Additional Assets are selected.\n\nPlease select at least one item (Subtitles, Thumbnail, Description, Metadata, or Chapters) before starting the download.",
            "zh_CN": "您已选择“仅附加内容”下载模式，但尚未在“附加内容”中勾选任何项目。\n\n请至少选择一项（字幕、封面、简介、元数据或章节标记）后再开始下载。",
            "zh_TW": (
                "您已選擇「僅附加內容」下載模式，但尚未在「附加內容」中勾選任何項目。\\n"
                "\\n"
                "請在開始下載前至少選取一項（字幕、縮圖、說明、中繼資料或章節標記）。"
            ),
        },
        "dialog_invalid_url_title": {
            "en": "Invalid URL",
            "zh_CN": "链接无效",
            "zh_TW": "連結格式錯誤",
        },
        "dialog_invalid_url_msg": {
            "en": "Please enter a valid YouTube channel or playlist URL.",
            "zh_CN": "请输入有效的 YouTube 频道或播放列表链接。",
            "zh_TW": "請輸入有效的 YouTube 頻道或播放清單連結。",
        },
        "dialog_missing_dest_title": {
            "en": "Missing Destination",
            "zh_CN": "未指定保存文件夹",
            "zh_TW": "未指定儲存資料夾",
        },
        "dialog_missing_dest_msg": {
            "en": "Please choose a download destination folder.",
            "zh_CN": "请选择视频下载的目标文件夹。",
            "zh_TW": "請選擇影片下載的目的地資料夾。",
        },
        "dialog_folder_not_found_title": {
            "en": "Folder Not Found",
            "zh_CN": "文件夹不存在",
            "zh_TW": "找不到資料夾",
        },
        "dialog_folder_not_found_msg": {
            "en": "The destination directory does not exist yet:\n{folder}",
            "zh_CN": "目标文件夹尚不存在：\n{folder}",
            "zh_TW": (
                "目的地資料夾尚不存在：\\n"
                "{folder}"
            ),
        },
        "dialog_ffmpeg_warning_title": {
            "en": "FFmpeg Recommended",
            "zh_CN": "建议配置 FFmpeg",
            "zh_TW": "建議安裝 FFmpeg",
        },
        "dialog_ffmpeg_warning_msg": {
            "en": "FFmpeg is not detected on your system. Merging video/audio streams, extracting audio, "
                  "converting subtitles, or converting thumbnails requires FFmpeg.\n\n"
                  "Would you like to continue anyway?",
            "zh_CN": "检测到系统尚未配置 FFmpeg。合并音视频流、提取音频、转换字幕或封面格式需要 FFmpeg 支持。\n\n是否仍要继续？",
            "zh_TW": (
                "系統中未偵測到 FFmpeg。合併視訊與音訊串流、提取音訊、轉換字幕或縮圖格式都需要 FFmpeg 支援。\\n"
                "\\n"
                "是否仍要繼續？"
            ),
        },
        "dialog_confirm_cancel_title": {
            "en": "Confirm Cancellation",
            "zh_CN": "确认取消",
            "zh_TW": "確認取消",
        },
        "dialog_confirm_cancel_msg": {
            "en": "Are you sure you want to cancel the current download and stop the queue?",
            "zh_CN": "确定要取消当前下载并停止队列吗？",
            "zh_TW": "確定要取消目前的下載並停止佇列嗎？",
        },
        "select_folder_title": {
            "en": "Select Download Destination Folder",
            "zh_CN": "选择下载保存文件夹",
            "zh_TW": "選擇下載儲存資料夾",
        },

        # Settings Dialog
        "settings_window_title": {
            "en": "Settings - Channel Harvest",
            "zh_CN": "设置 - Channel Harvest",
            "zh_TW": "設定 - Channel Harvest",
        },
        "settings_general": {
            "en": "GENERAL",
            "zh_CN": "常规",
            "zh_TW": "一般",
        },
        "settings_notifications_title": {
            "en": "Desktop Notifications",
            "zh_CN": "桌面通知",
            "zh_TW": "桌面通知",
        },
        "settings_notifications_desc": {
            "en": "Show a Windows desktop notification when all downloads complete.",
            "zh_CN": "下载完成后显示 Windows 桌面通知提示。",
            "zh_TW": "下載完成後顯示 Windows 桌面通知提示。",
        },
        "settings_clear_link_title": {
            "en": "Automatic Clear Source Link",
            "zh_CN": "自动清空来源链接",
            "zh_TW": "自動清空來源連結",
        },
        "settings_clear_link_desc": {
            "en": "Clear the source link input after all downloads complete.",
            "zh_CN": "下载完成后自动清空来源链接输入框。",
            "zh_TW": "下載完成後自動清空來源連結輸入框。",
        },
        "settings_clear_media_list_title": {
            "en": "Automatic Clear Media List",
            "zh_CN": "自动清空媒体列表",
            "zh_TW": "自動清空媒體列表",
        },
        "settings_clear_media_list_desc": {
            "en": "Clear the scanned media list after all downloads complete.",
            "zh_CN": "下载完成后自动清空已扫描的媒体列表。",
            "zh_TW": "下載完成後自動清空已掃描的媒體列表。",
        },
        "settings_clear_custom_folder_title": {
            "en": "Automatic Clear Custom Folder Name",
            "zh_CN": "自动清空自定义文件夹名称",
            "zh_TW": "自動清空自訂資料夾名稱",
        },
        "settings_clear_custom_folder_desc": {
            "en": "Clear the custom folder name input after all downloads complete.",
            "zh_CN": "下载完成后自动清空自定义文件夹名称输入框。",
            "zh_TW": "下載完成後自動清空自訂資料夾名稱輸入框。",
        },
        "settings_include_media_id_title": {
            "en": "Include Media ID in Filename",
            "zh_CN": "文件名包含媒体 ID",
            "zh_TW": "檔案名稱包含媒體 ID",
        },
        "settings_include_media_id_desc": {
            "en": "Append the platform media or video ID to saved filenames.",
            "zh_CN": "在保存的文件名末尾添加对应媒体或视频的平台 ID。",
            "zh_TW": "在儲存的檔案名稱結尾新增對應媒體或影片的平台 ID。",
        },
        "settings_auto_scan_on_paste_title": {
            "en": "Auto-Scan on Paste",
            "zh_CN": "粘贴链接后自动扫描",
            "zh_TW": "貼上連結後自動掃描",
        },
        "settings_auto_scan_on_paste_desc": {
            "en": "Automatically start scanning when a valid media link is pasted into the Link field.",
            "zh_CN": "当完整粘贴有效媒体链接至主界面链接输入框时，自动触发扫描程序。",
            "zh_TW": "當完整貼上有效媒體連結至主畫面連結輸入框時，自動觸發掃描程序。",
        },
        "settings_skip_downloaded_media_title": {
            "en": "Skip Downloaded Media",
            "zh_CN": "跳过已下载媒体",
            "zh_TW": "略過已下載媒體",
        },
        "settings_skip_downloaded_media_desc": {
            "en": "Skip media items that already exist in the download directory or archive.",
            "zh_CN": "跳过保存目录中已存在或已被归档的媒体文件。",
            "zh_TW": "略過儲存目錄中已存在或已被封存的媒體檔案。",
        },
        "settings_appearance": {
            "en": "APPEARANCE",
            "zh_CN": "外观",
            "zh_TW": "外觀",
        },
        "settings_notifications": {
            "en": "Windows Notifications",
            "zh_CN": "系统通知",
            "zh_TW": "系統通知",
        },
        "settings_enable_notifications": {
            "en": "Show notification when downloads complete",
            "zh_CN": "下载完成后弹出系统通知提示",
            "zh_TW": "下載完成後彈出系統通知提示",
        },
        "settings_clear_link_lbl": {
            "en": "Source Link",
            "zh_CN": "源链接",
            "zh_TW": "來源連結",
        },
        "settings_clear_link": {
            "en": "Clear link after download completes",
            "zh_CN": "下载完成后清空链接",
            "zh_TW": "下載完成後清空連結",
        },
        "tooltip_clear_link": {
            "en": "Automatically clear the source link input after download completes.",
            "zh_CN": "下载完成后自动清空输入的链接文本。",
            "zh_TW": "下載完成後自動清空輸入的連結文字。",
        },
        "settings_clear_table_lbl": {
            "en": "Media Table",
            "zh_CN": "媒体列表",
            "zh_TW": "媒體清單",
        },
        "settings_clear_media_table": {
            "en": "Clear media table after download completes",
            "zh_CN": "下载完成后清空媒体列表",
            "zh_TW": "下載完成後清空媒體清單",
        },
        "tooltip_clear_media_table": {
            "en": "Automatically clear the available media table after download completes.",
            "zh_CN": "下载完成后自动清空可用媒体列表。",
            "zh_TW": "下載完成後自動清空可用媒體清單。",
        },
        "notification_download_completed_title": {
            "en": "Downloaded Completed",
            "zh_CN": "下载完成",
            "zh_TW": "下載完成",
        },
        "notification_download_completed_stats": {
            "en": "{completed} Completed, {skipped} Skipped, {failed} Failed",
            "zh_CN": "完成 {completed}，跳过 {skipped}，失败 {failed}",
            "zh_TW": "完成 {completed}，略過 {skipped}，失敗 {failed}",
        },
        "settings_theme": {
            "en": "Theme",
            "zh_CN": "主题",
            "zh_TW": "主題",
        },
        "settings_language": {
            "en": "Language",
            "zh_CN": "语言",
            "zh_TW": "語言",
        },
        "settings_sys_components": {
            "en": "SYSTEM COMPONENTS",
            "zh_CN": "系统组件",
            "zh_TW": "系統元件",
        },
        "installed": {
            "en": "Installed",
            "zh_CN": "已安装",
            "zh_TW": "已安裝",
        },
        "not_found": {
            "en": "Not Found",
            "zh_CN": "未找到",
            "zh_TW": "未找到",
        },
        "path_prefix": {
            "en": "Path: {path}",
            "zh_CN": "路径：{path}",
            "zh_TW": "路徑：{path}",
        },
        "copy_path": {
            "en": "Copy Path",
            "zh_CN": "复制路径",
            "zh_TW": "複製路徑",
        },
        "copied": {
            "en": "Copied!",
            "zh_CN": "已复制！",
            "zh_TW": "已複製！",
        },
        "ffmpeg_hint": {
            "en": "Required for merging video and audio streams into MP4/MKV.",
            "zh_CN": "用于将视频与音频流合并为 MP4/MKV 格式。",
            "zh_TW": "用於將視訊與音訊串流整合為 MP4/MKV 格式。",
        },
        "check_for_updates": {
            "en": "Check for Updates",
            "zh_CN": "检查更新",
            "zh_TW": "檢查更新",
        },
        "checking_updates": {
            "en": "Checking...",
            "zh_CN": "正在检查...",
            "zh_TW": "正在檢查…",
        },
        "check_again": {
            "en": "Check Again",
            "zh_CN": "重新检查",
            "zh_TW": "重新檢查",
        },
        "retry": {
            "en": "Retry",
            "zh_CN": "重试",
            "zh_TW": "重試",
        },
        "check_failed": {
            "en": "Check Failed",
            "zh_CN": "检查失败",
            "zh_TW": "檢查失敗",
        },
        "update_available": {
            "en": "Update available",
            "zh_CN": "有可用更新",
            "zh_TW": "有可用更新",
        },
        "up_to_date": {
            "en": "Up to date",
            "zh_CN": "已是最新版本",
            "zh_TW": "已是最新版本",
        },
        "is_latest_ver_fmt": {
            "en": "v{ver} is the latest version.",
            "zh_CN": "v{ver} 已是最新版本。",
            "zh_TW": "v{ver} 已是最新版本。",
        },
        "update_ytdlp": {
            "en": "Update yt-dlp",
            "zh_CN": "更新 yt-dlp",
            "zh_TW": "更新 yt-dlp",
        },
        "auto_check_ytdlp": {
            "en": "Automatically check for yt-dlp updates",
            "zh_CN": "启动时自动检查 yt-dlp 更新",
            "zh_TW": "啟動時自動檢查 yt-dlp 更新",
        },
        "deno_title": {
            "en": "Deno (JS Runtime)",
            "zh_CN": "Deno (JS 运行环境)",
            "zh_TW": "Deno (JS 執行階段)",
        },
        "deno_hint": {
            "en": "JavaScript runtime required by yt-dlp to solve YouTube video challenges.",
            "zh_CN": "yt-dlp 用于执行 YouTube 视频挑战验证的 JavaScript 运行环境。",
            "zh_TW": "yt-dlp 用於求解 YouTube 影片挑戰驗證所需的 JavaScript 執行環境。",
        },
        "settings_auth": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "settings_browser_cookies": {
            "en": "Browser Cookies",
            "zh_CN": "浏览器 Cookie",
            "zh_TW": "瀏覽器 Cookies",
        },
        "settings_cookies_hint": {
            "en": "Use browser cookies if YouTube requires sign-in verification. Browsers should be closed during downloads.",
            "zh_CN": "若 YouTube 要求人机验证或登录，可调用本地浏览器 Cookie。下载时请关闭相应浏览器。",
            "zh_TW": "若 YouTube 要求人機驗證或登入，可讀取本機瀏覽器 Cookies。下載時請關閉相應瀏覽器。",
        },
        "settings_auth_bilibili": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_bilibili_hint": {
            "en": "Bilibili requires account cookies (SESSDATA) for high-definition 1080p+ streams or member-only videos. Select a Netscape-formatted cookies.txt file.",
            "zh_CN": "哔哩哔哩需要账号 Cookie (SESSDATA) 以获取 1080p+ 高清视频流或大会员专享内容。请选择 Netscape 格式的 cookies.txt 文件。",
            "zh_TW": "嗶哩嗶哩需要帳號 Cookie (SESSDATA) 以取得 1080p+ 高畫質串流或大會員專屬內容。請選取 Netscape 格式的 cookies.txt 檔案。",
        },
        "auth_bilibili_none_hint": {
            "en": "No authentication configured for Bilibili. Public videos will download at default standard resolution (up to 480p/720p without login).",
            "zh_CN": "哔哩哔哩未配置认证。公开视频将以默认标清/高清分辨率下载（未登录通常最高支持 480p/720p）。",
            "zh_TW": "嗶哩嗶哩未設定認證。公開影片將以預設標準畫質下載（未登入通常最高支援 480p/720p）。",
        },
        "auth_test_bilibili_tooltip": {
            "en": "Test if Bilibili cookies can be safely read from the selected file",
            "zh_CN": "测试所选文件是否包含有效的哔哩哔哩 Cookie",
            "zh_TW": "測試所選檔案是否包含有效的嗶哩嗶哩 Cookie",
        },
        "settings_auth_douyin": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_platform_label": {
            "en": "Platform",
            "zh_CN": "平台",
            "zh_TW": "平台",
        },
        "auth_douyin_hint": {
            "en": "Douyin requires fresh session cookies (s_v_web_id / ttwid) to extract videos and scan creator profiles. You can extract cookies from your browser or import a cookies.txt file.",
            "zh_CN": "抖音需要有效的会话 Cookie（s_v_web_id / ttwid）以解析视频和扫描创作者主页。您可以直接从浏览器读取 Cookie，或导入 cookies.txt 文件。",
            "zh_TW": "抖音需要有效的工作階段 Cookies（s_v_web_id / ttwid）以解析影片和掃描創作者主頁。您可以直接從瀏覽器讀取 Cookies，或匯入 cookies.txt 檔案。",
        },
        "auth_douyin_none_hint": {
            "en": "Authentication is disabled for Douyin. Note that public Douyin videos and profiles may require session cookies to extract.",
            "zh_CN": "已对抖音禁用身份验证。注意：抖音公开视频和创作者主页通常需要会话 Cookie 方可解析。",
            "zh_TW": "已對抖音停用身分驗證。注意：抖音公開影片和創作者主頁通常需要工作階段 Cookies 方可解析。",
        },
        "cookies_none": {
            "en": "No authentication (Default)",
            "zh_CN": "不使用认证 (默认)",
            "zh_TW": "不使用驗證 (預設)",
        },
        "auth_test_btn": {
            "en": "Test",
            "zh_CN": "测试登录",
            "zh_TW": "測試連線",
        },
        "auth_test_tooltip": {
            "en": "Test if YouTube cookies can be safely read from the selected browser",
            "zh_CN": "测试是否能安全读取所选浏览器的 YouTube Cookie",
            "zh_TW": "測試是否能安全讀取所選瀏覽器的 YouTube Cookies",
        },
        "auth_test_douyin_tooltip": {
            "en": "Test if Douyin cookies can be safely read from the selected source",
            "zh_CN": "测试是否能安全读取所选来源的抖音 Cookie",
            "zh_TW": "測試是否能安全讀取所選來源的抖音 Cookies",
        },
        "auth_test_title": {
            "en": "Authentication Test",
            "zh_CN": "登录测试",
            "zh_TW": "登入驗證測試",
        },
        "auth_disabled_msg": {
            "en": "Authentication is currently disabled. Please select a browser from the dropdown first.",
            "zh_CN": "当前已禁用身份验证。请先在下拉菜单中选择一个浏览器。",
            "zh_TW": "目前已停用身分驗證。請先在下拉選單中選擇瀏覽器。",
        },
        "auth_test_success_title": {
            "en": "Authentication Successful",
            "zh_CN": "登录测试成功",
            "zh_TW": "驗證測試成功",
        },
        "auth_test_success_msg": {
            "en": "Successfully detected {count} YouTube/Google authentication cookie(s) from {browser}.",
            "zh_CN": "成功从 {browser} 中检测到 {count} 个 YouTube/Google 验证 Cookie。",
            "zh_TW": "成功從 {browser} 中偵測到 {count} 個 YouTube/Google 驗證 Cookies。",
        },
        "auth_test_warn_title": {
            "en": "No Cookies Found",
            "zh_CN": "未检测到 Cookie",
            "zh_TW": "未偵測到 Cookies",
        },
        "auth_test_no_cookies_msg": {
            "en": "No YouTube or Google cookies were found in {browser}.\nPlease open {browser} and log in to YouTube first.",
            "zh_CN": "在 {browser} 中未找到 YouTube 或 Google Cookie。\n请先打开 {browser} 登录 YouTube。",
            "zh_TW": (
                "在 {browser} 中未找到 YouTube 或 Google Cookies。\\n"
                "請先開啟 {browser} 並登入 YouTube。"
            ),
        },
        "auth_test_error_title": {
            "en": "Authentication Error",
            "zh_CN": "登录测试失败",
            "zh_TW": "驗證測試失敗",
        },
        "auth_test_error_msg": {
            "en": "Failed to read cookies from {browser}:\n{error}\n\nPlease ensure {browser} is fully closed before testing.",
            "zh_CN": "读取 {browser} 的 Cookie 失败：\n{error}\n\n请确保在测试前已完全关闭 {browser}。",
            "zh_TW": (
                "讀取 {browser} 的 Cookies 失敗：\\n"
                "{error}\\n"
                "\\n"
                "請確保在測試前已完全關閉 {browser}。"
            ),
        },
        "cookies_chrome": {
            "en": "Google Chrome",
            "zh_CN": "Google Chrome",
            "zh_TW": "Google Chrome",
        },
        "cookies_edge": {
            "en": "Microsoft Edge",
            "zh_CN": "Microsoft Edge",
            "zh_TW": "Microsoft Edge",
        },
        "cookies_firefox": {
            "en": "Mozilla Firefox",
            "zh_CN": "Mozilla Firefox",
            "zh_TW": "Mozilla Firefox",
        },
        "cookies_brave": {
            "en": "Brave",
            "zh_CN": "Brave",
            "zh_TW": "Brave",
        },
        "cookies_opera": {
            "en": "Opera",
            "zh_CN": "Opera",
            "zh_TW": "Opera",
        },
        "cookies_vivaldi": {
            "en": "Vivaldi",
            "zh_CN": "Vivaldi",
            "zh_TW": "Vivaldi",
        },
        "auth_custom_cookie_file": {
            "en": "Custom Cookie File (cookies.txt)...",
            "zh_CN": "Cookie 文件 (cookies.txt)...",
            "zh_TW": "Cookie 檔案 (cookies.txt)…",
        },
        "auth_cookie_file_placeholder": {
            "en": "Select exported cookies.txt file...",
            "zh_CN": "选择导出的 cookies.txt 文件...",
            "zh_TW": "選取匯出的 cookies.txt 檔案…",
        },
        "auth_select_cookie_file": {
            "en": "Select Cookie File",
            "zh_CN": "选择 Cookie 文件",
            "zh_TW": "選取 Cookie 檔案",
        },
        "status_testing": {
            "en": "Testing...",
            "zh_CN": "测试中...",
            "zh_TW": "測試中…",
        },
        "auth_dialog_title": {
            "en": "YouTube Authentication Diagnostics",
            "zh_CN": "YouTube 登录诊断",
            "zh_TW": "YouTube 登入驗證診斷",
        },
        "auth_dialog_douyin_title": {
            "en": "Douyin Authentication Diagnostics",
            "zh_CN": "抖音身份验证诊断",
            "zh_TW": "抖音身分驗證診斷",
        },
        "auth_dialog_stage_heading": {
            "en": "STAGE & SOURCE DETAILS",
            "zh_CN": "阶段与来源信息",
            "zh_TW": "階段與來源資訊",
        },
        "auth_dialog_stage": {
            "en": "Verification Stage",
            "zh_CN": "验证阶段",
            "zh_TW": "驗證階段",
        },
        "auth_dialog_source": {
            "en": "Source",
            "zh_CN": "凭证来源",
            "zh_TW": "憑證來源",
        },
        "auth_dialog_reason_heading": {
            "en": "DIAGNOSTIC CAUSE",
            "zh_CN": "诊断原因",
            "zh_TW": "診斷原因",
        },
        "auth_dialog_action_heading": {
            "en": "SUGGESTED ACTION",
            "zh_CN": "建议操作",
            "zh_TW": "建議操作",
        },
        "auth_dialog_tech_heading": {
            "en": "SANITIZED TECHNICAL DETAILS",
            "zh_CN": "技术详情 (已脱敏)",
            "zh_TW": "技術詳情 (已脫敏)",
        },
        "auth_dialog_copy_btn": {
            "en": "Copy Diagnostic Details",
            "zh_CN": "复制诊断详情",
            "zh_TW": "複製診斷詳情",
        },
        "auth_dialog_close_btn": {
            "en": "Close",
            "zh_CN": "关闭",
            "zh_TW": "關閉",
        },
        "auth_method_label": {
            "en": "Authentication Method",
            "zh_CN": "登录方式",
            "zh_TW": "驗證方式",
        },
        "auth_method_none": {
            "en": "None",
            "zh_CN": "不使用",
            "zh_TW": "不使用",
        },
        "auth_method_browser": {
            "en": "Browser Cookies",
            "zh_CN": "浏览器 Cookie",
            "zh_TW": "瀏覽器 Cookies",
        },
        "auth_method_custom_file_radio": {
            "en": "Custom Cookie File",
            "zh_CN": "Cookie 文件",
            "zh_TW": "Cookie 檔案",
        },
        "auth_browser_label": {
            "en": "Browser:",
            "zh_CN": "浏览器：",
            "zh_TW": "瀏覽器：",
        },
        "auth_profile_label": {
            "en": "Profile:",
            "zh_CN": "配置文件：",
            "zh_TW": "設定檔：",
        },
        "auth_cookie_file_label": {
            "en": "Cookie File:",
            "zh_CN": "Cookie 文件：",
            "zh_TW": "Cookie 檔案：",
        },
        "auth_status_label": {
            "en": "Status:",
            "zh_CN": "状态：",
            "zh_TW": "狀態：",
        },
        "status_not_configured": {
            "en": "Not configured",
            "zh_CN": "未配置",
            "zh_TW": "未設定",
        },
        "status_not_tested": {
            "en": "Not tested",
            "zh_CN": "未测试",
            "zh_TW": "未測試",
        },
        "status_cookie_file_detected": {
            "en": "Cookie file detected",
            "zh_CN": "已检测到 Cookie 文件",
            "zh_TW": "已偵測到 Cookie 檔案",
        },
        "status_session_detected": {
            "en": "YouTube session detected",
            "zh_CN": "已检测到 YouTube 登录 Cookie",
            "zh_TW": "已偵測到 YouTube 登入工作階段",
        },
        "status_bilibili_session_detected": {
            "en": "Bilibili session detected",
            "zh_CN": "已检测到哔哩哔哩登录会话",
            "zh_TW": "已偵測到嗶哩嗶哩登入階段",
        },
        "status_douyin_session_detected": {
            "en": "Douyin session detected",
            "zh_CN": "已检测到抖音登录 Cookie",
            "zh_TW": "已偵測到抖音登入工作階段",
        },
        "status_decryption_failed": {
            "en": "Browser cookies could not be decrypted",
            "zh_CN": "无法解密浏览器 Cookie",
            "zh_TW": "無法解密瀏覽器 Cookies",
        },
        "status_invalid_cookie_file": {
            "en": "This does not appear to be a valid cookies.txt file.",
            "zh_CN": "这似乎不是有效的 cookies.txt 文件。",
            "zh_TW": "這似乎不是有效的 cookies.txt 檔案。",
        },
        "auth_none_hint": {
            "en": "Authentication is not configured. Public YouTube downloads will proceed without cookies.",
            "zh_CN": "未配置登录。公开的 YouTube 视频无需 Cookie 即可直接下载。",
            "zh_TW": "未設定登入驗證。公開的 YouTube 影片無需 Cookies 即可直接下載。",
        },
        "auth_clear_cookie_file": {
            "en": "Clear Cookie File",
            "zh_CN": "清除 Cookie 文件",
            "zh_TW": "清除 Cookie 檔案",
        },
        "auth_cookie_file_cleared": {
            "en": "Cookie file reference cleared.",
            "zh_CN": "已清除 Cookie 文件引用。",
            "zh_TW": "已清除 Cookie 檔案路徑參照。",
        },
        "auth_cookie_file_hint": {
            "en": "For authenticated downloads, export your browser cookies to a Netscape-format cookies.txt file and select it here.",
            "zh_CN": "需要登录验证时，请将浏览器 Cookie 导出为 Netscape 格式的 cookies.txt 文件，然后在此选择。",
            "zh_TW": "需要登入驗證時，請將瀏覽器 Cookies 匯出為 Netscape 格式的 cookies.txt 檔案，然後在此選取。",
        },
        "auth_fallback_notice_file": {
            "en": "Browser cookie extraction is temporarily unavailable in the interface. Switched to your configured Custom Cookie File.",
            "zh_CN": "界面中已暂停直接读取浏览器 Cookie。已切换至已配置的自定义 Cookie 文件。",
            "zh_TW": "介面中已暫停直接讀取瀏覽器 Cookies。已切換至已設定的自訂 Cookie 檔案。",
        },
        "auth_fallback_notice_none": {
            "en": "Browser cookie extraction is temporarily unavailable in the interface. Authentication is set to None. For authenticated downloads, export your browser cookies to a Netscape-format cookies.txt file and select Custom Cookie File.",
            "zh_CN": "界面中已暂停直接读取浏览器 Cookie。当前身份验证设为“不使用”。需要登录验证时，请将浏览器 Cookie 导出为 Netscape 格式的 cookies.txt 文件，然后选择自定义 Cookie 文件。",
            "zh_TW": "介面中已暫停直接讀取瀏覽器 Cookies。目前身分驗證設為「不使用」。需要登入驗證時，請將瀏覽器 Cookies 匯出為 Netscape 格式的 cookies.txt 檔案，然後選取自訂 Cookie 檔案。",
        },
        "auth_cookie_file_privacy_notice": {
            "en": "Cookie files contain sensitive YouTube session information. Keep this file private and do not share it publicly.",
            "zh_CN": "Cookie 文件包含敏感的 YouTube 登录会话信息。请妥善保管，切勿公开发布或分享。",
            "zh_TW": "Cookie 檔案包含敏感的 YouTube 登入工作階段資訊。請妥善保管，切勿公開催發布或分享。",
        },
        "auth_bilibili_privacy_notice": {
            "en": "Cookie files contain sensitive Bilibili session data (SESSDATA). Never share your cookie file.",
            "zh_CN": "Cookie 文件包含敏感的哔哩哔哩登录凭据 (SESSDATA)。请妥善保管，切勿公开发布或分享。",
            "zh_TW": "Cookie 檔案包含機密的嗶哩嗶哩登入憑證 (SESSDATA)。請妥善保管，切勿公開發布或分享。",
        },
        "auth_douyin_privacy_notice": {
            "en": "Cookie files contain sensitive Douyin session information. Keep this file private and do not share it publicly.",
            "zh_CN": "Cookie 文件包含敏感的抖音登录会话信息。请妥善保管，切勿公开发布或分享。",
            "zh_TW": "Cookie 檔案包含敏感的抖音登入工作階段資訊。請妥善保管，切勿公開發布或分享。",
        },
        "auth_diagnostics_heading": {
            "en": "AUTHENTICATION DIAGNOSTICS",
            "zh_CN": "登录诊断",
            "zh_TW": "登入驗證診斷",
        },
        "auth_last_test": {
            "en": "Last Test:",
            "zh_CN": "上次测试：",
            "zh_TW": "上次測試：",
        },
        "auth_view_diagnostic_details": {
            "en": "View Diagnostic Details",
            "zh_CN": "查看诊断详情",
            "zh_TW": "檢視診斷詳情",
        },
        "auth_switch_to_cookie_file": {
            "en": "Use Custom Cookie File",
            "zh_CN": "使用 Cookie 文件",
            "zh_TW": "使用 Cookie 檔案",
        },
        "auth_abe_title": {
            "en": "{browser} Cookie Access Unavailable",
            "zh_CN": "{browser} Cookie 访问不可用",
            "zh_TW": "{browser} Cookie 存取受阻",
        },
        "auth_abe_reason": {
            "en": "Channel Harvest could not decrypt the cookies stored by {browser}. This can happen with modern {browser} security protection (such as App-Bound Encryption). Your YouTube login may still be working normally in {browser}.",
            "zh_CN": "Channel Harvest 无法解密 {browser} 存储的 Cookie。这通常由现代 {browser} 安全保护机制 (如 App-Bound 绑定加密) 引起。您的 YouTube 登录在 {browser} 浏览器中可能仍然正常工作。",
            "zh_TW": "Channel Harvest 無法解密 {browser} 儲存的 Cookies。這通常由現代 {browser} 安全保護機制（如 App-Bound 加密）引起。您的 YouTube 登入在 {browser} 瀏覽器中可能仍然正常運作。",
        },
        "auth_abe_douyin_reason": {
            "en": "Channel Harvest could not decrypt the cookies stored by {browser}. This can happen with modern {browser} security protection (such as App-Bound Encryption). Your Douyin login may still be working normally in {browser}.",
            "zh_CN": "Channel Harvest 无法解密 {browser} 存储的 Cookie。这通常由现代 {browser} 安全保护机制 (如 App-Bound 绑定加密) 引起。您的抖音登录在 {browser} 浏览器中可能仍然正常工作。",
            "zh_TW": "Channel Harvest 無法解密 {browser} 儲存的 Cookies。這通常由現代 {browser} 安全保護機制（如 App-Bound 加密）引起。您的抖音登入在 {browser} 瀏覽器中可能仍然正常運作。",
        },
        "auth_abe_solution": {
            "en": "Recommended solution: Export your YouTube cookies as a cookies.txt file and select it under Custom Cookie File.",
            "zh_CN": "建议解决方案：使用浏览器扩展将您的 YouTube Cookie 导出为 cookies.txt 文件，并在“自定义 Cookie 文件”中选择它。",
            "zh_TW": "建議解決方式：使用瀏覽器擴充功能將您的 YouTube Cookies 匯出為 cookies.txt 檔案，並在「自訂 Cookie 檔案」中選取它。",
        },
        "auth_abe_douyin_solution": {
            "en": "Recommended solution: Export your Douyin cookies as a cookies.txt file and select it under Custom Cookie File.",
            "zh_CN": "建议解决方案：使用浏览器扩展将您的抖音 Cookie 导出为 cookies.txt 文件，并在“Cookie 文件”中选择它。",
            "zh_TW": "建議解決方式：使用瀏覽器擴充功能將您的抖音 Cookies 匯出為 cookies.txt 檔案，並在「Cookie 檔案」中選取它。",
        },
        "auth_select_cookie_file_btn": {
            "en": "Select Cookie File",
            "zh_CN": "选择 Cookie 文件",
            "zh_TW": "選取 Cookie 檔案",
        },
        "settings_data_dir": {
            "en": "DATA DIRECTORY",
            "zh_CN": "数据目录",
            "zh_TW": "資料目錄",
        },
        "data_dir_desc": {
            "en": "Application data & download archive:",
            "zh_CN": "应用程序数据与下载归档记录：",
            "zh_TW": "應用程式資料與下載封存記錄：",
        },
        "open_data_folder": {
            "en": "Open Data Folder",
            "zh_CN": "打开数据文件夹",
            "zh_TW": "開啟資料資料夾",
        },
        "open_data_folder_tooltip": {
            "en": "Open %APPDATA%\\ChannelHarvest in Windows File Explorer",
            "zh_CN": "在 Windows 资源管理器中打开 %APPDATA%\\ChannelHarvest",
            "zh_TW": "在 Windows 檔案總管中開啟 %APPDATA%\\ChannelHarvest",
        },
        "developed_by_fmt": {
            "en": "Developed by {developer}",
            "zh_CN": "开发者：{developer}",
            "zh_TW": "開發者：{developer}",
        },
        "ytdlp_busy_title": {
            "en": "Download in Progress",
            "zh_CN": "正在下载中",
            "zh_TW": "下載進行中",
        },
        "ytdlp_busy_msg": {
            "en": "yt-dlp cannot be updated while a download is running.\n\nPlease finish or cancel the current download first.",
            "zh_CN": "下载正在进行中，无法更新 yt-dlp。\n\n请先完成或取消当前下载。",
            "zh_TW": (
                "下載正在進行中，無法更新 yt-dlp。\\n"
                "\\n"
                "請先完成或取消目前下載。"
            ),
        },
        "ytdlp_update_prompt_title": {
            "en": "Update yt-dlp",
            "zh_CN": "更新 yt-dlp",
            "zh_TW": "更新 yt-dlp",
        },
        "ytdlp_update_prompt_msg": {
            "en": "A new yt-dlp version is available.\n\nCurrent version: v{current}\nLatest version: v{latest}\n\nWould you like to update?",
            "zh_CN": "发现新的 yt-dlp 版本。\n\n当前版本：v{current}\n最新版本：v{latest}\n\n是否立即更新？",
            "zh_TW": (
                "發現新的 yt-dlp 版本。\\n"
                "\\n"
                "目前版本：v{current}\\n"
                "最新版本：v{latest}\\n"
                "\\n"
                "是否立即更新？"
            ),
        },
        "updating": {
            "en": "Updating...",
            "zh_CN": "正在更新...",
            "zh_TW": "正在更新…",
        },
        "downloading_update": {
            "en": "Downloading and installing update...",
            "zh_CN": "正在下载并安装更新...",
            "zh_TW": "正在下載並安裝更新…",
        },
        "update_complete_title": {
            "en": "Update Complete",
            "zh_CN": "更新完成",
            "zh_TW": "更新完成",
        },
        "update_complete_msg": {
            "en": "yt-dlp has been updated to v{ver} successfully.",
            "zh_CN": "yt-dlp 已成功更新至 v{ver}。",
            "zh_TW": "yt-dlp 已成功更新至 v{ver}。",
        },
        "update_failed_title": {
            "en": "Update Failed",
            "zh_CN": "更新失败",
            "zh_TW": "更新失敗",
        },
        "update_failed_msg": {
            "en": "Could not update yt-dlp:\n{error}\n\nYour existing yt-dlp installation was preserved.",
            "zh_CN": "无法更新 yt-dlp：\n{error}\n\n已保留现有的 yt-dlp 安装。",
            "zh_TW": (
                "無法更新 yt-dlp：\\n"
                "{error}\\n"
                "\\n"
                "已保留現有的 yt-dlp 安裝。"
            ),
        },
        "retry_update": {
            "en": "Retry Update",
            "zh_CN": "重试更新",
            "zh_TW": "重試更新",
        },

        # Runtime Manager & Diagnostic Report
        "runtime_manager_title": {
            "en": "RUNTIME MANAGER",
            "zh_CN": "下载组件",
            "zh_TW": "元件管理",
        },
        "runtime_manager_sub": {
            "en": "Channel Harvest Runtime",
            "zh_CN": "Channel Harvest 下载组件",
            "zh_TW": "Channel Harvest 核心元件",
        },
        "th_component": {
            "en": "Component",
            "zh_CN": "组件",
            "zh_TW": "元件",
        },
        "th_current_version": {
            "en": "Current Version",
            "zh_CN": "当前版本",
            "zh_TW": "目前版本",
        },
        "th_status": {
            "en": "Status",
            "zh_CN": "状态",
            "zh_TW": "狀態",
        },
        "status_up_to_date": {
            "en": "Up to date",
            "zh_CN": "已是最新版本",
            "zh_TW": "已是最新版本",
        },
        "status_update_available": {
            "en": "Update available",
            "zh_CN": "有可用更新",
            "zh_TW": "有可用更新",
        },
        "status_not_installed": {
            "en": "Not Installed",
            "zh_CN": "未安装",
            "zh_TW": "未安裝",
        },
        "status_not_found": {
            "en": "Not Found",
            "zh_CN": "未找到",
            "zh_TW": "未找到",
        },
        "status_checking": {
            "en": "Checking...",
            "zh_CN": "正在检查...",
            "zh_TW": "正在檢查…",
        },
        "status_error": {
            "en": "Error",
            "zh_CN": "检查失败",
            "zh_TW": "檢查失敗",
        },
        "check_runtime_updates": {
            "en": "Check for Runtime Updates",
            "zh_CN": "检查组件更新",
            "zh_TW": "檢查元件更新",
        },
        "update_available_components": {
            "en": "Update Available Components",
            "zh_CN": "更新组件",
            "zh_TW": "更新元件",
        },
        "auto_check_runtime": {
            "en": "Automatically check for runtime updates",
            "zh_CN": "启动时自动检查组件更新",
            "zh_TW": "啟動時自動檢查元件更新",
        },
        "diagnostic_report_title": {
            "en": "DIAGNOSTIC REPORT",
            "zh_CN": "诊断报告",
            "zh_TW": "診斷報告",
        },
        "diagnostic_report_desc": {
            "en": "Create a diagnostic report containing system and runtime information.",
            "zh_CN": "生成包含系统与运行环境信息的诊断报告，用于故障排查。",
            "zh_TW": "產生包含系統與執行環境資訊的診斷報告，用於問題排查。",
        },
        "copy_diagnostic_info": {
            "en": "Copy Diagnostic Information",
            "zh_CN": "复制诊断信息",
            "zh_TW": "複製診斷資訊",
        },
        "copied_diagnostic_info": {
            "en": "Diagnostic information copied to clipboard.",
            "zh_CN": "诊断信息已复制到剪贴板。",
            "zh_TW": "診斷資訊已複製到剪貼簿。",
        },
        "open_log_folder": {
            "en": "Open Log Folder",
            "zh_CN": "打开日志文件夹",
            "zh_TW": "開啟記錄資料夾",
        },
        "open_log_folder_tooltip": {
            "en": "Open %APPDATA%\\ChannelHarvest\\logs in Windows File Explorer",
            "zh_CN": "在 Windows 资源管理器中打开日志文件夹",
            "zh_TW": "在 Windows 檔案總管中開啟記錄資料夾",
        },
        "runtime_busy_title": {
            "en": "Download in Progress",
            "zh_CN": "正在下载中",
            "zh_TW": "下載進行中",
        },
        "runtime_busy_msg": {
            "en": "Runtime components cannot be updated while downloads are running.\n\nPlease pause or wait for downloads to complete.",
            "zh_CN": "下载正在进行中，无法更新组件。\n\n请先暂停或等待下载完成。",
            "zh_TW": (
                "下載正在進行中，無法更新元件。\\n"
                "\\n"
                "請先暫停或等待下載完成。"
            ),
        },
        "runtime_update_confirm_title": {
            "en": "Update Runtime Components",
            "zh_CN": "更新下载组件",
            "zh_TW": "更新下載元件",
        },
        "runtime_update_confirm_msg": {
            "en": "The following components have updates available:\n\n{components}\n\nWould you like to install the updates now?",
            "zh_CN": "以下组件有可用更新：\n\n{components}\n\n是否立即下载并安装更新？",
            "zh_TW": (
                "以下元件有可用更新：\\n"
                "\\n"
                "{components}\\n"
                "\\n"
                "是否立即下載並安裝更新？"
            ),
        },
        "runtime_update_complete_title": {
            "en": "Runtime Update Complete",
            "zh_CN": "组件更新完成",
            "zh_TW": "元件更新完成",
        },
        "runtime_update_complete_msg": {
            "en": "Runtime components updated ({success} succeeded, {failed} failed).\n\nA restart of Channel Harvest is recommended for all changes to take effect.\n\nWould you like to restart now?",
            "zh_CN": "下载组件更新完毕（成功 {success} 个，失败 {failed} 个）。\n\n建议重启 Channel Harvest 使所有更新生效。\n\n是否立即重启软件？",
            "zh_TW": (
                "下載元件更新完畢（成功 {success} 個，失敗 {failed} 個）。\\n"
                "\\n"
                "建議重啟 Channel Harvest 使所有更新生效。\\n"
                "\\n"
                "是否立即重啟軟體？"
            ),
        },

        # Summary Dialog
        "summary_window_title": {
            "en": "Download Queue Complete",
            "zh_CN": "下载队列已完成",
            "zh_TW": "下載佇列完成",
        },
        "summary_window_title_cancelled": {
            "en": "Download Queue Cancelled",
            "zh_CN": "下载队列已取消",
            "zh_TW": "下載佇列已取消",
        },
        "summary_header_title": {
            "en": "Download Completed 🎉",
            "zh_CN": "下载完成 🎉",
            "zh_TW": "下載完成 🎉",
        },
        "summary_header_title_cancelled": {
            "en": "Download Cancelled",
            "zh_CN": "下载已取消",
            "zh_TW": "下載已取消",
        },
        "summary_batch_results": {
            "en": "Batch Results",
            "zh_CN": "批量下载统计",
            "zh_TW": "批次下載統計",
        },
        "summary_total": {
            "en": "Total Media in Queue:",
            "zh_CN": "队列媒体总数：",
            "zh_TW": "佇列媒體總數：",
        },
        "summary_completed": {
            "en": "Successfully Downloaded:",
            "zh_CN": "成功下载：",
            "zh_TW": "成功下載：",
        },
        "summary_downloaded": {
            "en": "Downloaded:",
            "zh_CN": "已下载：",
            "zh_TW": "已下載：",
        },
        "summary_skipped_media": {
            "en": "Skipped Media:",
            "zh_CN": "跳过媒体：",
            "zh_TW": "略過媒體：",
        },
        "summary_skipped": {
            "en": "Skipped (Already Exists):",
            "zh_CN": "已跳过（文件已存在）：",
            "zh_TW": "已略過 (檔案已存在)：",
        },
        "summary_skipped_private": {
            "en": "Skipped — Private Video:",
            "zh_CN": "跳过 — 私享视频：",
            "zh_TW": "略過 — 私人影片：",
        },
        "summary_skipped_unavailable": {
            "en": "Skipped — Unavailable Video:",
            "zh_CN": "跳过 — 无法访问视频：",
            "zh_TW": "略過 — 無法播放影片：",
        },
        "summary_failed": {
            "en": "Failed:",
            "zh_CN": "下载失败：",
            "zh_TW": "下載失敗：",
        },
        "summary_cancelled": {
            "en": "Cancelled:",
            "zh_CN": "已取消：",
            "zh_TW": "已取消：",
        },
        "summary_lyrics_not_found": {
            "en": "Lyrics Not Found:",
            "zh_CN": "未找到歌词：",
            "zh_TW": "未找到歌詞：",
        },
        "summary_lyrics_not_found_both": {
            "en": "Notice: Synchronized LRC lyrics could not be found for {count} song(s). Lyrics file export and audio tag embedding were skipped.",
            "zh_CN": "提示：未检索到 {count} 首歌曲的相应同步 LRC 歌词，已跳过歌词文件导出与音频标签嵌入。",
            "zh_TW": "提示：未檢索到 {count} 首歌曲的相應同步 LRC 歌詞，已略過歌詞檔案匯出與音訊標籤嵌入。",
        },
        "summary_lyrics_not_found_download": {
            "en": "Notice: Synchronized LRC lyrics could not be found for {count} song(s). Lyrics file export was skipped.",
            "zh_CN": "提示：未检索到 {count} 首歌曲的相应同步 LRC 歌词，已跳过歌词文件导出。",
            "zh_TW": "提示：未檢索到 {count} 首歌曲的相應同步 LRC 歌詞，已略過歌詞檔案匯出。",
        },
        "summary_lyrics_not_found_embed": {
            "en": "Notice: Synchronized LRC lyrics could not be found for {count} song(s). Audio tag embedding was skipped.",
            "zh_CN": "提示：未检索到 {count} 首歌曲的相应同步 LRC 歌词，已跳过音频标签嵌入。",
            "zh_TW": "提示：未檢索到 {count} 首歌曲的相應同步 LRC 歌詞，已略過音訊標籤嵌入。",
        },
        "summary_destination": {
            "en": "Destination:",
            "zh_CN": "保存文件夹：",
            "zh_TW": "儲存資料夾：",
        },
        "summary_open_folder": {
            "en": "📁 Open Download Folder",
            "zh_CN": "📁 打开下载文件夹",
            "zh_TW": "📁 開啟下載資料夾",
        },

        # Error Details Dialog
        "error_dialog_title": {
            "en": "Error Details",
            "zh_CN": "错误详情",
            "zh_TW": "錯誤詳情",
        },
        "error_dialog_video_label": {
            "en": "Target Video:",
            "zh_CN": "目标视频：",
            "zh_TW": "目標影片：",
        },
        "error_dialog_reason_heading": {
            "en": "Reason",
            "zh_CN": "失败原因",
            "zh_TW": "失敗原因",
        },
        "error_dialog_action_heading": {
            "en": "What you can do",
            "zh_CN": "建议操作",
            "zh_TW": "建議操作",
        },
        "error_dialog_tech_heading": {
            "en": "Technical Details",
            "zh_CN": "技术详情",
            "zh_TW": "技術詳情",
        },
        "error_dialog_copy_btn": {
            "en": "📋 Copy Error Details",
            "zh_CN": "📋 复制错误报告",
            "zh_TW": "📋 複製錯誤報告",
        },
        "error_dialog_copied": {
            "en": "✓ Copied to Clipboard!",
            "zh_CN": "✓ 已复制到剪贴板！",
            "zh_TW": "✓ 已複製到剪貼簿！",
        },

        # Additional Dialog & Logging Keys
        "theme_system": {
            "en": "System",
            "zh_CN": "跟随系统",
            "zh_TW": "跟隨系統",
        },
        "unknown_title": {
            "en": "Unknown Title",
            "zh_CN": "未知标题",
            "zh_TW": "未知標題",
        },
        "tech_category_label": {
            "en": "Category",
            "zh_CN": "分类",
            "zh_TW": "分類",
        },
        "tech_component_label": {
            "en": "Component",
            "zh_CN": "组件",
            "zh_TW": "元件",
        },
        "tech_stage_label": {
            "en": "Stage",
            "zh_CN": "阶段",
            "zh_TW": "階段",
        },
        "tech_http_status_label": {
            "en": "HTTP Status",
            "zh_CN": "HTTP 状态码",
            "zh_TW": "HTTP 狀態碼",
        },
        "no_tech_details": {
            "en": "No technical details available.",
            "zh_CN": "暂无技术详情",
            "zh_TW": "暫無技術詳情",
        },
        "could_not_open_dir_fmt": {
            "en": "Could not open directory:\n{error}",
            "zh_CN": "无法打开该文件夹：\n{error}",
            "zh_TW": (
                "無法開啟該資料夾：\\n"
                "{error}"
            ),
        },
        "could_not_restart_fmt": {
            "en": "Could not restart automatically: {error}",
            "zh_CN": "无法自动重启软件：{error}",
            "zh_TW": "無法自動重啟軟體：{error}",
        },
        "could_not_open_logs_fmt": {
            "en": "Could not open logs directory:\n{error}",
            "zh_CN": "无法打开日志文件夹：\n{error}",
            "zh_TW": (
                "無法開啟記錄資料夾：\\n"
                "{error}"
            ),
        },
        "cookie_yt_session_count_fmt": {
            "en": "({count} YouTube session cookies)",
            "zh_CN": "({count} 个 YouTube 登录 Cookie)",
            "zh_TW": "({count} 個 YouTube 登入 Cookies)",
        },
        "cookie_yt_count_no_session_fmt": {
            "en": "({count} YouTube cookies, no active session)",
            "zh_CN": "({count} 个 YouTube Cookie，无登录会话)",
            "zh_TW": "({count} 個 YouTube Cookies，無登入工作階段)",
        },
        "cookie_count_no_yt_fmt": {
            "en": "({count} cookies, no YouTube cookies)",
            "zh_CN": "({count} 个 Cookie，未包含 YouTube Cookie)",
            "zh_TW": "({count} 個 Cookies，未包含 YouTube Cookies)",
        },
        "cookie_dy_session_count_fmt": {
            "en": "({count} Douyin session cookies)",
            "zh_CN": "({count} 个抖音登录 Cookie)",
            "zh_TW": "({count} 個抖音登入 Cookies)",
        },
        "cookie_dy_count_no_session_fmt": {
            "en": "({count} Douyin cookies, no active session)",
            "zh_CN": "({count} 个抖音 Cookie，无登录会话)",
            "zh_TW": "({count} 個抖音 Cookies，無登入工作階段)",
        },
        "cookie_count_no_dy_fmt": {
            "en": "({count} cookies, no Douyin cookies)",
            "zh_CN": "({count} 个 Cookie，未包含抖音 Cookie)",
            "zh_TW": "({count} 個 Cookies，未包含抖音 Cookies)",
        },
        "auth_click_test_bilibili_hint": {
            "en": "Click 'Test' to run a Bilibili cookie verification.",
            "zh_CN": "点击“测试登录”以执行哔哩哔哩 Cookie 验证。",
            "zh_TW": "點擊「測試連線」以執行嗶哩嗶哩 Cookie 驗證。",
        },
        "auth_dialog_bilibili_title": {
            "en": "Bilibili Authentication Diagnostics",
            "zh_CN": "哔哩哔哩认证诊断",
            "zh_TW": "嗶哩嗶哩認證診斷",
        },
        "cookie_bili_session_count_fmt": {
            "en": "({count} Bilibili session cookies)",
            "zh_CN": "({count} 个哔哩哔哩登录 Cookie)",
            "zh_TW": "({count} 個嗶哩嗶哩登入 Cookies)",
        },
        "cookie_bili_count_no_session_fmt": {
            "en": "({count} Bilibili cookies, no active session)",
            "zh_CN": "({count} 个哔哩哔哩 Cookie，无登录会话)",
            "zh_TW": "({count} 個嗶哩嗶哩 Cookies，無登入工作階段)",
        },
        "cookie_count_bili_fmt": {
            "en": "({count} Bilibili cookies, session active)",
            "zh_CN": "({count} 个哔哩哔哩 Cookie，登录会话有效)",
            "zh_TW": "({count} 個嗶哩嗶哩 Cookies，登入階段有效)",
        },
        "cookie_count_no_bili_fmt": {
            "en": "({count} cookies, no Bilibili cookies)",
            "zh_CN": "({count} 个 Cookie，未包含哔哩哔哩 Cookie)",
            "zh_TW": "({count} 個 Cookies，未包含嗶哩嗶哩 Cookies)",
        },
        "auth_click_test_douyin_hint": {
            "en": "Click 'Test' to run a Douyin cookie verification.",
            "zh_CN": "点击“测试登录”即可验证抖音 Cookie 状态。",
            "zh_TW": "點擊「測試連線」即可驗證抖音 Cookie 狀態。",
        },
        "auth_click_test_verify_douyin_hint": {
            "en": "Click 'Test' to verify browser cookie extraction for Douyin.",
            "zh_CN": "点击“测试登录”以检测浏览器抖音 Cookie 读取状态。",
            "zh_TW": "點擊「測試連線」以偵測瀏覽器抖音 Cookie 讀取狀態。",
        },
        "auth_optional_hint": {
            "en": "Authentication is optional. Public YouTube videos download normally without configuration.",
            "zh_CN": "未配置登录。公开的 YouTube 视频无需登录即可直接下载。",
            "zh_TW": "未設定登入驗證。公開的 YouTube 影片無需登入即可直接下載。",
        },
        "auth_click_test_hint": {
            "en": "Click 'Test' to run a live YouTube verification.",
            "zh_CN": "点击“测试登录”即可验证与 YouTube 的连通状态。",
            "zh_TW": "點擊「測試連線」即可驗證與 YouTube 的連線狀態。",
        },
        "auth_no_test_yet": {
            "en": "No live authentication test has been run in this session.",
            "zh_CN": "当前会话尚未进行身份验证测试。",
            "zh_TW": "目前工作階段尚未進行身分驗證測試。",
        },
        "auth_click_test_verify_hint": {
            "en": "Click 'Test' to verify browser cookie extraction and YouTube connectivity.",
            "zh_CN": "点击“测试登录”以检测浏览器 Cookie 读取及 YouTube 连通性。",
            "zh_TW": "點擊「測試連線」以偵測瀏覽器 Cookie 讀取及 YouTube 連線能力。",
        },
        "auth_result_abe_header_fmt": {
            "en": "⚠️ {browser} Cookie Access Unavailable",
            "zh_CN": "⚠️ {browser} Cookie 无法读取",
            "zh_TW": "⚠️ {browser} Cookie 存取受阻",
        },
        "auth_result_not_configured": {
            "en": "ℹ Authentication Not Configured",
            "zh_CN": "ℹ 尚未配置身份验证",
            "zh_TW": "ℹ 尚未設定身分驗證",
        },
        "auth_result_success_fmt": {
            "en": "✓ {browser} Session Authenticated",
            "zh_CN": "✓ {browser} 登录会话验证成功",
            "zh_TW": "✓ {browser} 登入工作階段驗證成功",
        },
        "auth_result_success_no_session_fmt": {
            "en": "✓ {browser} Succeeded (No Login Session)",
            "zh_CN": "✓ {browser} 验证成功 (无登录会话)",
            "zh_TW": "✓ {browser} 驗證成功 (無登入工作階段)",
        },
        "auth_result_failed_fmt": {
            "en": "✕ {browser} Authentication Failed",
            "zh_CN": "✕ {browser} 身份验证失败",
            "zh_TW": "✕ {browser} 身分驗證失敗",
        },
        "auth_result_profile_fmt": {
            "en": " (Profile: {profile})",
            "zh_CN": " (配置文件：{profile})",
            "zh_TW": " (設定檔：{profile})",
        },
        "cookie_file_filter": {
            "en": "Cookie Files (*.txt);;All Files (*.*)",
            "zh_CN": "Cookie 文件 (*.txt);;所有文件 (*.*)",
            "zh_TW": "Cookie 檔案 (*.txt);;所有檔案 (*.*)",
        },
        "videos_found_filter_fmt": {
            "en": "{visible} of {total} media found",
            "zh_CN": "显示 {visible} / {total} 个媒体",
            "zh_TW": "顯示 {visible} / {total} 個媒體",
        },
        "one_video_found": {
            "en": "1 media found",
            "zh_CN": "共找到 1 个媒体",
            "zh_TW": "共找到 1 個媒體",
        },
        "tooltip_reason_label": {
            "en": "Reason:",
            "zh_CN": "失败原因：",
            "zh_TW": "失敗原因：",
        },
        "tooltip_action_label": {
            "en": "What you can do:",
            "zh_CN": "建议操作：",
            "zh_TW": "建議操作：",
        },
        "tooltip_details_hint": {
            "en": "(Double-click or right-click to view details)",
            "zh_CN": "(双击或右键查看详情)",
            "zh_TW": "(連按兩下或按右鍵檢視詳情)",
        },
        "download_failed_fallback": {
            "en": "Download failed",
            "zh_CN": "下载失败",
            "zh_TW": "下載失敗",
        },
        "video_id_prefix": {
            "en": "ID: {id}",
            "zh_CN": "视频 ID：{id}",
            "zh_TW": "影片 ID：{id}",
        },
        "url_prefix": {
            "en": "URL: {url}",
            "zh_CN": "链接：{url}",
            "zh_TW": "連結：{url}",
        },
        "youtube_id_prefix": {
            "en": "YouTube ID: {id}",
            "zh_CN": "YouTube ID：{id}",
            "zh_TW": "YouTube ID：{id}",
        },
        "log_ready": {
            "en": "[READY] Channel Harvest initialized.",
            "zh_CN": "[就绪] Channel Harvest 初始化完成。",
            "zh_TW": "[就緒] Channel Harvest 初始化完成。",
        },
        "log_archive_active_fmt": {
            "en": "[INFO] Download archive active: {name}",
            "zh_CN": "[信息] 下载归档记录已启用：{name}",
            "zh_TW": "[資訊] 下載封存記錄已啟用：{name}",
        },
        "log_ffmpeg_warning": {
            "en": "[WARNING] FFmpeg was not detected on this system. Audio and video stream merging requires FFmpeg.",
            "zh_CN": "[警告] 系统未检测到 FFmpeg。音视频流合并与提取需要 FFmpeg 支持。",
            "zh_TW": "[警告] 系統未偵測到 FFmpeg。視訊與音訊串流合併需要 FFmpeg 支援。",
        },
        "log_scan_finished_fmt": {
            "en": "[SUCCESS] Channel scan finished. {count} video(s) retrieved. Inspecting subtitle tracks in background...",
            "zh_CN": "[成功] 频道扫描完成，共获取 {count} 个视频。正在后台检测字幕可用性...",
            "zh_TW": "[成功] 頻道掃描完成，共取得 {count} 部影片。正在背景偵測字幕可用性…",
        },
        "log_subtitle_detection_done": {
            "en": "[INFO] Subtitle availability detection completed.",
            "zh_CN": "[信息] 字幕可用性检测已完成。",
            "zh_TW": "[資訊] 字幕可用性偵測已完成。",
        },
        "log_dest_set_fmt": {
            "en": "[CONFIG] Download destination set to: {path}",
            "zh_CN": "[配置] 下载保存目录已设为：{path}",
            "zh_TW": "[設定] 下載儲存目錄已設為：{path}",
        },
        "log_update_available_fmt": {
            "en": "[UPDATE] A new yt-dlp version is available: v{latest} (current: v{current}). Check Settings to update.",
            "zh_CN": "[更新] 发现新的 yt-dlp 版本：v{latest}（当前版本：v{current}）。请前往“设置”进行更新。",
            "zh_TW": "[更新] 發現新的 yt-dlp 版本：v{latest}（目前版本：v{current}）。請前往「設定」進行更新。",
        },
    
        # ---------------------------------------------------------------------
        # Facebook Integration Strings
        # ---------------------------------------------------------------------
        "platform_facebook": {
            "en": "Facebook",
            "zh_CN": "Facebook",
            "zh_TW": "Facebook",
        },
        "section_facebook_link": {
            "en": "FACEBOOK LINK",
            "zh_CN": "FACEBOOK 链接",
            "zh_TW": "FACEBOOK 連結",
        },
        "facebook_url_label": {
            "en": "Video or Reel URL",
            "zh_CN": "视频或 Reel 链接",
            "zh_TW": "影片或 Reel 連結",
        },
        "facebook_url_placeholder": {
            "en": "Paste Facebook video or Reel URL (e.g. https://www.facebook.com/watch/?v=... or /reel/...)",
            "zh_CN": "粘贴 Facebook 视频或 Reel 链接 (如 https://www.facebook.com/watch/?v=... 或 /reel/...)",
            "zh_TW": "貼上 Facebook 影片或 Reel 連結 (例如 https://www.facebook.com/watch/?v=... 或 /reel/...)",
        },
        "scan_facebook": {
            "en": "Scan Facebook",
            "zh_CN": "解析 Facebook",
            "zh_TW": "解析 Facebook",
        },
        "dialog_invalid_facebook_url_title": {
            "en": "Invalid Facebook Link",
            "zh_CN": "无效的 Facebook 链接",
            "zh_TW": "無效的 Facebook 連結",
        },
        "dialog_invalid_facebook_url_msg": {
            "en": "Please enter a valid Facebook video, Reel, or share URL, for example:\nhttps://www.facebook.com/watch/?v=1234567890",
            "zh_CN": "请输入有效的 Facebook 视频、Reel 或分享链接，例如：\nhttps://www.facebook.com/watch/?v=1234567890",
            "zh_TW": "請輸入有效的 Facebook 影片、Reel 或分享連結，例如：\nhttps://www.facebook.com/watch/?v=1234567890",
        },
        "empty_subtitle_facebook": {
            "en": "Facebook videos do not provide standard external SRT subtitles.",
            "zh_CN": "Facebook 视频不提供标准 SRT 独立字幕文件。",
            "zh_TW": "Facebook 影片不提供標準 SRT 獨立字幕檔案。",
        },
        "tooltip_facebook_no_subs": {
            "en": "Subtitles are not typically provided for Facebook videos",
            "zh_CN": "Facebook 视频通常不提供独立字幕",
            "zh_TW": "Facebook 影片通常不提供獨立字幕",
        },
        "tooltip_facebook_no_chapters": {
            "en": "Chapters are not supported for Facebook videos",
            "zh_CN": "Facebook 视频不支持章节",
            "zh_TW": "Facebook 影片不支援章節",
        },
        "settings_auth_facebook": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_facebook_hint": {
            "en": "Export cookies from your web browser using a Netscape cookies.txt extension while logged in to Facebook, then select the file above.",
            "zh_CN": "在已登录 Facebook 的浏览器中使用 Netscape cookies.txt 扩展导出 Cookie，并在上方选择该文件。",
            "zh_TW": "在已登入 Facebook 的瀏覽器中使用 Netscape cookies.txt 擴充功能匯出 Cookie，並於上方選取該檔案。",
        },
        "auth_facebook_none_hint": {
            "en": "No authentication is configured for Facebook. Public videos and accessible Reels will download without cookies.",
            "zh_CN": "未配置 Facebook 身份认证。公开视频和可访问的 Reel 将在无需 Cookie 的状态下直接下载。",
            "zh_TW": "未設定 Facebook 身分驗證。公開影片與可存取的 Reel 將在無需 Cookie 的狀態下直接下載。",
        },
        "auth_test_facebook_tooltip": {
            "en": "Verify the configured Facebook cookie file without downloading videos",
            "zh_CN": "验证配置的 Facebook Cookie 文件 (不下载视频)",
            "zh_TW": "驗證已設定的 Facebook Cookie 檔案 (不下載影片)",
        },
        "status_facebook_session_detected": {
            "en": "Facebook Session Detected",
            "zh_CN": "已检测到 Facebook 登录会话",
            "zh_TW": "已偵測到 Facebook 登入工作階段",
        },
        "auth_facebook_privacy_notice": {
            "en": "Privacy Guaranteed: Cookie contents, passwords, and tokens are never logged or exported.",
            "zh_CN": "隐私安全保证：Cookie 内容、密码与会话令牌绝不会被记录或导出。",
            "zh_TW": "隱私安全保證：Cookie 內容、密碼與工作階段權杖絕不會被記錄或匯出。",
        },
        "auth_click_test_facebook_hint": {
            "en": "Click 'Test' to verify your Facebook cookie file.",
            "zh_CN": "点击“测试”以验证您的 Facebook Cookie 文件。",
            "zh_TW": "按一下「測試」以驗證您的 Facebook Cookie 檔案。",
        },
        "auth_dialog_facebook_title": {
            "en": "Facebook Authentication Verification",
            "zh_CN": "Facebook 身份认证诊断",
            "zh_TW": "Facebook 身分驗證診斷",
        },
        # ---------------------------------------------------------------------
        # Instagram Integration Strings
        # ---------------------------------------------------------------------
        "platform_instagram": {
            "en": "Instagram",
            "zh_CN": "Instagram",
            "zh_TW": "Instagram",
        },
        "section_instagram_link": {
            "en": "INSTAGRAM LINK",
            "zh_CN": "INSTAGRAM 链接",
            "zh_TW": "INSTAGRAM 連結",
        },
        "instagram_url_label": {
            "en": "Reel, Post, or Profile URL",
            "zh_CN": "Reel、帖子或主页链接",
            "zh_TW": "Reel、貼文或首頁連結",
        },
        "instagram_url_placeholder": {
            "en": "Paste Instagram Reel, Post, or Profile URL (e.g. https://www.instagram.com/reel/... or /p/...)",
            "zh_CN": "粘贴 Instagram Reel、帖子或主页链接 (如 https://www.instagram.com/reel/... 或 /p/...)",
            "zh_TW": "貼上 Instagram Reel、貼文或首頁連結 (例如 https://www.instagram.com/reel/... 或 /p/...)",
        },
        "scan_instagram": {
            "en": "Scan Instagram",
            "zh_CN": "解析 Instagram",
            "zh_TW": "解析 Instagram",
        },
        "dialog_invalid_instagram_url_title": {
            "en": "Invalid Instagram Link",
            "zh_CN": "无效的 Instagram 链接",
            "zh_TW": "無效的 Instagram 連結",
        },
        "dialog_invalid_instagram_url_msg": {
            "en": "Please enter a valid Instagram Reel, post, Carousel, or profile URL, for example:\nhttps://www.instagram.com/reel/Chunk8-jurw/\nhttps://www.instagram.com/p/BQ0eAlwhDrw/",
            "zh_CN": "请输入有效的 Instagram Reel、视频帖子、轮播或主页链接，例如：\nhttps://www.instagram.com/reel/Chunk8-jurw/\nhttps://www.instagram.com/p/BQ0eAlwhDrw/",
            "zh_TW": "請輸入有效的 Instagram Reel、影片貼文、輪播或個人首頁連結，例如：\nhttps://www.instagram.com/reel/Chunk8-jurw/\nhttps://www.instagram.com/p/BQ0eAlwhDrw/",
        },
        "empty_subtitle_instagram": {
            "en": "Instagram media items do not provide standard external SRT subtitles.",
            "zh_CN": "Instagram 媒体内容不提供独立 SRT 字幕文件。",
            "zh_TW": "Instagram 媒體內容不提供獨立 SRT 字幕檔案。",
        },
        "tooltip_instagram_no_subs": {
            "en": "Subtitles are not provided for Instagram media",
            "zh_CN": "Instagram 媒体内容不提供独立字幕",
            "zh_TW": "Instagram 媒體內容不提供獨立字幕",
        },
        "tooltip_instagram_no_chapters": {
            "en": "Chapters are not supported for Instagram media",
            "zh_CN": "Instagram 媒体内容不支持章节",
            "zh_TW": "Instagram 媒體內容不支援章節",
        },
        "settings_auth_instagram": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_instagram_hint": {
            "en": "Export cookies from your web browser using a Netscape cookies.txt extension while logged in to Instagram, then select the file above.",
            "zh_CN": "在已登录 Instagram 的浏览器中使用 Netscape cookies.txt 扩展导出 Cookie，并在上方选择该文件。",
            "zh_TW": "在已登入 Instagram 的瀏覽器中使用 Netscape cookies.txt 擴充功能匯出 Cookie，並於上方選取該檔案。",
        },
        "auth_instagram_none_hint": {
            "en": "No authentication is configured for Instagram. Public Reels and posts will download without cookies when accessible.",
            "zh_CN": "未配置 Instagram 身份认证。公开的 Reel 和帖子将在无需 Cookie 的状态下直接下载。",
            "zh_TW": "未設定 Instagram 身分驗證。公開的 Reel 與貼文將在無需 Cookie 的狀態下直接下載。",
        },
        "auth_test_instagram_tooltip": {
            "en": "Verify the configured Instagram cookie file without downloading videos",
            "zh_CN": "验证配置的 Instagram Cookie 文件 (不下载视频)",
            "zh_TW": "驗證已設定的 Instagram Cookie 檔案 (不下載影片)",
        },
        "status_instagram_session_detected": {
            "en": "Instagram Session Detected",
            "zh_CN": "已检测到 Instagram 登录会话",
            "zh_TW": "已偵測到 Instagram 登入工作階段",
        },
        "auth_instagram_privacy_notice": {
            "en": "Privacy Guaranteed: Cookie contents, passwords, and tokens are never logged or exported.",
            "zh_CN": "隐私安全保证：Cookie 内容、密码与会话令牌绝不会被记录或导出。",
            "zh_TW": "隱私安全保證：Cookie 內容、密碼與工作階段權杖絕不會被記錄或匯出。",
        },
        "auth_click_test_instagram_hint": {
            "en": "Click 'Test' to verify your Instagram cookie file.",
            "zh_CN": "点击“测试”以验证您的 Instagram Cookie 文件。",
            "zh_TW": "按一下「測試」以驗證您的 Instagram Cookie 檔案。",
        },
        "auth_dialog_instagram_title": {
            "en": "Instagram Authentication Verification",
            "zh_CN": "Instagram 身份认证诊断",
            "zh_TW": "Instagram 身分驗證診斷",
        },
        # ---------------------------------------------------------------------
        # X (Twitter) Integration Strings
        # ---------------------------------------------------------------------
        "platform_x": {
            "en": "X (Twitter)",
            "zh_CN": "X (Twitter)",
            "zh_TW": "X (Twitter)",
        },
        "section_x_link": {
            "en": "X (TWITTER) LINK",
            "zh_CN": "X (TWITTER) 链接",
            "zh_TW": "X (TWITTER) 連結",
        },
        "x_url_label": {
            "en": "Post or Profile URL",
            "zh_CN": "帖子或主页链接",
            "zh_TW": "貼文或首頁連結",
        },
        "x_url_placeholder": {
            "en": "Paste X (Twitter) post or profile URL (e.g. https://x.com/username/status/...)",
            "zh_CN": "粘贴 X (Twitter) 帖子或主页链接 (如 https://x.com/username/status/...)",
            "zh_TW": "貼上 X (Twitter) 貼文或首頁連結 (例如 https://x.com/username/status/...)",
        },
        "scan_x": {
            "en": "Scan X (Twitter)",
            "zh_CN": "解析 X (Twitter)",
            "zh_TW": "解析 X (Twitter)",
        },
        "dialog_invalid_x_url_title": {
            "en": "Invalid X (Twitter) Link",
            "zh_CN": "无效的 X (Twitter) 链接",
            "zh_TW": "無效的 X (Twitter) 連結",
        },
        "dialog_invalid_x_url_msg": {
            "en": "Please enter a valid X (Twitter) post or profile URL, for example:\nhttps://x.com/username/status/1234567890123456789\nhttps://twitter.com/username/status/1234567890123456789",
            "zh_CN": "请输入有效的 X (Twitter) 帖子或主页链接，例如：\nhttps://x.com/username/status/1234567890123456789\nhttps://twitter.com/username/status/1234567890123456789",
            "zh_TW": "請輸入有效的 X (Twitter) 貼文或首頁連結，例如：\nhttps://x.com/username/status/1234567890123456789\nhttps://twitter.com/username/status/1234567890123456789",
        },
        "settings_auth_x": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_x_none_hint": {
            "en": "No authentication is configured for X (Twitter). Public posts and videos will download without cookies when accessible.",
            "zh_CN": "未配置 X (Twitter) 身份认证。公开的帖子和视频将在无需 Cookie 的状态下直接下载。",
            "zh_TW": "未設定 X (Twitter) 身分驗證。公開的貼文與影片將在無需 Cookie 的狀態下直接下載。",
        },
        "auth_x_hint": {
            "en": "Export cookies from your web browser using a Netscape cookies.txt extension while logged in to X (Twitter), then select the file above.",
            "zh_CN": "在已登录 X (Twitter) 的浏览器中使用 Netscape cookies.txt 扩展导出 Cookie，并在上方选择该文件。",
            "zh_TW": "在已登入 X (Twitter) 的瀏覽器中使用 Netscape cookies.txt 擴充功能匯出 Cookie，並於上方選取該檔案。",
        },
        "auth_x_privacy_notice": {
            "en": "Privacy Guaranteed: Cookie contents, passwords, and tokens are never logged or exported.",
            "zh_CN": "隐私安全保证：Cookie 内容、密码与会话令牌绝不会被记录或导出。",
            "zh_TW": "隱私安全保證：Cookie 內容、密碼與工作階段權杖絕不會被記錄或匯出。",
        },
        "auth_test_x_tooltip": {
            "en": "Verify the configured X (Twitter) cookie file without downloading videos",
            "zh_CN": "验证配置的 X (Twitter) Cookie 文件 (不下载视频)",
            "zh_TW": "驗證已設定的 X (Twitter) Cookie 檔案 (不下載影片)",
        },
        "auth_dialog_x_title": {
            "en": "X (Twitter) Authentication Verification",
            "zh_CN": "X (Twitter) 身份认证诊断",
            "zh_TW": "X (Twitter) 身分驗證診斷",
        },
        "auth_click_test_x_hint": {
            "en": "Click 'Test' to verify your X (Twitter) cookie file.",
            "zh_CN": "点击“测试”以验证您的 X (Twitter) Cookie 文件。",
            "zh_TW": "按一下「測試」以驗證您的 X (Twitter) Cookie 檔案。",
        },
        "status_x_session_detected": {
            "en": "X (Twitter) Session Detected",
            "zh_CN": "已检测到 X (Twitter) 登录会话",
            "zh_TW": "已偵測到 X (Twitter) 登入工作階段",
        },
        # ---------------------------------------------------------------------
        # TikTok Authentication Strings
        # ---------------------------------------------------------------------
        "settings_auth_tiktok": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_tiktok_hint": {
            "en": "Export cookies from your web browser using a Netscape cookies.txt extension while logged in to TikTok, then select the file above.",
            "zh_CN": "在已登录 TikTok 的浏览器中使用 Netscape cookies.txt 扩展导出 Cookie，并在上方选择该文件。",
            "zh_TW": "在已登入 TikTok 的瀏覽器中使用 Netscape cookies.txt 擴充功能匯出 Cookie，並於上方選取該檔案。",
        },
        "auth_tiktok_none_hint": {
            "en": "No authentication is configured for TikTok. Public videos and accessible creator profiles will download without cookies.",
            "zh_CN": "未配置 TikTok 身份认证。公开视频和可访问的创作者主页将在无需 Cookie 的状态下直接下载。",
            "zh_TW": "未設定 TikTok 身分驗證。公開影片與可存取的創作者首頁將在無需 Cookie 的狀態下直接下載。",
        },
        "auth_test_tiktok_tooltip": {
            "en": "Verify the configured TikTok cookie file without downloading videos",
            "zh_CN": "验证配置的 TikTok Cookie 文件 (不下载视频)",
            "zh_TW": "驗證已設定的 TikTok Cookie 檔案 (不下載影片)",
        },
        "status_tiktok_session_detected": {
            "en": "TikTok Session Detected",
            "zh_CN": "已检测到 TikTok 登录会话",
            "zh_TW": "已偵測到 TikTok 登入工作階段",
        },
        "auth_tiktok_privacy_notice": {
            "en": "Privacy Guaranteed: Cookie contents, passwords, and tokens are never logged or exported.",
            "zh_CN": "隐私安全保证：Cookie 内容、密码与会话令牌绝不会被记录或导出。",
            "zh_TW": "隱私安全保證：Cookie 內容、密碼與工作階段權杖絕不會被記錄或匯出。",
        },
        "auth_click_test_tiktok_hint": {
            "en": "Click 'Test' to verify your TikTok cookie file.",
            "zh_CN": "点击“测试”以验证您的 TikTok Cookie 文件。",
            "zh_TW": "按一下「測試」以驗證您的 TikTok Cookie 檔案。",
        },
        "auth_dialog_tiktok_title": {
            "en": "TikTok Authentication Verification",
            "zh_CN": "TikTok 身份认证诊断",
            "zh_TW": "TikTok 身分驗證診斷",
        },
        # ---------------------------------------------------------------------
        # All Platforms Authentication Strings
        # ---------------------------------------------------------------------
        "settings_auth_all": {
            "en": "AUTHENTICATION",
            "zh_CN": "身份验证",
            "zh_TW": "身分驗證",
        },
        "auth_all_hint": {
            "en": "Select an exported Netscape cookies.txt file containing cookies for your platforms. Channel Harvest will automatically use this cookie file across all supported platforms.",
            "zh_CN": "选择包含多个平台 Cookie 的 Netscape cookies.txt 文件。Channel Harvest 将自动在所有支持的平台上统一使用该文件进行连接。",
            "zh_TW": "選取包含多個平台 Cookie 的 Netscape cookies.txt 檔案。Channel Harvest 將自動在所有支援的平台上統一使用該檔案進行連線。",
        },
        "auth_all_none_hint": {
            "en": "No universal authentication is configured. Downloads will use individual platform settings or proceed publicly without cookies.",
            "zh_CN": "未配置全局统一身份认证。下载将遵循各平台的独立设置，或在无需 Cookie 的状态下直接下载公开内容。",
            "zh_TW": "未設定全域統一身分驗證。下載將遵循各平台的獨立設定，或在無需 Cookie 的狀態下直接下載公開內容。",
        },
        "auth_test_all_tooltip": {
            "en": "Verify the universal cookie file for all platforms without downloading media",
            "zh_CN": "验证配置的全局通用 Cookie 文件 (不下载媒体)",
            "zh_TW": "驗證已設定的全域通用 Cookie 檔案 (不下載媒體)",
        },
        "status_all_session_detected": {
            "en": "Universal Session Detected (All Platforms)",
            "zh_CN": "已检测到通用登录会话 (所有平台)",
            "zh_TW": "已偵測到通用登入工作階段 (所有平台)",
        },
        "auth_all_privacy_notice": {
            "en": "Privacy Guaranteed: Cookie contents, passwords, and tokens are never logged or exported.",
            "zh_CN": "隐私安全保证：Cookie 内容、密码与会话令牌绝不会被记录或导出。",
            "zh_TW": "隱私安全保證：Cookie 內容、密碼與工作階段權杖絕不會被記錄或匯出。",
        },
        "auth_click_test_all_hint": {
            "en": "Click 'Test' to verify your universal cookie file across platforms.",
            "zh_CN": "点击“测试”以验证您的全局通用 Cookie 文件跨平台有效性。",
            "zh_TW": "按一下「測試」以驗證您的全域通用 Cookie 檔案跨平台有效性。",
        },
        "auth_dialog_all_title": {
            "en": "All Platforms Authentication Verification",
            "zh_CN": "全平台统一身份认证诊断",
            "zh_TW": "全平台統一身分驗證診斷",
        },
        "tooltip_x_no_chapters": {
            "en": "Chapters are not supported for X (Twitter) media",
            "zh_CN": "X (Twitter) 媒体内容不支持章节",
            "zh_TW": "X (Twitter) 媒體內容不支援章節",
        },
        "tooltip_x_no_subs": {
            "en": "Subtitles are not typically provided for X (Twitter) media",
            "zh_CN": "X (Twitter) 媒体内容通常不提供独立字幕",
            "zh_TW": "X (Twitter) 媒體內容通常不提供獨立字幕",
        },
        "empty_subtitle_x": {
            "en": "X (Twitter) media items do not provide standard external SRT subtitles.",
            "zh_CN": "X (Twitter) 媒体内容不提供独立 SRT 字幕文件。",
            "zh_TW": "X (Twitter) 媒體內容不提供獨立 SRT 字幕檔案。",
        },
        # Availability & Skip Explanations
        "avail_msg_private": {
            "en": "Private video. Sign in if you've been granted access.",
            "zh_CN": "私密视频。如已获得权限，请在设置中配置有效登录状态。",
            "zh_TW": "私人影片。若已取得權限，請於設定中配置有效登入狀態。",
        },
        "avail_msg_deleted": {
            "en": "This video has been removed or deleted.",
            "zh_CN": "该视频已被删除或移除。",
            "zh_TW": "該影片已被刪除或移除。",
        },
        "avail_msg_region_restricted": {
            "en": "This video is not available in your geographic location.",
            "zh_CN": "该视频在您所在的地区不可用 (地区限制)。",
            "zh_TW": "該影片在您所在的地區無法播放 (地區限制)。",
        },
        "avail_msg_age_restricted": {
            "en": "Age-restricted video. Sign in to confirm your age.",
            "zh_CN": "年龄限制视频。需要登录以确认年龄。",
            "zh_TW": "年齡限制影片。需要登入以確認年齡。",
        },
        "avail_msg_auth_required": {
            "en": "Content requires authentication, membership, or VIP access.",
            "zh_CN": "该内容需要会员权限、充电专属或登录认证。",
            "zh_TW": "該內容需要會員權限、充電專屬或登入認證。",
        },
        "avail_msg_access_denied": {
            "en": "Access denied by platform.",
            "zh_CN": "平台拒绝访问。",
            "zh_TW": "平台拒絕存取。",
        },
        "avail_msg_unlisted": {
            "en": "Unlisted video. Accessible and downloadable via link.",
            "zh_CN": "不公开视频。可通过链接正常访问和下载。",
            "zh_TW": "不公開影片。可透過連結正常存取和下載。",
        },
        "avail_msg_upcoming": {
            "en": "Upcoming live stream or premiere is not yet downloadable.",
            "zh_CN": "未开始的首播或直播，目前无法下载。",
            "zh_TW": "未開始的首播或直播，目前無法下載。",
        },
        "avail_msg_unavailable": {
            "en": "Video is unavailable under current network conditions.",
            "zh_CN": "当前网络条件下视频不可用。",
            "zh_TW": "當前網路條件下影片無法播放。",
        },
        "avail_tooltip_disabled": {
            "en": "Inaccessible: {reason}",
            "zh_CN": "不可用：{reason}",
            "zh_TW": "無法播放：{reason}",
        },
        "status_inaccessible": {
            "en": "Inaccessible Video",
            "zh_CN": "不可用视频",
            "zh_TW": "無法播放影片",
        },
}

    # -------------------------------------------------------------------------
    # Canonical Value Translations (For Dropdowns & Badges)
    # -------------------------------------------------------------------------
    _MODE_LABELS = {
        DownloadMode.VIDEO_AND_AUDIO: {"en": "Video + Audio", "zh_CN": "视频 + 音频", "zh_TW": "影片 + 音訊"},
        DownloadMode.VIDEO_ONLY: {"en": "Video Only", "zh_CN": "仅视频", "zh_TW": "僅影片"},
        DownloadMode.AUDIO_ONLY: {"en": "Audio Only", "zh_CN": "仅音频", "zh_TW": "僅音訊"},
        DownloadMode.IMAGE_ONLY: {"en": "Image Only", "zh_CN": "仅图片", "zh_TW": "僅圖片"},
        DownloadMode.ASSETS_ONLY: {"en": "Assets Only", "zh_CN": "仅附加内容", "zh_TW": "僅附加內容"},
        "Subtitle Only": {"en": "Assets Only", "zh_CN": "仅附加内容", "zh_TW": "僅附加內容"},
    }

    _SUB_SOURCE_LABELS = {
        SubtitleSource.BEST_AVAILABLE: {"en": "Best Available", "zh_CN": "最佳可用", "zh_TW": "最佳可用"},
        SubtitleSource.OFFICIAL: {"en": "Official Only", "zh_CN": "官方字幕", "zh_TW": "官方字幕"},
        SubtitleSource.AUTO_GENERATED: {"en": "Auto-generated Only", "zh_CN": "自动生成字幕", "zh_TW": "自動產生字幕"},
    }

    _SUB_LANG_LABELS = {
        SubtitleLanguage.CHINESE: {"en": "Chinese (中文)", "zh_CN": "中文", "zh_TW": "中文"},
        SubtitleLanguage.ENGLISH: {"en": "English", "zh_CN": "英文", "zh_TW": "英文"},
        SubtitleLanguage.MALAY: {"en": "Malay (Bahasa Melayu)", "zh_CN": "马来文", "zh_TW": "馬來文"},
        SubtitleLanguage.JAPANESE: {"en": "Japanese (日本語)", "zh_CN": "日文", "zh_TW": "日文"},
        SubtitleLanguage.KOREAN: {"en": "Korean (한국어)", "zh_CN": "韩文", "zh_TW": "韓文"},
        SubtitleLanguage.ALL: {"en": "All Available Languages", "zh_CN": "全部语言", "zh_TW": "所有語言"},
    }

    _THUMB_FORMAT_LABELS = {
        ThumbnailFormat.JPG: {"en": "JPG", "zh_CN": "JPG", "zh_TW": "JPG"},
        ThumbnailFormat.PNG: {"en": "PNG", "zh_CN": "PNG", "zh_TW": "PNG"},
        ThumbnailFormat.WEBP: {"en": "WEBP", "zh_CN": "WEBP", "zh_TW": "WEBP"},
        ThumbnailFormat.ORIGINAL: {"en": "Original", "zh_CN": "原始格式", "zh_TW": "原始格式"},
    }

    _THEME_LABELS = {
        "System": {"en": "System", "zh_CN": "跟随系统", "zh_TW": "跟隨系統"},
        "Light": {"en": "Light", "zh_CN": "浅色模式", "zh_TW": "淺色模式"},
        "Dark": {"en": "Dark", "zh_CN": "深色模式", "zh_TW": "深色模式"},
    }

    _STATUS_LABELS = {
        # Availability States
        "AVAILABLE": {"en": "Available", "zh_CN": "可用", "zh_TW": "可用"},
        "Available": {"en": "Available", "zh_CN": "可用", "zh_TW": "可用"},
        "PRIVATE": {"en": "Private Video", "zh_CN": "私密视频", "zh_TW": "私人影片"},
        "Private Video": {"en": "Private Video", "zh_CN": "私密视频", "zh_TW": "私人影片"},
        "DELETED": {"en": "Deleted Video", "zh_CN": "已删除视频", "zh_TW": "已刪除影片"},
        "Deleted Video": {"en": "Deleted Video", "zh_CN": "已删除视频", "zh_TW": "已刪除影片"},
        "REGION_RESTRICTED": {"en": "Region Restricted", "zh_CN": "地区受限", "zh_TW": "地區限制"},
        "Region Restricted": {"en": "Region Restricted", "zh_CN": "地区受限", "zh_TW": "地區限制"},
        "AGE_RESTRICTED": {"en": "Age Restricted", "zh_CN": "年龄限制", "zh_TW": "年齡限制"},
        "Age Restricted": {"en": "Age Restricted", "zh_CN": "年龄限制", "zh_TW": "年齡限制"},
        "AUTH_REQUIRED": {"en": "Login Required", "zh_CN": "需要登录", "zh_TW": "需要登入"},
        "Login Required": {"en": "Login Required", "zh_CN": "需要登录", "zh_TW": "需要登入"},
        "ACCESS_DENIED": {"en": "Access Denied", "zh_CN": "访问被拒", "zh_TW": "存取被拒"},
        "Access Denied": {"en": "Access Denied", "zh_CN": "访问被拒", "zh_TW": "存取被拒"},
        "UNLISTED": {"en": "Unlisted", "zh_CN": "不公开列出", "zh_TW": "不公開列出"},
        "Unlisted": {"en": "Unlisted", "zh_CN": "不公开列出", "zh_TW": "不公開列出"},
        "NO_SUPPORTED_FORMAT": {"en": "No Supported Format", "zh_CN": "无支持格式", "zh_TW": "無支援格式"},
        "UNAVAILABLE": {"en": "Unavailable Video", "zh_CN": "视频不可用", "zh_TW": "影片無法播放"},
        "Unavailable Video": {"en": "Unavailable Video", "zh_CN": "视频不可用", "zh_TW": "影片無法播放"},
        "Upcoming Video": {"en": "Upcoming Video", "zh_CN": "未开播视频", "zh_TW": "未開播影片"},
        "TEMPORARY_ERROR": {"en": "Temporary Error", "zh_CN": "临时错误", "zh_TW": "暫時錯誤"},
        VideoStatus.WAITING: {"en": "Waiting", "zh_CN": "等待中", "zh_TW": "等待中"},
        VideoStatus.DOWNLOADING: {"en": "Downloading", "zh_CN": "下载中", "zh_TW": "下載中"},
        "Downloading (Video)": {"en": "Downloading (Video)", "zh_CN": "下载中 (视频)", "zh_TW": "下載中 (影片)"},
        "Downloading (Audio)": {"en": "Downloading (Audio)", "zh_CN": "下载中 (音频)", "zh_TW": "下載中 (音訊)"},
        "Downloading (Subtitles)": {"en": "Downloading (Subtitles)", "zh_CN": "下载中 (字幕)", "zh_TW": "下載中 (字幕)"},
        "Downloading (Thumbnail)": {"en": "Downloading (Thumbnail)", "zh_CN": "下载中 (封面)", "zh_TW": "下載中 (封面)"},
        "Downloading Assets": {"en": "Downloading Assets", "zh_CN": "下载素材中", "zh_TW": "下載素材中"},
        "Saving (Metadata)": {"en": "Saving (Metadata)", "zh_CN": "保存中 (元数据)", "zh_TW": "儲存中 (中繼資料)"},
        VideoStatus.PROCESSING: {"en": "Processing", "zh_CN": "处理中", "zh_TW": "處理中"},
        VideoStatus.COMPLETED: {"en": "Completed", "zh_CN": "已完成", "zh_TW": "已完成"},
        VideoStatus.SKIPPED: {"en": "Skipped", "zh_CN": "已跳过", "zh_TW": "已略過"},
        VideoStatus.FAILED: {"en": "Failed", "zh_CN": "失败", "zh_TW": "失敗"},
        VideoStatus.CANCELLED: {"en": "Cancelled", "zh_CN": "已取消", "zh_TW": "已取消"},
        "Bot Verification Required": {"en": "Bot Verification Required", "zh_CN": "需人机验证", "zh_TW": "需人機驗證"},
        "Rate Limited (429)": {"en": "Rate Limited (429)", "zh_CN": "被限流 (429)", "zh_TW": "請求受限 (429)"},
        "Private / Unavailable": {"en": "Private / Unavailable", "zh_CN": "私密/不可用", "zh_TW": "私人/無法播放"},
        # Concise Error Statuses
        "Failed — HTTP 403": {"en": "Failed — HTTP 403", "zh_CN": "失败 — HTTP 403", "zh_TW": "失敗 — HTTP 403"},
        "Failed — Rate limited": {"en": "Failed — Rate limited", "zh_CN": "失败 — 请求被限流", "zh_TW": "失敗 — 請求頻率受限"},
        "Failed — Rate limited (429)": {"en": "Failed — Rate limited (429)", "zh_CN": "失败 — Rate limited (429)", "zh_TW": "失敗 — 請求頻率受限 (429)"},
        "Failed — Bot verification": {"en": "Failed — Bot verification", "zh_CN": "失败 — 需人机验证", "zh_TW": "失敗 — 需人機驗證"},
        "Failed — Login required": {"en": "Failed — Login required", "zh_CN": "失败 — 需要登录", "zh_TW": "失敗 — 需要登入"},
        "Failed — Private video": {"en": "Failed — Private video", "zh_CN": "失败 — 私密视频", "zh_TW": "失敗 — 私人影片"},
        "Failed — Video unavailable": {"en": "Failed — Video unavailable", "zh_CN": "失败 — 视频不可用", "zh_TW": "失敗 — 影片無法播放"},
        "Failed — Region restricted": {"en": "Failed — Region restricted", "zh_CN": "失败 — 地区受限", "zh_TW": "失敗 — 地區限制"},
        "Failed — Age restricted": {"en": "Failed — Age restricted", "zh_CN": "失败 — 年龄限制", "zh_TW": "失敗 — 年齡限制"},
        "Failed — JS runtime error": {"en": "Failed — JS runtime error", "zh_CN": "失败 — JS运行时错误", "zh_TW": "失敗 — JS 執行階段錯誤"},
        "Failed — EJS error": {"en": "Failed — EJS error", "zh_CN": "失败 — EJS组件错误", "zh_TW": "失敗 — EJS 元件錯誤"},
        "Failed — PO Token error": {"en": "Failed — PO Token error", "zh_CN": "失败 — PO Token错误", "zh_TW": "失敗 — PO Token 錯誤"},
        "Failed — HTTP 404": {"en": "Failed — HTTP 404", "zh_CN": "失败 — HTTP 404", "zh_TW": "失敗 — HTTP 404"},
        "Failed — HTTP 429": {"en": "Failed — HTTP 429", "zh_CN": "失败 — HTTP 429", "zh_TW": "失敗 — HTTP 429"},
        "Failed — HTTP 500": {"en": "Failed — HTTP 500", "zh_CN": "失败 — HTTP 500", "zh_TW": "失敗 — HTTP 500"},
        "Failed — HTTP 502": {"en": "Failed — HTTP 502", "zh_CN": "失败 — HTTP 502", "zh_TW": "失敗 — HTTP 502"},
        "Failed — HTTP 503": {"en": "Failed — HTTP 503", "zh_CN": "失败 — HTTP 503", "zh_TW": "失敗 — HTTP 503"},
        "Failed — Format error": {"en": "Failed — Format error", "zh_CN": "失败 — 格式不支持", "zh_TW": "失敗 — 格式不支援"},
        "Failed — FFmpeg error": {"en": "Failed — FFmpeg error", "zh_CN": "失败 — FFmpeg转码错误", "zh_TW": "失敗 — FFmpeg 轉檔錯誤"},
        "Failed — Disk full": {"en": "Failed — Disk full", "zh_CN": "失败 — 磁盘空间不足", "zh_TW": "失敗 — 磁碟空間不足"},
        "Failed — Permission error": {"en": "Failed — Permission error", "zh_CN": "失败 — 权限不足", "zh_TW": "失敗 — 權限不足"},
        "Failed — File system error": {"en": "Failed — File system error", "zh_CN": "失败 — 文件系统错误", "zh_TW": "失敗 — 檔案系統錯誤"},
        "Failed — File locked": {"en": "Failed — File locked", "zh_CN": "失败 — 文件被锁定", "zh_TW": "失敗 — 檔案遭鎖定"},
        "Failed — Range error (416)": {"en": "Failed — Range error (416)", "zh_CN": "失败 — 请求范围异常 (416)", "zh_TW": "失敗 — 請求範圍異常 (416)"},
        "Failed — Network error": {"en": "Failed — Network error", "zh_CN": "失败 — 网络错误", "zh_TW": "失敗 — 網路錯誤"},
        "Failed — Timeout": {"en": "Failed — Timeout", "zh_CN": "失败 — 连接超时", "zh_TW": "失敗 — 連線逾時"},
        "Failed — Unknown error": {"en": "Failed — Unknown error", "zh_CN": "失败 — 未知错误", "zh_TW": "失敗 — 未知錯誤"},
    }

    _QUALITY_LABELS = {
        "Best Available": {"en": "Best Available", "zh_CN": "最高分辨率", "zh_TW": "最高解析度"},
    }

    _VIDEO_BITRATE_LABELS = {
        "Best Available": {"en": "Best Available", "zh_CN": "最高画质", "zh_TW": "最高畫質"},
    }

    _AUDIO_BITRATE_LABELS = {
        "Best Available": {"en": "Best Available", "zh_CN": "最高音质", "zh_TW": "最高音質"},
        # WAV PCM bit depths
        "16-bit PCM": {"en": "16-bit PCM", "zh_CN": "16位 PCM (CD音质)", "zh_TW": "16位元 PCM (CD音質)"},
        "24-bit PCM": {"en": "24-bit PCM", "zh_CN": "24位 PCM (录音室母带)", "zh_TW": "24位元 PCM (錄音室母帶)"},
        "32-bit Float": {"en": "32-bit Float", "zh_CN": "32位 浮点", "zh_TW": "32位元 浮點"},
        # FLAC compression levels & bit depths
        "Level 8 (Highest)": {"en": "Level 8 (Highest)", "zh_CN": "8级 (最高压缩)", "zh_TW": "8級 (最高壓縮)"},
        "Level 5 (Default)": {"en": "Level 5 (Default)", "zh_CN": "5级 (默认平衡)", "zh_TW": "5級 (預設平衡)"},
        "Level 0 (Fastest)": {"en": "Level 0 (Fastest)", "zh_CN": "0级 (最快无损)", "zh_TW": "0級 (最快無損)"},
        "24-bit": {"en": "24-bit Lossless", "zh_CN": "24位 无损", "zh_TW": "24位元 無損"},
        "16-bit": {"en": "16-bit Lossless", "zh_CN": "16位 无损", "zh_TW": "16位元 無損"},
    }

    _BITRATE_LABELS = _VIDEO_BITRATE_LABELS

    @classmethod
    def get_language(cls) -> str:
        """Returns the current language code ('en' or 'zh_CN')."""
        return cls._current_language

    @classmethod
    def set_language(cls, lang: str) -> None:
        """
        Sets the active language and notifies all registered listeners.
        """
        if lang not in (cls.LANG_EN, cls.LANG_ZH, cls.LANG_ZH_TW):
            lang = cls.LANG_EN
        if cls._current_language != lang:
            cls._current_language = lang
            cls._notify_listeners()

    @classmethod
    def is_chinese(cls) -> bool:
        """Returns True if the current language is Simplified or Traditional Chinese."""
        return cls._current_language in (cls.LANG_ZH, cls.LANG_ZH_TW)
    @classmethod
    def is_simplified_chinese(cls) -> bool:
        """Returns True if the current language is Simplified Chinese."""
        return cls._current_language == cls.LANG_ZH

    @classmethod
    def is_traditional_chinese(cls) -> bool:
        """Returns True if the current language is Traditional Chinese (Taiwan)."""
        return cls._current_language == cls.LANG_ZH_TW
    @classmethod
    def register_listener(cls, callback: Callable[[str], None]) -> None:
        """Registers a listener to be notified when language changes."""
        if callback not in cls._listeners:
            cls._listeners.append(callback)

    @classmethod
    def unregister_listener(cls, callback: Callable[[str], None]) -> None:
        """Unregisters a listener callback."""
        if callback in cls._listeners:
            cls._listeners.remove(callback)

    @classmethod
    def _notify_listeners(cls) -> None:
        """Calls all registered listeners with the new language code."""
        dead_listeners = []
        for cb in list(cls._listeners):
            try:
                cb(cls._current_language)
            except (RuntimeError, Exception) as e:
                err_str = str(e).lower()
                if "already deleted" in err_str or "wrapped c/c++ object" in err_str:
                    dead_listeners.append(cb)
                else:
                    print(f"[I18n] Error notifying listener: {e}")
        for dead in dead_listeners:
            if dead in cls._listeners:
                cls._listeners.remove(dead)

        # -------------------------------------------------------------------------
    # Profile Media Archive & gallery-dl Integration Strings
    # -------------------------------------------------------------------------
    _ARCHIVE_STRINGS: Dict[str, Dict[str, str]] = {
        "section_available_media": {
            "en": "AVAILABLE MEDIA",
            "zh_CN": "可用媒体",
            "zh_TW": "可用媒體",
        },
        "header_media_title": {
            "en": "Media Title",
            "zh_CN": "媒体标题",
            "zh_TW": "媒體標題",
        },
        "header_media_type": {
            "en": "Media Type",
            "zh_CN": "媒体类型",
            "zh_TW": "媒體類型",
        },
        "header_media_id": {
            "en": "Media ID",
            "zh_CN": "媒体 ID",
            "zh_TW": "媒體 ID",
        },
        "media_type_photo": {
            "en": "Photo",
            "zh_CN": "照片",
            "zh_TW": "相片",
        },
        "media_type_reel": {
            "en": "Reel",
            "zh_CN": "Reel",
            "zh_TW": "Reel",
        },
        "media_type_unknown": {
            "en": "Unknown",
            "zh_CN": "未知",
            "zh_TW": "未知",
        },
        "counter_media_found": {
            "en": "{count} media found",
            "zh_CN": "已发现 {count} 个媒体",
            "zh_TW": "已發現 {count} 個媒體",
        },
        "counter_media_selected": {
            "en": "{count} selected",
            "zh_CN": "已选择 {count} 个",
            "zh_TW": "已選取 {count} 個",
        },
        "empty_title_media": {
            "en": "No media available",
            "zh_CN": "暂无可用媒体",
            "zh_TW": "暫無可用媒體",
        },
        "empty_subtitle_media": {
            "en": "Scan a channel, profile, or playlist to load media.",
            "zh_CN": "扫描频道、个人主页或播放列表以加载媒体。",
            "zh_TW": "掃描頻道、個人主頁或播放清單以載入媒體。",
        },
        "search_placeholder_media": {
            "en": "🔍 Search media...",
            "zh_CN": "🔍 搜索媒体...",
            "zh_TW": "🔍 搜尋媒體...",
        },
        "tooltip_clear_media": {
            "en": "Clear all media from the table",
            "zh_CN": "清空表格中的所有媒体",
            "zh_TW": "清空表格中的所有媒體",
        },
        "sub_section_image_options": {
            "en": "IMAGE OPTIONS",
            "zh_CN": "图片选项",
            "zh_TW": "圖片選項",
        },
        "form_image_format": {
            "en": "Image Format",
            "zh_CN": "图片格式",
            "zh_TW": "圖片格式",
        },
        "form_image_quality": {
            "en": "Image Quality",
            "zh_CN": "图片质量",
            "zh_TW": "圖片品質",
        },
        "cb_preserve_original_images": {
            "en": "Preserve Original Images",
            "zh_CN": "保留原始图片",
            "zh_TW": "保留原始圖片",
        },
        "cb_skip_downloaded_media": {
            "en": "Skip downloaded media",
            "zh_CN": "跳过已下载媒体",
            "zh_TW": "略過已下載媒體",
        },
        "cb_create_individual_media_folders": {
            "en": "Create individual media folder",
            "zh_CN": "为每个媒体创建独立文件夹",
            "zh_TW": "為每個媒體建立獨立資料夾",
        },
        "cb_add_number_to_filename": {
            "en": "Add Sequence No. to filename",
            "zh_CN": "文件名添加序号",
            "zh_TW": "檔案名稱添加編號",
        },
        "cb_add_number": {
            "en": "Add Sequence No. to filename",
            "zh_CN": "文件名添加序号",
            "zh_TW": "檔案名稱添加編號",
        },
        "cb_create_unique_filename": {
            "en": "Create custom folder name",
            "zh_CN": "创建自定义文件夹",
            "zh_TW": "建立自訂資料夾",
        },
        "tooltip_create_unique_filename": {
            "en": "Save downloaded media into a custom user-specified folder. When enabled, channel subfolders are disabled.",
            "zh_CN": "将下载的媒体保存到用户指定的自定义文件夹中。启用后，将自动禁用频道子文件夹。",
            "zh_TW": "將下載的媒體儲存至使用者指定的自訂資料夾中。啟用後，將自動停用頻道子資料夾。",
        },
        "placeholder_unique_folder_name": {
            "en": "Enter custom folder name...",
            "zh_CN": "输入自定义文件夹名称...",
            "zh_TW": "輸入自訂資料夾名稱...",
        },
        "tooltip_disabled_in_image_only_mode": {
            "en": "Cannot be selected in Image Only mode",
            "zh_CN": "仅图片模式下不可选",
            "zh_TW": "僅圖片模式下不可選",
        },
        "tooltip_add_number_to_filename": {
            "en": "Prefix downloaded media filenames with their scan order number (e.g. 01_Title, supporting up to 6 digits)",
            "zh_CN": "根据扫描结果顺序在下载的媒体文件名前添加序号 (如 01_标题，最大支持6位数)",
            "zh_TW": "根據掃描結果順序在下載的媒體檔案名稱前添加編號 (如 01_標題，最大支援6位數)",
        },
        "cb_include_media_id_in_filename": {
            "en": "Include Media ID in filename",
            "zh_CN": "文件名中包含媒体 ID",
            "zh_TW": "檔案名稱包含媒體 ID",
        },
        "tooltip_preserve_original_images": {
            "en": "Always preserve the original downloaded image files.",
            "zh_CN": "始终保留下载的原始图片文件。",
            "zh_TW": "一律保留下載的原始圖片檔案。",
        },
        "tooltip_skip_downloaded_media": {
            "en": "Skip downloading media files that already exist in the target folder.",
            "zh_CN": "跳过目标文件夹中已存在的媒体文件。",
            "zh_TW": "略過目標資料夾中已存在的媒體檔案。",
        },
        "tooltip_create_individual_media_folders": {
            "en": "Store each media item's files in its own folder.",
            "zh_CN": "将每个媒体项目的文件存储在专属文件夹中。",
            "zh_TW": "將每個媒體項目的檔案儲存在專屬資料夾中。",
        },
        "tooltip_include_media_id_in_filename": {
            "en": "Include unique Media ID in downloaded filenames.",
            "zh_CN": "在下载的文件名中包含唯一的媒体 ID。",
            "zh_TW": "在下載的檔案名稱中包含唯一的媒體 ID。",
        },
        "image_fmt_original": {
            "en": "Keep Original",
            "zh_CN": "保持原始格式",
            "zh_TW": "保持原始格式",
        },
        "image_quality_100": {
            "en": "100% (Best)",
            "zh_CN": "100% (最佳)",
            "zh_TW": "100% (最佳)",
        },
        "image_quality_90": {
            "en": "90% (High)",
            "zh_CN": "90% (高质量)",
            "zh_TW": "90% (高品質)",
        },
        "image_quality_80": {
            "en": "80% (Medium)",
            "zh_CN": "80% (标准)",
            "zh_TW": "80% (標準)",
        },
        "image_quality_70": {
            "en": "70% (Compact)",
            "zh_CN": "70% (较小)",
            "zh_TW": "70% (較小)",
        },
        "profile_media_archive": {
            "en": "Profile Media Archive",
            "zh_CN": "个人主页媒体归档",
            "zh_TW": "個人主頁媒體封存",
        },
        "scan_completeness_complete": {
            "en": "Complete Archive",
            "zh_CN": "完整归档",
            "zh_TW": "完整封存",
        },
        "scan_completeness_partial": {
            "en": "Partial Scan",
            "zh_CN": "部分扫描",
            "zh_TW": "部分掃描",
        },
        "scan_completeness_interrupted": {
            "en": "Scan Interrupted",
            "zh_CN": "扫描已中断",
            "zh_TW": "掃描已中斷",
        },
        "scan_completeness_failed": {
            "en": "Scan Failed",
            "zh_CN": "扫描失败",
            "zh_TW": "掃描失敗",
        },
        "engine_gallerydl": {
            "en": "gallery-dl (Images & Albums)",
            "zh_CN": "gallery-dl (图片与相册)",
            "zh_TW": "gallery-dl (圖片與相簿)",
        },
        "engine_ytdlp": {
            "en": "yt-dlp (Videos & Reels)",
            "zh_CN": "yt-dlp (视频与Reels)",
            "zh_TW": "yt-dlp (影片與Reels)",
        },
        "media_type_image": {
            "en": "Photo / Image",
            "zh_CN": "照片 / 图片",
            "zh_TW": "相片 / 圖片",
        },
        "media_type_video": {
            "en": "Video",
            "zh_CN": "视频",
            "zh_TW": "影片",
        },
        "media_type_carousel": {
            "en": "Carousel / Album",
            "zh_CN": "轮播 / 相册",
            "zh_TW": "輪播 / 相簿",
        },
        "gallerydl_status_ready": {
            "en": "gallery-dl Ready",
            "zh_CN": "gallery-dl 就绪",
            "zh_TW": "gallery-dl 就緒",
        },
        "gallerydl_status_missing": {
            "en": "gallery-dl Missing",
            "zh_CN": "未找到 gallery-dl",
            "zh_TW": "未找到 gallery-dl",
        },
        "archive_report_saved": {
            "en": "Scan report saved to disk",
            "zh_CN": "归档扫描报告已保存至磁盘",
            "zh_TW": "封存掃描報告已儲存至磁碟",
        },
    }
    
    
    @classmethod
    def get_media_type_label(cls, media_type: str) -> str:
        m = (media_type or "").upper()
        if m in ("PHOTO", "IMAGE"):
            return cls.tr("media_type_photo")
        if m == "REEL":
            return cls.tr("media_type_reel")
        if m == "VIDEO":
            return cls.tr("media_type_video")
        return cls.tr("media_type_unknown")
    @classmethod
    def get_image_format_label(cls, fmt: str) -> str:
        if fmt in ("Original", "Keep Original"):
            return cls.tr("image_fmt_original")
        return fmt
    @classmethod
    def get_image_quality_label(cls, q: str) -> str:
        if "100" in q:
            return cls.tr("image_quality_100")
        if "90" in q:
            return cls.tr("image_quality_90")
        if "80" in q:
            return cls.tr("image_quality_80")
        if "70" in q:
            return cls.tr("image_quality_70")
        return q
    @classmethod
    def tr(cls, key: str, **kwargs: Any) -> str:
        """
        Translates a string key into the current language, applying formatting kwargs if provided.
        Falls back to English or the key itself if not found.
        """
        lang = cls._current_language
        entry = cls._STRINGS.get(key) or cls._ARCHIVE_STRINGS.get(key)
        if entry:
            text = entry.get(lang) or entry.get(cls.LANG_EN, key)
        else:
            text = key

        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    # -------------------------------------------------------------------------
    # Enum / Dropdown Value Helper Functions
    # -------------------------------------------------------------------------
    @classmethod
    def get_mode_label(cls, canonical_mode: str) -> str:
        entry = cls._MODE_LABELS.get(canonical_mode, {})
        return entry.get(cls._current_language, canonical_mode)

    @classmethod
    def get_sub_source_label(cls, canonical_source: str) -> str:
        entry = cls._SUB_SOURCE_LABELS.get(canonical_source, {})
        return entry.get(cls._current_language, canonical_source)

    @classmethod
    def get_sub_lang_label(cls, canonical_lang: str) -> str:
        entry = cls._SUB_LANG_LABELS.get(canonical_lang, {})
        return entry.get(cls._current_language, canonical_lang)

    @classmethod
    def get_thumb_format_label(cls, canonical_format: str) -> str:
        entry = cls._THUMB_FORMAT_LABELS.get(canonical_format, {})
        return entry.get(cls._current_language, canonical_format)

    @classmethod
    def get_theme_label(cls, canonical_theme: str) -> str:
        entry = cls._THEME_LABELS.get(canonical_theme, {})
        return entry.get(cls._current_language, canonical_theme)

    @classmethod
    def get_status_label(cls, canonical_status: Any) -> str:
        entry = cls._STATUS_LABELS.get(canonical_status, {})
        fallback = getattr(canonical_status, "value", str(canonical_status))
        if entry:
            return entry.get(cls._current_language, fallback)
        if cls.is_traditional_chinese() and isinstance(fallback, str) and fallback.startswith("Failed — "):
            return "失敗 — " + fallback[len("Failed — "):]
        if cls.is_chinese() and isinstance(fallback, str) and fallback.startswith("Failed — "):
            return "失败 — " + fallback[len("Failed — "):]
        return fallback

    @classmethod
    def get_quality_label(cls, canonical_quality: str) -> str:
        if canonical_quality == "Best Available":
            return cls._QUALITY_LABELS["Best Available"].get(cls._current_language, "Best Available")
        return canonical_quality

    @classmethod
    def get_video_bitrate_label(cls, canonical_bitrate: str) -> str:
        if canonical_bitrate == "Best Available":
            return cls._VIDEO_BITRATE_LABELS["Best Available"].get(cls._current_language, "Best Available")
        return canonical_bitrate

    @classmethod
    def get_audio_bitrate_label(cls, canonical_bitrate: str) -> str:
        if canonical_bitrate in cls._AUDIO_BITRATE_LABELS:
            return cls._AUDIO_BITRATE_LABELS[canonical_bitrate].get(cls._current_language, canonical_bitrate)
        return canonical_bitrate

    @classmethod
    def get_bitrate_label(cls, canonical_bitrate: str) -> str:
        return cls.get_video_bitrate_label(canonical_bitrate)


def tr(key: str, **kwargs: Any) -> str:
    """Convenience shortcut function for I18nManager.tr()."""
    return I18nManager.tr(key, **kwargs)
