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

    # Supported language choices for UI dropdown
    LANGUAGES = [
        ("English", LANG_EN),
        ("简体中文", LANG_ZH),
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
        },
        "app_subtitle": {
            "en": "Harvest your channel. Keep every video.",
            "zh_CN": "批量归档频道视频，完整留存每一份精彩。",
        },
        "settings_tooltip": {
            "en": "Settings",
            "zh_CN": "设置",
        },
        "close": {
            "en": "Close",
            "zh_CN": "关闭",
        },
        "error": {
            "en": "Error",
            "zh_CN": "错误",
        },

        # Section 1: YouTube Link
        "section_youtube_link": {
            "en": "YOUTUBE LINK",
            "zh_CN": "YOUTUBE 链接",
        },
        "channel_url_label": {
            "en": "YouTube Channel / Playlist URL",
            "zh_CN": "YouTube 频道或播放列表链接",
        },
        "channel_url_placeholder": {
            "en": "https://www.youtube.com/@channel or playlist URL",
            "zh_CN": "https://www.youtube.com/@频道名 或播放列表链接",
        },
        "scan_channel": {
            "en": "Scan Channel",
            "zh_CN": "扫描频道",
        },
        "scanning": {
            "en": "Scanning...",
            "zh_CN": "扫描中...",
        },

        # Section 2: Available Videos
        "section_available_videos": {
            "en": "AVAILABLE VIDEOS",
            "zh_CN": "视频列表",
        },
        "header_select": {
            "en": "",
            "zh_CN": "",
        },
        "header_index": {
            "en": "#",
            "zh_CN": "#",
        },
        "header_title": {
            "en": "Video Title",
            "zh_CN": "视频标题",
        },
        "header_duration": {
            "en": "Duration",
            "zh_CN": "时长",
        },
        "header_subtitle": {
            "en": "Subtitle",
            "zh_CN": "字幕",
        },
        "header_video_id": {
            "en": "Video ID",
            "zh_CN": "视频 ID",
        },
        "header_status": {
            "en": "Status",
            "zh_CN": "状态",
        },
        "subtitle_yes": {
            "en": "Yes",
            "zh_CN": "有",
        },
        "subtitle_no": {
            "en": "No",
            "zh_CN": "无",
        },
        "subtitle_checking": {
            "en": "Checking...",
            "zh_CN": "检测中...",
        },
        "videos_found_fmt": {
            "en": "{found} videos found",
            "zh_CN": "找到 {found} 个视频",
        },
        "videos_selected_fmt": {
            "en": "{selected} selected",
            "zh_CN": "已选择 {selected} 个",
        },
        "select_all": {
            "en": "Select All",
            "zh_CN": "全选",
        },
        "deselect_all": {
            "en": "Deselect All",
            "zh_CN": "取消全选",
        },
        "clear_list": {
            "en": "Clear List",
            "zh_CN": "清空列表",
        },
        "clear_list_tooltip": {
            "en": "Clear all videos from the table",
            "zh_CN": "清空表格中的所有视频",
        },
        "search_placeholder": {
            "en": "🔍 Search videos...",
            "zh_CN": "🔍 搜索视频...",
        },
        "empty_title": {
            "en": "No videos available",
            "zh_CN": "暂无视频",
        },
        "empty_subtitle": {
            "en": "Scan a YouTube channel or playlist to load videos.",
            "zh_CN": "扫描 YouTube 频道或播放列表以加载视频。",
        },

        # Video Table Context Menu
        "ctx_copy_title": {
            "en": "Copy Title",
            "zh_CN": "复制标题",
        },
        "ctx_copy_url": {
            "en": "Copy URL",
            "zh_CN": "复制链接",
        },
        "ctx_copy_id": {
            "en": "Copy Video ID",
            "zh_CN": "复制视频 ID",
        },
        "ctx_open_browser": {
            "en": "Open in Browser",
            "zh_CN": "在浏览器中打开",
        },
        "ctx_view_error_details": {
            "en": "View Error Details...",
            "zh_CN": "查看错误详情...",
        },
        "ctx_copy_error_details": {
            "en": "Copy Error Details",
            "zh_CN": "复制错误报告",
        },

        # Section 3: Download Option
        "section_download_option": {
            "en": "DOWNLOAD OPTION",
            "zh_CN": "下载选项",
        },
        "save_to": {
            "en": "Save to:",
            "zh_CN": "保存到：",
        },
        "browse": {
            "en": "Browse...",
            "zh_CN": "浏览...",
        },

        # Sub-panel 1: MEDIA
        "subsection_media": {
            "en": "MEDIA",
            "zh_CN": "视频与音频",
        },
        "label_mode": {
            "en": "Mode",
            "zh_CN": "下载内容",
        },
        "label_resolution": {
            "en": "Video Resolution",
            "zh_CN": "视频分辨率",
        },
        "label_video_format": {
            "en": "Video Format",
            "zh_CN": "视频格式",
        },
        "label_video_bitrate": {
            "en": "Video Bitrate",
            "zh_CN": "视频码率",
        },
        "label_audio_format": {
            "en": "Audio Format",
            "zh_CN": "音频格式",
        },
        "label_audio_bitrate": {
            "en": "Audio Bitrate",
            "zh_CN": "音频质量",
        },

        # Sub-panel 2: ADDITIONAL ASSETS
        "subsection_assets": {
            "en": "ADDITIONAL ASSETS",
            "zh_CN": "其他内容",
        },
        "cb_subtitles": {
            "en": "Subtitles",
            "zh_CN": "字幕",
        },
        "label_sub_source": {
            "en": "Source",
            "zh_CN": "字幕来源",
        },
        "label_sub_lang": {
            "en": "Language",
            "zh_CN": "字幕语言",
        },
        "label_sub_format": {
            "en": "Subtitle Format",
            "zh_CN": "字幕格式",
        },
        "cb_thumbnail": {
            "en": "Download thumbnail",
            "zh_CN": "下载封面图",
        },
        "cb_thumbnail_tooltip": {
            "en": "Download the video's YouTube thumbnail as a separate image file.",
            "zh_CN": "将视频的 YouTube 封面保存为独立图片文件。",
        },
        "label_thumb_format": {
            "en": "Thumbnail Format",
            "zh_CN": "封面格式",
        },
        "label_thumb_format_tooltip": {
            "en": "Format for saved thumbnail image.",
            "zh_CN": "保存封面图的图片格式。",
        },
        "subgroup_info_files": {
            "en": "INFORMATION FILES",
            "zh_CN": "视频信息",
        },
        "cb_save_desc": {
            "en": "Save description",
            "zh_CN": "保存视频简介",
        },
        "cb_save_desc_tooltip": {
            "en": "Save original YouTube video description to a .description text file.",
            "zh_CN": "将原始 YouTube 视频简介保存为 .description 文本文件。",
        },
        "cb_save_meta": {
            "en": "Save metadata",
            "zh_CN": "保存元数据",
        },
        "cb_save_meta_tooltip": {
            "en": "Save clean, organized video metadata to a .metadata.txt file.",
            "zh_CN": "将整理后的视频元数据保存为 .metadata.txt 文件。",
        },
        "cb_save_chapters": {
            "en": "Save chapters",
            "zh_CN": "保存章节",
        },
        "cb_save_chapters_tooltip": {
            "en": "Save video chapter markers to a .chapters.txt file.",
            "zh_CN": "将视频章节标记保存为 .chapters.txt 文件。",
        },

        # Sub-panel 3: FILE ORGANIZATION
        "subsection_org": {
            "en": "FILE ORGANIZATION",
            "zh_CN": "文件整理",
        },
        "cb_skip_existing": {
            "en": "Skip downloaded videos",
            "zh_CN": "跳过已下载视频",
        },
        "cb_skip_existing_tooltip": {
            "en": "Skip downloading files that already exist in the target folder.",
            "zh_CN": "跳过目标文件夹中已存在的视频文件。",
        },
        "cb_channel_folder": {
            "en": "Create channel subfolder",
            "zh_CN": "按频道分类存放",
        },
        "cb_channel_folder_tooltip": {
            "en": "Store videos inside a folder named after the channel.",
            "zh_CN": "在目标目录中按频道名称建立子文件夹保存。",
        },
        "cb_individual_folder": {
            "en": "Create individual video folders",
            "zh_CN": "每个视频单独建文件夹",
        },
        "cb_individual_folder_tooltip": {
            "en": "Store each video's files in its own folder.",
            "zh_CN": "为每个视频创建专属文件夹存放其所有相关文件。",
        },

        # Action Bar Buttons
        "btn_start_download": {
            "en": "Start Download",
            "zh_CN": "开始下载",
        },
        "btn_pause": {
            "en": "Pause",
            "zh_CN": "暂停",
        },
        "btn_pause_tooltip": {
            "en": "Pause queue after current video finishes",
            "zh_CN": "在当前视频下载完成后暂停队列",
        },
        "btn_resume": {
            "en": "Resume",
            "zh_CN": "继续",
        },
        "btn_resume_tooltip": {
            "en": "Resume paused download queue",
            "zh_CN": "恢复已暂停的下载队列",
        },
        "btn_cancel": {
            "en": "Cancel",
            "zh_CN": "取消",
        },
        "btn_cancel_tooltip": {
            "en": "Cancel active download and stop queue",
            "zh_CN": "取消当前下载并停止队列",
        },
        "btn_open_folder": {
            "en": "Open Folder",
            "zh_CN": "打开文件夹",
        },
        "btn_open_folder_tooltip": {
            "en": "Open destination directory in Windows Explorer",
            "zh_CN": "在 Windows 资源管理器中打开目标目录",
        },

        # Section 4: Download Progress
        "section_download_progress": {
            "en": "DOWNLOAD PROGRESS",
            "zh_CN": "下载进度",
        },
        "current_video_none": {
            "en": "Current Video: None",
            "zh_CN": "当前视频：无",
        },
        "current_video_fmt": {
            "en": "Current Video: {title}",
            "zh_CN": "当前视频：{title}",
        },
        "overall_progress_fmt": {
            "en": "Overall Progress: {completed} / {total} completed",
            "zh_CN": "总进度：已完成 {completed} / {total}",
        },
        "speed_fmt": {
            "en": "Speed: {speed}",
            "zh_CN": "下载速度：{speed}",
        },
        "eta_fmt": {
            "en": "ETA: {eta}",
            "zh_CN": "预计剩余时间：{eta}",
        },
        "queue_stats_fmt": {
            "en": "Completed: {completed} | Skipped: {skipped} | Failed: {failed} | Remaining: {remaining}",
            "zh_CN": "已完成：{completed} | 已跳过：{skipped} | 失败：{failed} | 剩余：{remaining}",
        },

        # Section 5: Activity Log
        "section_activity_log": {
            "en": "ACTIVITY LOG",
            "zh_CN": "运行日志",
        },
        "log_hint": {
            "en": "Real-time extraction and download output",
            "zh_CN": "实时解析与下载输出",
        },
        "show_log": {
            "en": "Show Log ▾",
            "zh_CN": "显示日志 ▾",
        },
        "hide_log": {
            "en": "Hide Log ▴",
            "zh_CN": "收起日志 ▴",
        },
        "clear_log": {
            "en": "Clear Log",
            "zh_CN": "清空日志",
        },

        # Status Bar Messages
        "status_ready": {
            "en": "Ready • Paste a YouTube channel URL and click 'Scan Channel'",
            "zh_CN": "就绪 • 请粘贴 YouTube 频道或播放列表链接并点击“扫描频道”",
        },
        "status_scanning": {
            "en": "Scanning channel...",
            "zh_CN": "正在扫描频道...",
        },
        "status_scan_complete_fmt": {
            "en": "Scan complete • {count} videos found",
            "zh_CN": "扫描完成 • 找到 {count} 个视频",
        },
        "status_scan_empty": {
            "en": "Scan complete • No downloadable videos found.",
            "zh_CN": "扫描完成 • 未找到可下载的视频。",
        },
        "status_scan_failed": {
            "en": "Scan failed. Check the channel URL and network connection.",
            "zh_CN": "扫描失败。请检查频道链接与网络连接。",
        },
        "status_downloading_fmt": {
            "en": "Downloading {index}/{total}: {title}",
            "zh_CN": "正在下载 {index}/{total}：{title}",
        },
        "status_paused": {
            "en": "Queue paused.",
            "zh_CN": "下载队列已暂停。",
        },
        "status_resumed": {
            "en": "Queue resumed.",
            "zh_CN": "下载队列已继续。",
        },
        "status_cancelled": {
            "en": "Download cancelled.",
            "zh_CN": "下载已取消。",
        },
        "status_finished_fmt": {
            "en": "Download finished • {completed} completed, {failed} failed, {skipped} skipped",
            "zh_CN": "下载已完成 • 成功 {completed}，失败 {failed}，跳过 {skipped}",
        },

        # Common Messages & Dialogs
        "dialog_no_selection_title": {
            "en": "No Videos Selected",
            "zh_CN": "未选择视频",
        },
        "dialog_no_selection_msg": {
            "en": "Please select at least one video to download.",
            "zh_CN": "请至少勾选一个要下载的视频。",
        },
        "dialog_invalid_url_title": {
            "en": "Invalid URL",
            "zh_CN": "链接无效",
        },
        "dialog_invalid_url_msg": {
            "en": "Please enter a valid YouTube channel or playlist URL.",
            "zh_CN": "请输入有效的 YouTube 频道或播放列表链接。",
        },
        "dialog_missing_dest_title": {
            "en": "Missing Destination",
            "zh_CN": "未指定保存文件夹",
        },
        "dialog_missing_dest_msg": {
            "en": "Please choose a download destination folder.",
            "zh_CN": "请选择视频下载的目标文件夹。",
        },
        "dialog_folder_not_found_title": {
            "en": "Folder Not Found",
            "zh_CN": "文件夹不存在",
        },
        "dialog_folder_not_found_msg": {
            "en": "The destination directory does not exist yet:\n{folder}",
            "zh_CN": "目标文件夹尚不存在：\n{folder}",
        },
        "dialog_ffmpeg_warning_title": {
            "en": "FFmpeg Recommended",
            "zh_CN": "建议配置 FFmpeg",
        },
        "dialog_ffmpeg_warning_msg": {
            "en": "FFmpeg is not detected on your system. Merging video/audio streams, extracting audio, "
                  "converting subtitles, or converting thumbnails requires FFmpeg.\n\n"
                  "Would you like to continue anyway?",
            "zh_CN": "检测到系统尚未配置 FFmpeg。合并音视频流、提取音频、转换字幕或封面格式需要 FFmpeg 支持。\n\n是否仍要继续？",
        },
        "dialog_confirm_cancel_title": {
            "en": "Confirm Cancellation",
            "zh_CN": "确认取消",
        },
        "dialog_confirm_cancel_msg": {
            "en": "Are you sure you want to cancel the current download and stop the queue?",
            "zh_CN": "确定要取消当前下载并停止队列吗？",
        },
        "select_folder_title": {
            "en": "Select Download Destination Folder",
            "zh_CN": "选择下载保存文件夹",
        },

        # Settings Dialog
        "settings_window_title": {
            "en": "Settings - Channel Harvest",
            "zh_CN": "设置 - Channel Harvest",
        },
        "settings_appearance": {
            "en": "APPEARANCE",
            "zh_CN": "外观",
        },
        "settings_theme": {
            "en": "Theme",
            "zh_CN": "主题",
        },
        "settings_language": {
            "en": "Language",
            "zh_CN": "语言",
        },
        "settings_sys_components": {
            "en": "SYSTEM COMPONENTS",
            "zh_CN": "系统组件",
        },
        "installed": {
            "en": "Installed",
            "zh_CN": "已安装",
        },
        "not_found": {
            "en": "Not Found",
            "zh_CN": "未找到",
        },
        "path_prefix": {
            "en": "Path: {path}",
            "zh_CN": "路径：{path}",
        },
        "copy_path": {
            "en": "Copy Path",
            "zh_CN": "复制路径",
        },
        "copied": {
            "en": "Copied!",
            "zh_CN": "已复制！",
        },
        "ffmpeg_hint": {
            "en": "Required for merging video and audio streams into MP4/MKV.",
            "zh_CN": "用于将视频与音频流合并为 MP4/MKV 格式。",
        },
        "check_for_updates": {
            "en": "Check for Updates",
            "zh_CN": "检查更新",
        },
        "checking_updates": {
            "en": "Checking...",
            "zh_CN": "正在检查...",
        },
        "check_again": {
            "en": "Check Again",
            "zh_CN": "重新检查",
        },
        "retry": {
            "en": "Retry",
            "zh_CN": "重试",
        },
        "check_failed": {
            "en": "Check Failed",
            "zh_CN": "检查失败",
        },
        "update_available": {
            "en": "Update available",
            "zh_CN": "有可用更新",
        },
        "up_to_date": {
            "en": "Up to date",
            "zh_CN": "已是最新版本",
        },
        "is_latest_ver_fmt": {
            "en": "v{ver} is the latest version.",
            "zh_CN": "v{ver} 已是最新版本。",
        },
        "update_ytdlp": {
            "en": "Update yt-dlp",
            "zh_CN": "更新 yt-dlp",
        },
        "auto_check_ytdlp": {
            "en": "Automatically check for yt-dlp updates",
            "zh_CN": "启动时自动检查 yt-dlp 更新",
        },
        "deno_title": {
            "en": "Deno (JS Runtime)",
            "zh_CN": "Deno (JS 运行环境)",
        },
        "deno_hint": {
            "en": "JavaScript runtime required by yt-dlp to solve YouTube video challenges.",
            "zh_CN": "yt-dlp 用于执行 YouTube 视频挑战验证的 JavaScript 运行环境。",
        },
        "settings_auth": {
            "en": "YOUTUBE AUTHENTICATION",
            "zh_CN": "YOUTUBE 登录",
        },
        "settings_browser_cookies": {
            "en": "Browser Cookies",
            "zh_CN": "浏览器 Cookie",
        },
        "settings_cookies_hint": {
            "en": "Use browser cookies if YouTube requires sign-in verification. Browsers should be closed during downloads.",
            "zh_CN": "若 YouTube 要求人机验证或登录，可调用本地浏览器 Cookie。下载时请关闭相应浏览器。",
        },
        "cookies_none": {
            "en": "No authentication (Default)",
            "zh_CN": "不使用认证 (默认)",
        },
        "auth_test_btn": {
            "en": "Test",
            "zh_CN": "测试登录",
        },
        "auth_test_tooltip": {
            "en": "Test if YouTube cookies can be safely read from the selected browser",
            "zh_CN": "测试是否能安全读取所选浏览器的 YouTube Cookie",
        },
        "auth_test_title": {
            "en": "Authentication Test",
            "zh_CN": "登录测试",
        },
        "auth_disabled_msg": {
            "en": "Authentication is currently disabled. Please select a browser from the dropdown first.",
            "zh_CN": "当前已禁用身份验证。请先在下拉菜单中选择一个浏览器。",
        },
        "auth_test_success_title": {
            "en": "Authentication Successful",
            "zh_CN": "登录测试成功",
        },
        "auth_test_success_msg": {
            "en": "Successfully detected {count} YouTube/Google authentication cookie(s) from {browser}.",
            "zh_CN": "成功从 {browser} 中检测到 {count} 个 YouTube/Google 验证 Cookie。",
        },
        "auth_test_warn_title": {
            "en": "No Cookies Found",
            "zh_CN": "未检测到 Cookie",
        },
        "auth_test_no_cookies_msg": {
            "en": "No YouTube or Google cookies were found in {browser}.\nPlease open {browser} and log in to YouTube first.",
            "zh_CN": "在 {browser} 中未找到 YouTube 或 Google Cookie。\n请先打开 {browser} 登录 YouTube。",
        },
        "auth_test_error_title": {
            "en": "Authentication Error",
            "zh_CN": "登录测试失败",
        },
        "auth_test_error_msg": {
            "en": "Failed to read cookies from {browser}:\n{error}\n\nPlease ensure {browser} is fully closed before testing.",
            "zh_CN": "读取 {browser} 的 Cookie 失败：\n{error}\n\n请确保在测试前已完全关闭 {browser}。",
        },
        "cookies_chrome": {
            "en": "Google Chrome",
            "zh_CN": "Google Chrome",
        },
        "cookies_edge": {
            "en": "Microsoft Edge",
            "zh_CN": "Microsoft Edge",
        },
        "cookies_firefox": {
            "en": "Mozilla Firefox",
            "zh_CN": "Mozilla Firefox",
        },
        "cookies_brave": {
            "en": "Brave",
            "zh_CN": "Brave",
        },
        "cookies_opera": {
            "en": "Opera",
            "zh_CN": "Opera",
        },
        "cookies_vivaldi": {
            "en": "Vivaldi",
            "zh_CN": "Vivaldi",
        },
        "auth_custom_cookie_file": {
            "en": "Custom Cookie File (cookies.txt)...",
            "zh_CN": "Cookie 文件 (cookies.txt)...",
        },
        "auth_cookie_file_placeholder": {
            "en": "Select exported cookies.txt file...",
            "zh_CN": "选择导出的 cookies.txt 文件...",
        },
        "auth_select_cookie_file": {
            "en": "Select Cookie File",
            "zh_CN": "选择 Cookie 文件",
        },
        "status_testing": {
            "en": "Testing...",
            "zh_CN": "测试中...",
        },
        "auth_dialog_title": {
            "en": "YouTube Authentication Diagnostics",
            "zh_CN": "YouTube 登录诊断",
        },
        "auth_dialog_stage_heading": {
            "en": "STAGE & SOURCE DETAILS",
            "zh_CN": "阶段与来源信息",
        },
        "auth_dialog_stage": {
            "en": "Verification Stage",
            "zh_CN": "验证阶段",
        },
        "auth_dialog_source": {
            "en": "Source",
            "zh_CN": "凭证来源",
        },
        "auth_dialog_reason_heading": {
            "en": "DIAGNOSTIC CAUSE",
            "zh_CN": "诊断原因",
        },
        "auth_dialog_action_heading": {
            "en": "SUGGESTED ACTION",
            "zh_CN": "建议操作",
        },
        "auth_dialog_tech_heading": {
            "en": "SANITIZED TECHNICAL DETAILS",
            "zh_CN": "技术详情 (已脱敏)",
        },
        "auth_dialog_copy_btn": {
            "en": "Copy Diagnostic Details",
            "zh_CN": "复制诊断详情",
        },
        "auth_dialog_close_btn": {
            "en": "Close",
            "zh_CN": "关闭",
        },
        "auth_method_label": {
            "en": "Authentication Method",
            "zh_CN": "登录方式",
        },
        "auth_method_none": {
            "en": "None",
            "zh_CN": "不使用",
        },
        "auth_method_browser": {
            "en": "Browser Cookies",
            "zh_CN": "浏览器 Cookie",
        },
        "auth_method_custom_file_radio": {
            "en": "Custom Cookie File",
            "zh_CN": "Cookie 文件",
        },
        "auth_browser_label": {
            "en": "Browser:",
            "zh_CN": "浏览器：",
        },
        "auth_profile_label": {
            "en": "Profile:",
            "zh_CN": "配置文件：",
        },
        "auth_cookie_file_label": {
            "en": "Cookie File:",
            "zh_CN": "Cookie 文件：",
        },
        "auth_status_label": {
            "en": "Status:",
            "zh_CN": "状态：",
        },
        "status_not_configured": {
            "en": "Not configured",
            "zh_CN": "未配置",
        },
        "status_not_tested": {
            "en": "Not tested",
            "zh_CN": "未测试",
        },
        "status_cookie_file_detected": {
            "en": "Cookie file detected",
            "zh_CN": "已检测到 Cookie 文件",
        },
        "status_session_detected": {
            "en": "YouTube session detected",
            "zh_CN": "已检测到 YouTube 登录 Cookie",
        },
        "status_decryption_failed": {
            "en": "Browser cookies could not be decrypted",
            "zh_CN": "无法解密浏览器 Cookie",
        },
        "status_invalid_cookie_file": {
            "en": "This does not appear to be a valid cookies.txt file.",
            "zh_CN": "这似乎不是有效的 cookies.txt 文件。",
        },
        "auth_none_hint": {
            "en": "Authentication is not configured. Public YouTube downloads will proceed without cookies.",
            "zh_CN": "未配置登录。公开的 YouTube 视频无需 Cookie 即可直接下载。",
        },
        "auth_clear_cookie_file": {
            "en": "Clear Cookie File",
            "zh_CN": "清除 Cookie 文件",
        },
        "auth_cookie_file_cleared": {
            "en": "Cookie file reference cleared.",
            "zh_CN": "已清除 Cookie 文件引用。",
        },
        "auth_cookie_file_privacy_notice": {
            "en": "Cookie files contain sensitive YouTube session information. Keep this file private and do not share it publicly.",
            "zh_CN": "Cookie 文件包含敏感的 YouTube 登录会话信息。请妥善保管，切勿公开发布或分享。",
        },
        "auth_diagnostics_heading": {
            "en": "AUTHENTICATION DIAGNOSTICS",
            "zh_CN": "登录诊断",
        },
        "auth_last_test": {
            "en": "Last Test:",
            "zh_CN": "上次测试：",
        },
        "auth_view_diagnostic_details": {
            "en": "View Diagnostic Details",
            "zh_CN": "查看诊断详情",
        },
        "auth_switch_to_cookie_file": {
            "en": "Use Custom Cookie File",
            "zh_CN": "使用 Cookie 文件",
        },
        "auth_abe_title": {
            "en": "{browser} Cookie Access Unavailable",
            "zh_CN": "{browser} Cookie 访问不可用",
        },
        "auth_abe_reason": {
            "en": "Channel Harvest could not decrypt the cookies stored by {browser}. This can happen with modern {browser} security protection (such as App-Bound Encryption). Your YouTube login may still be working normally in {browser}.",
            "zh_CN": "Channel Harvest 无法解密 {browser} 存储的 Cookie。这通常由现代 {browser} 安全保护机制 (如 App-Bound 绑定加密) 引起。您的 YouTube 登录在 {browser} 浏览器中可能仍然正常工作。",
        },
        "auth_abe_solution": {
            "en": "Recommended solution: Export your YouTube cookies as a cookies.txt file and select it under Custom Cookie File.",
            "zh_CN": "建议解决方案：使用浏览器扩展将您的 YouTube Cookie 导出为 cookies.txt 文件，并在“自定义 Cookie 文件”中选择它。",
        },
        "auth_select_cookie_file_btn": {
            "en": "Select Cookie File",
            "zh_CN": "选择 Cookie 文件",
        },
        "settings_data_dir": {
            "en": "DATA DIRECTORY",
            "zh_CN": "数据目录",
        },
        "data_dir_desc": {
            "en": "Application data & download archive:",
            "zh_CN": "应用程序数据与下载归档记录：",
        },
        "open_data_folder": {
            "en": "Open Data Folder",
            "zh_CN": "打开数据文件夹",
        },
        "open_data_folder_tooltip": {
            "en": "Open %APPDATA%\\ChannelHarvest in Windows File Explorer",
            "zh_CN": "在 Windows 资源管理器中打开 %APPDATA%\\ChannelHarvest",
        },
        "developed_by_fmt": {
            "en": "Developed by {developer}",
            "zh_CN": "开发者：{developer}",
        },
        "ytdlp_busy_title": {
            "en": "Download in Progress",
            "zh_CN": "正在下载中",
        },
        "ytdlp_busy_msg": {
            "en": "yt-dlp cannot be updated while a download is running.\n\nPlease finish or cancel the current download first.",
            "zh_CN": "下载正在进行中，无法更新 yt-dlp。\n\n请先完成或取消当前下载。",
        },
        "ytdlp_update_prompt_title": {
            "en": "Update yt-dlp",
            "zh_CN": "更新 yt-dlp",
        },
        "ytdlp_update_prompt_msg": {
            "en": "A new yt-dlp version is available.\n\nCurrent version: v{current}\nLatest version: v{latest}\n\nWould you like to update?",
            "zh_CN": "发现新的 yt-dlp 版本。\n\n当前版本：v{current}\n最新版本：v{latest}\n\n是否立即更新？",
        },
        "updating": {
            "en": "Updating...",
            "zh_CN": "正在更新...",
        },
        "downloading_update": {
            "en": "Downloading and installing update...",
            "zh_CN": "正在下载并安装更新...",
        },
        "update_complete_title": {
            "en": "Update Complete",
            "zh_CN": "更新完成",
        },
        "update_complete_msg": {
            "en": "yt-dlp has been updated to v{ver} successfully.",
            "zh_CN": "yt-dlp 已成功更新至 v{ver}。",
        },
        "update_failed_title": {
            "en": "Update Failed",
            "zh_CN": "更新失败",
        },
        "update_failed_msg": {
            "en": "Could not update yt-dlp:\n{error}\n\nYour existing yt-dlp installation was preserved.",
            "zh_CN": "无法更新 yt-dlp：\n{error}\n\n已保留现有的 yt-dlp 安装。",
        },
        "retry_update": {
            "en": "Retry Update",
            "zh_CN": "重试更新",
        },

        # Runtime Manager & Diagnostic Report
        "runtime_manager_title": {
            "en": "RUNTIME MANAGER",
            "zh_CN": "下载组件",
        },
        "runtime_manager_sub": {
            "en": "Channel Harvest Runtime",
            "zh_CN": "Channel Harvest 下载组件",
        },
        "th_component": {
            "en": "Component",
            "zh_CN": "组件",
        },
        "th_current_version": {
            "en": "Current Version",
            "zh_CN": "当前版本",
        },
        "th_status": {
            "en": "Status",
            "zh_CN": "状态",
        },
        "status_up_to_date": {
            "en": "Up to date",
            "zh_CN": "已是最新版本",
        },
        "status_update_available": {
            "en": "Update available",
            "zh_CN": "有可用更新",
        },
        "status_not_installed": {
            "en": "Not Installed",
            "zh_CN": "未安装",
        },
        "status_not_found": {
            "en": "Not Found",
            "zh_CN": "未找到",
        },
        "status_checking": {
            "en": "Checking...",
            "zh_CN": "正在检查...",
        },
        "status_error": {
            "en": "Error",
            "zh_CN": "检查失败",
        },
        "check_runtime_updates": {
            "en": "Check for Runtime Updates",
            "zh_CN": "检查组件更新",
        },
        "update_available_components": {
            "en": "Update Available Components",
            "zh_CN": "更新组件",
        },
        "auto_check_runtime": {
            "en": "Automatically check for runtime updates",
            "zh_CN": "启动时自动检查组件更新",
        },
        "diagnostic_report_title": {
            "en": "DIAGNOSTIC REPORT",
            "zh_CN": "诊断报告",
        },
        "diagnostic_report_desc": {
            "en": "Create a diagnostic report containing system and runtime information.",
            "zh_CN": "生成包含系统与运行环境信息的诊断报告，用于故障排查。",
        },
        "copy_diagnostic_info": {
            "en": "Copy Diagnostic Information",
            "zh_CN": "复制诊断信息",
        },
        "copied_diagnostic_info": {
            "en": "Diagnostic information copied to clipboard.",
            "zh_CN": "诊断信息已复制到剪贴板。",
        },
        "open_log_folder": {
            "en": "Open Log Folder",
            "zh_CN": "打开日志文件夹",
        },
        "open_log_folder_tooltip": {
            "en": "Open %APPDATA%\\ChannelHarvest\\logs in Windows File Explorer",
            "zh_CN": "在 Windows 资源管理器中打开日志文件夹",
        },
        "runtime_busy_title": {
            "en": "Download in Progress",
            "zh_CN": "正在下载中",
        },
        "runtime_busy_msg": {
            "en": "Runtime components cannot be updated while downloads are running.\n\nPlease pause or wait for downloads to complete.",
            "zh_CN": "下载正在进行中，无法更新组件。\n\n请先暂停或等待下载完成。",
        },
        "runtime_update_confirm_title": {
            "en": "Update Runtime Components",
            "zh_CN": "更新下载组件",
        },
        "runtime_update_confirm_msg": {
            "en": "The following components have updates available:\n\n{components}\n\nWould you like to install the updates now?",
            "zh_CN": "以下组件有可用更新：\n\n{components}\n\n是否立即下载并安装更新？",
        },
        "runtime_update_complete_title": {
            "en": "Runtime Update Complete",
            "zh_CN": "组件更新完成",
        },
        "runtime_update_complete_msg": {
            "en": "Runtime components updated ({success} succeeded, {failed} failed).\n\nA restart of Channel Harvest is recommended for all changes to take effect.\n\nWould you like to restart now?",
            "zh_CN": "下载组件更新完毕（成功 {success} 个，失败 {failed} 个）。\n\n建议重启 Channel Harvest 使所有更新生效。\n\n是否立即重启软件？",
        },

        # Summary Dialog
        "summary_window_title": {
            "en": "Download Queue Complete",
            "zh_CN": "下载队列已完成",
        },
        "summary_header_title": {
            "en": "Download Completed 🎉",
            "zh_CN": "下载完成 🎉",
        },
        "summary_batch_results": {
            "en": "Batch Results",
            "zh_CN": "批量下载统计",
        },
        "summary_total": {
            "en": "Total Videos in Queue:",
            "zh_CN": "队列视频总数：",
        },
        "summary_completed": {
            "en": "Successfully Downloaded:",
            "zh_CN": "成功下载：",
        },
        "summary_skipped": {
            "en": "Skipped (Already Exists):",
            "zh_CN": "已跳过（文件已存在）：",
        },
        "summary_failed": {
            "en": "Failed:",
            "zh_CN": "下载失败：",
        },
        "summary_destination": {
            "en": "Destination:",
            "zh_CN": "保存文件夹：",
        },
        "summary_open_folder": {
            "en": "📁 Open Download Folder",
            "zh_CN": "📁 打开下载文件夹",
        },

        # Error Details Dialog
        "error_dialog_title": {
            "en": "Error Details",
            "zh_CN": "错误详情",
        },
        "error_dialog_video_label": {
            "en": "Target Video:",
            "zh_CN": "目标视频：",
        },
        "error_dialog_reason_heading": {
            "en": "Reason",
            "zh_CN": "失败原因",
        },
        "error_dialog_action_heading": {
            "en": "What you can do",
            "zh_CN": "建议操作",
        },
        "error_dialog_tech_heading": {
            "en": "Technical Details",
            "zh_CN": "技术详情",
        },
        "error_dialog_copy_btn": {
            "en": "📋 Copy Error Details",
            "zh_CN": "📋 复制错误报告",
        },
        "error_dialog_copied": {
            "en": "✓ Copied to Clipboard!",
            "zh_CN": "✓ 已复制到剪贴板！",
        },

        # Additional Dialog & Logging Keys
        "theme_system": {
            "en": "System",
            "zh_CN": "跟随系统",
        },
        "unknown_title": {
            "en": "Unknown Title",
            "zh_CN": "未知标题",
        },
        "tech_category_label": {
            "en": "Category",
            "zh_CN": "分类",
        },
        "tech_component_label": {
            "en": "Component",
            "zh_CN": "组件",
        },
        "tech_stage_label": {
            "en": "Stage",
            "zh_CN": "阶段",
        },
        "tech_http_status_label": {
            "en": "HTTP Status",
            "zh_CN": "HTTP 状态码",
        },
        "no_tech_details": {
            "en": "No technical details available.",
            "zh_CN": "暂无技术详情",
        },
        "could_not_open_dir_fmt": {
            "en": "Could not open directory:\n{error}",
            "zh_CN": "无法打开该文件夹：\n{error}",
        },
        "could_not_restart_fmt": {
            "en": "Could not restart automatically: {error}",
            "zh_CN": "无法自动重启软件：{error}",
        },
        "could_not_open_logs_fmt": {
            "en": "Could not open logs directory:\n{error}",
            "zh_CN": "无法打开日志文件夹：\n{error}",
        },
        "cookie_yt_session_count_fmt": {
            "en": "({count} YouTube session cookies)",
            "zh_CN": "({count} 个 YouTube 登录 Cookie)",
        },
        "cookie_yt_count_no_session_fmt": {
            "en": "({count} YouTube cookies, no active session)",
            "zh_CN": "({count} 个 YouTube Cookie，无登录会话)",
        },
        "cookie_count_no_yt_fmt": {
            "en": "({count} cookies, no YouTube cookies)",
            "zh_CN": "({count} 个 Cookie，未包含 YouTube Cookie)",
        },
        "auth_optional_hint": {
            "en": "Authentication is optional. Public YouTube videos download normally without configuration.",
            "zh_CN": "未配置登录。公开的 YouTube 视频无需登录即可直接下载。",
        },
        "auth_click_test_hint": {
            "en": "Click 'Test' to run a live YouTube verification.",
            "zh_CN": "点击“测试登录”即可验证与 YouTube 的连通状态。",
        },
        "auth_no_test_yet": {
            "en": "No live authentication test has been run in this session.",
            "zh_CN": "当前会话尚未进行身份验证测试。",
        },
        "auth_click_test_verify_hint": {
            "en": "Click 'Test' to verify browser cookie extraction and YouTube connectivity.",
            "zh_CN": "点击“测试登录”以检测浏览器 Cookie 读取及 YouTube 连通性。",
        },
        "auth_result_abe_header_fmt": {
            "en": "⚠️ {browser} Cookie Access Unavailable",
            "zh_CN": "⚠️ {browser} Cookie 无法读取",
        },
        "auth_result_not_configured": {
            "en": "ℹ Authentication Not Configured",
            "zh_CN": "ℹ 尚未配置身份验证",
        },
        "auth_result_success_fmt": {
            "en": "✓ {browser} Session Authenticated",
            "zh_CN": "✓ {browser} 登录会话验证成功",
        },
        "auth_result_success_no_session_fmt": {
            "en": "✓ {browser} Succeeded (No Login Session)",
            "zh_CN": "✓ {browser} 验证成功 (无登录会话)",
        },
        "auth_result_failed_fmt": {
            "en": "✕ {browser} Authentication Failed",
            "zh_CN": "✕ {browser} 身份验证失败",
        },
        "auth_result_profile_fmt": {
            "en": " (Profile: {profile})",
            "zh_CN": " (配置文件：{profile})",
        },
        "cookie_file_filter": {
            "en": "Cookie Files (*.txt);;All Files (*.*)",
            "zh_CN": "Cookie 文件 (*.txt);;所有文件 (*.*)",
        },
        "videos_found_filter_fmt": {
            "en": "{visible} of {total} videos found",
            "zh_CN": "显示 {visible} / {total} 个视频",
        },
        "one_video_found": {
            "en": "1 video found",
            "zh_CN": "共找到 1 个视频",
        },
        "tooltip_reason_label": {
            "en": "Reason:",
            "zh_CN": "失败原因：",
        },
        "tooltip_action_label": {
            "en": "What you can do:",
            "zh_CN": "建议操作：",
        },
        "tooltip_details_hint": {
            "en": "(Double-click or right-click to view details)",
            "zh_CN": "(双击或右键查看详情)",
        },
        "download_failed_fallback": {
            "en": "Download failed",
            "zh_CN": "下载失败",
        },
        "video_id_prefix": {
            "en": "ID: {id}",
            "zh_CN": "视频 ID：{id}",
        },
        "url_prefix": {
            "en": "URL: {url}",
            "zh_CN": "链接：{url}",
        },
        "youtube_id_prefix": {
            "en": "YouTube ID: {id}",
            "zh_CN": "YouTube ID：{id}",
        },
        "log_ready": {
            "en": "[READY] Channel Harvest initialized.",
            "zh_CN": "[就绪] Channel Harvest 初始化完成。",
        },
        "log_archive_active_fmt": {
            "en": "[INFO] Download archive active: {name}",
            "zh_CN": "[信息] 下载归档记录已启用：{name}",
        },
        "log_ffmpeg_warning": {
            "en": "[WARNING] FFmpeg was not detected on this system. Audio and video stream merging requires FFmpeg.",
            "zh_CN": "[警告] 系统未检测到 FFmpeg。音视频流合并与提取需要 FFmpeg 支持。",
        },
        "log_scan_finished_fmt": {
            "en": "[SUCCESS] Channel scan finished. {count} video(s) retrieved. Inspecting subtitle tracks in background...",
            "zh_CN": "[成功] 频道扫描完成，共获取 {count} 个视频。正在后台检测字幕可用性...",
        },
        "log_subtitle_detection_done": {
            "en": "[INFO] Subtitle availability detection completed.",
            "zh_CN": "[信息] 字幕可用性检测已完成。",
        },
        "log_dest_set_fmt": {
            "en": "[CONFIG] Download destination set to: {path}",
            "zh_CN": "[配置] 下载保存目录已设为：{path}",
        },
        "log_update_available_fmt": {
            "en": "[UPDATE] A new yt-dlp version is available: v{latest} (current: v{current}). Check Settings to update.",
            "zh_CN": "[更新] 发现新的 yt-dlp 版本：v{latest}（当前版本：v{current}）。请前往“设置”进行更新。",
        },
    }

    # -------------------------------------------------------------------------
    # Canonical Value Translations (For Dropdowns & Badges)
    # -------------------------------------------------------------------------
    _MODE_LABELS = {
        DownloadMode.VIDEO_AND_AUDIO: {"en": "Video + Audio", "zh_CN": "视频 + 音频"},
        DownloadMode.VIDEO_ONLY: {"en": "Video Only", "zh_CN": "仅视频"},
        DownloadMode.AUDIO_ONLY: {"en": "Audio Only", "zh_CN": "仅音频"},
        DownloadMode.SUBTITLE_ONLY: {"en": "Subtitle Only", "zh_CN": "仅字幕"},
    }

    _SUB_SOURCE_LABELS = {
        SubtitleSource.BEST_AVAILABLE: {"en": "Best Available", "zh_CN": "最佳可用"},
        SubtitleSource.OFFICIAL: {"en": "Official Only", "zh_CN": "官方字幕"},
        SubtitleSource.AUTO_GENERATED: {"en": "Auto-generated Only", "zh_CN": "自动生成字幕"},
    }

    _SUB_LANG_LABELS = {
        SubtitleLanguage.CHINESE: {"en": "Chinese (中文)", "zh_CN": "中文"},
        SubtitleLanguage.ENGLISH: {"en": "English", "zh_CN": "英文"},
        SubtitleLanguage.MALAY: {"en": "Malay (Bahasa Melayu)", "zh_CN": "马来文"},
        SubtitleLanguage.JAPANESE: {"en": "Japanese (日本語)", "zh_CN": "日文"},
        SubtitleLanguage.KOREAN: {"en": "Korean (한국어)", "zh_CN": "韩文"},
        SubtitleLanguage.ALL: {"en": "All Available Languages", "zh_CN": "全部语言"},
    }

    _THUMB_FORMAT_LABELS = {
        ThumbnailFormat.JPG: {"en": "JPG", "zh_CN": "JPG"},
        ThumbnailFormat.PNG: {"en": "PNG", "zh_CN": "PNG"},
        ThumbnailFormat.WEBP: {"en": "WEBP", "zh_CN": "WEBP"},
        ThumbnailFormat.ORIGINAL: {"en": "Original", "zh_CN": "原始格式"},
    }

    _THEME_LABELS = {
        "System": {"en": "System", "zh_CN": "跟随系统"},
        "Light": {"en": "Light", "zh_CN": "浅色模式"},
        "Dark": {"en": "Dark", "zh_CN": "深色模式"},
    }

    _STATUS_LABELS = {
        VideoStatus.WAITING: {"en": "Waiting", "zh_CN": "等待中"},
        VideoStatus.DOWNLOADING: {"en": "Downloading", "zh_CN": "下载中"},
        VideoStatus.PROCESSING: {"en": "Processing", "zh_CN": "处理中"},
        VideoStatus.COMPLETED: {"en": "Completed", "zh_CN": "已完成"},
        VideoStatus.SKIPPED: {"en": "Skipped", "zh_CN": "已跳过"},
        VideoStatus.FAILED: {"en": "Failed", "zh_CN": "失败"},
        VideoStatus.CANCELLED: {"en": "Cancelled", "zh_CN": "已取消"},
        "Bot Verification Required": {"en": "Bot Verification Required", "zh_CN": "需人机验证"},
        "Rate Limited (429)": {"en": "Rate Limited (429)", "zh_CN": "被限流 (429)"},
        "Private / Unavailable": {"en": "Private / Unavailable", "zh_CN": "私密/不可用"},
        # Concise Error Statuses
        "Failed — HTTP 403": {"en": "Failed — HTTP 403", "zh_CN": "失败 — HTTP 403"},
        "Failed — Rate limited": {"en": "Failed — Rate limited", "zh_CN": "失败 — 请求被限流"},
        "Failed — Rate limited (429)": {"en": "Failed — Rate limited (429)", "zh_CN": "失败 — Rate limited (429)"},
        "Failed — Bot verification": {"en": "Failed — Bot verification", "zh_CN": "失败 — 需人机验证"},
        "Failed — Login required": {"en": "Failed — Login required", "zh_CN": "失败 — 需要登录"},
        "Failed — Private video": {"en": "Failed — Private video", "zh_CN": "失败 — 私密视频"},
        "Failed — Video unavailable": {"en": "Failed — Video unavailable", "zh_CN": "失败 — 视频不可用"},
        "Failed — Region restricted": {"en": "Failed — Region restricted", "zh_CN": "失败 — 地区受限"},
        "Failed — Age restricted": {"en": "Failed — Age restricted", "zh_CN": "失败 — 年龄限制"},
        "Failed — JS runtime error": {"en": "Failed — JS runtime error", "zh_CN": "失败 — JS运行时错误"},
        "Failed — EJS error": {"en": "Failed — EJS error", "zh_CN": "失败 — EJS组件错误"},
        "Failed — PO Token error": {"en": "Failed — PO Token error", "zh_CN": "失败 — PO Token错误"},
        "Failed — HTTP 404": {"en": "Failed — HTTP 404", "zh_CN": "失败 — HTTP 404"},
        "Failed — HTTP 429": {"en": "Failed — HTTP 429", "zh_CN": "失败 — HTTP 429"},
        "Failed — HTTP 500": {"en": "Failed — HTTP 500", "zh_CN": "失败 — HTTP 500"},
        "Failed — HTTP 502": {"en": "Failed — HTTP 502", "zh_CN": "失败 — HTTP 502"},
        "Failed — HTTP 503": {"en": "Failed — HTTP 503", "zh_CN": "失败 — HTTP 503"},
        "Failed — Format error": {"en": "Failed — Format error", "zh_CN": "失败 — 格式不支持"},
        "Failed — FFmpeg error": {"en": "Failed — FFmpeg error", "zh_CN": "失败 — FFmpeg转码错误"},
        "Failed — Disk full": {"en": "Failed — Disk full", "zh_CN": "失败 — 磁盘空间不足"},
        "Failed — Permission error": {"en": "Failed — Permission error", "zh_CN": "失败 — 权限不足"},
        "Failed — File system error": {"en": "Failed — File system error", "zh_CN": "失败 — 文件系统错误"},
        "Failed — File locked": {"en": "Failed — File locked", "zh_CN": "失败 — 文件被锁定"},
        "Failed — Range error (416)": {"en": "Failed — Range error (416)", "zh_CN": "失败 — 请求范围异常 (416)"},
        "Failed — Network error": {"en": "Failed — Network error", "zh_CN": "失败 — 网络错误"},
        "Failed — Timeout": {"en": "Failed — Timeout", "zh_CN": "失败 — 连接超时"},
        "Failed — Unknown error": {"en": "Failed — Unknown error", "zh_CN": "失败 — 未知错误"},
    }

    _QUALITY_LABELS = {
        "Best Available": {"en": "Best Available", "zh_CN": "最高分辨率"},
    }

    _VIDEO_BITRATE_LABELS = {
        "Best Available": {"en": "Best Available", "zh_CN": "最高画质"},
    }

    _AUDIO_BITRATE_LABELS = {
        "Best Available": {"en": "Best Available", "zh_CN": "最高音质"},
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
        if lang not in (cls.LANG_EN, cls.LANG_ZH):
            lang = cls.LANG_EN
        if cls._current_language != lang:
            cls._current_language = lang
            cls._notify_listeners()

    @classmethod
    def is_chinese(cls) -> bool:
        """Returns True if the current language is Simplified Chinese."""
        return cls._current_language == cls.LANG_ZH

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
        for cb in list(cls._listeners):
            try:
                cb(cls._current_language)
            except Exception as e:
                print(f"[I18n] Error notifying listener: {e}")

    @classmethod
    def tr(cls, key: str, **kwargs: Any) -> str:
        """
        Translates a string key into the current language, applying formatting kwargs if provided.
        Falls back to English or the key itself if not found.
        """
        lang = cls._current_language
        entry = cls._STRINGS.get(key)
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
        if canonical_bitrate == "Best Available":
            return cls._AUDIO_BITRATE_LABELS["Best Available"].get(cls._current_language, "Best Available")
        return canonical_bitrate

    @classmethod
    def get_bitrate_label(cls, canonical_bitrate: str) -> str:
        return cls.get_video_bitrate_label(canonical_bitrate)


def tr(key: str, **kwargs: Any) -> str:
    """Convenience shortcut function for I18nManager.tr()."""
    return I18nManager.tr(key, **kwargs)
