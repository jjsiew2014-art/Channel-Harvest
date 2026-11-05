"""
settings.py
Persistent user settings manager for Channel Harvest.

Saves and restores user preferences across launches:
- Target download folder
- Preferred video container format (MP4, MKV, WEBM, MOV)
- Target maximum resolution (1080p, 720p, etc.)
- Preferred bitrate
- Create channel subfolder option
- Skip already downloaded videos option
- Window size and position
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from core.paths import get_settings_file


class SettingsManager:
    """
    Manages loading and saving configuration to a JSON file in AppData.
    """

    # Safe default values for beginner users
    DEFAULT_SETTINGS: Dict[str, Any] = {
        "download_mode": "Video Only",
        "download_folder": str(Path.home() / "Downloads" / "Channel Harvest"),
        "format": "MOV",
        "quality": "1080p",
        "bitrate": "Best Available",
        "audio_format": "WAV",
        "audio_bitrate": "Best Available",
        "download_subtitles": False,
        "subtitle_source": "Best Available",
        "subtitle_language": "Chinese (中文)",
        "subtitle_format": "SRT",
        "download_thumbnail": False,
        "thumbnail_format": "JPG",
        "download_cover_art": False,
        "embed_cover_art": False,
        "embed_metadata": False,
        "download_lrc_lyrics": False,
        "embed_lyrics": False,
        "save_description": False,
        "save_metadata": False,
        "save_chapters": False,
        "create_channel_folder": True,
        "create_individual_video_folders": False,
        "include_video_id_in_filename": False,
        "skip_existing": False,
        "image_format": "Keep Original",
        "image_quality": "100% (Best)",
        "preserve_original_images": True,
        "skip_downloaded_media": False,
        "create_individual_media_folders": False,
        "include_media_id_in_filename": False,
        "add_number_to_filename": False,
        "add_number_prefix": False,
        "create_unique_filename": False,
        "create_unique_folder": False,
        "unique_filename_folder": "",
        "unique_folder_name": "",
        "window_width": 1200,
        "window_height": 960,
        "last_channel_url": "",
        "theme": "System",
        "language": "en",
        "selected_platform": "youtube",
        "auth_method": "none",
        "browser_cookies": "none",
        "browser_profile": "Default",
        "custom_cookie_file": "",
        "last_auth_status": "NOT_CONFIGURED",
        "douyin_auth_method": "none",
        "douyin_browser_cookies": "none",
        "douyin_browser_profile": "Default",
        "douyin_custom_cookie_file": "",
        "douyin_last_auth_status": "NOT_CONFIGURED",
        "bilibili_auth_method": "none",
        "bilibili_custom_cookie_file": "",
        "bilibili_last_auth_status": "NOT_CONFIGURED",
        "facebook_auth_method": "none",
        "facebook_custom_cookie_file": "",
        "facebook_last_auth_status": "NOT_CONFIGURED",
        "instagram_auth_method": "none",
        "instagram_custom_cookie_file": "",
        "instagram_last_auth_status": "NOT_CONFIGURED",
        "x_auth_method": "none",
        "x_custom_cookie_file": "",
        "x_last_auth_status": "NOT_CONFIGURED",
        "tiktok_auth_method": "none",
        "tiktok_custom_cookie_file": "",
        "tiktok_last_auth_status": "NOT_CONFIGURED",
        "all_auth_method": "none",
        "all_custom_cookie_file": "",
        "all_last_auth_status": "NOT_CONFIGURED",
        "auto_check_ytdlp_updates": True,
        "auto_check_runtime_updates": True,
        "enable_notifications": True,
        "clear_link_after_download": False,
        "clear_media_table_after_download": False,
        "clear_custom_folder_name_after_download": False,
        "auto_scan_on_paste": False,
        "last_ytdlp_update_check": 0.0,
        "last_runtime_update_check": 0.0,
    }

    def __init__(self, settings_path: Optional[Path] = None):
        self._settings_path = settings_path or get_settings_file()
        self._data: Dict[str, Any] = dict(self.DEFAULT_SETTINGS)
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from JSON file or initializes with defaults."""
        if not self._settings_path.exists() or self._settings_path.stat().st_size == 0:
            self.save()
            from core.i18n import I18nManager
            I18nManager.set_language(self._data.get("language", "en"))
            return self._data

        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    # Merge loaded settings over defaults to handle any newly added keys
                    self._data.update(loaded)
        except Exception as e:
            # If the file is corrupted, keep existing in-memory defaults
            print(f"[WARNING] Could not read settings file, using defaults: {e}")

        # Migration: old video keys <-> generalized media keys from loaded JSON
        if isinstance(loaded, dict):
            if "include_video_id_in_filename" in loaded and "include_media_id_in_filename" not in loaded:
                self._data["include_media_id_in_filename"] = loaded["include_video_id_in_filename"]
            elif "include_media_id_in_filename" in loaded and "include_video_id_in_filename" not in loaded:
                self._data["include_video_id_in_filename"] = loaded["include_media_id_in_filename"]

            if "skip_existing" in loaded and "skip_downloaded_media" not in loaded:
                self._data["skip_downloaded_media"] = loaded["skip_existing"]
            elif "skip_downloaded_media" in loaded and "skip_existing" not in loaded:
                self._data["skip_existing"] = loaded["skip_downloaded_media"]

            if "create_individual_video_folders" in loaded and "create_individual_media_folders" not in loaded:
                self._data["create_individual_media_folders"] = loaded["create_individual_video_folders"]
            elif "create_individual_media_folders" in loaded and "create_individual_video_folders" not in loaded:
                self._data["create_individual_video_folders"] = loaded["create_individual_media_folders"]

            if "add_number_to_filename" in loaded and "add_number_prefix" not in loaded:
                self._data["add_number_prefix"] = loaded["add_number_to_filename"]
            elif "add_number_prefix" in loaded and "add_number_to_filename" not in loaded:
                self._data["add_number_to_filename"] = loaded["add_number_prefix"]

            if "create_unique_filename" in loaded and "create_unique_folder" not in loaded:
                self._data["create_unique_folder"] = loaded["create_unique_filename"]
            elif "create_unique_folder" in loaded and "create_unique_filename" not in loaded:
                self._data["create_unique_filename"] = loaded["create_unique_folder"]

            if "unique_filename_folder" in loaded and "unique_folder_name" not in loaded:
                self._data["unique_folder_name"] = loaded["unique_filename_folder"]
            elif "unique_folder_name" in loaded and "unique_filename_folder" not in loaded:
                self._data["unique_filename_folder"] = loaded["unique_folder_name"]

        # Backward compatibility for auth_method: infer from browser_cookies if missing
        if "auth_method" not in loaded if 'loaded' in locals() and isinstance(loaded, dict) else True:
            b_cookies = str(self._data.get("browser_cookies", "none")).lower().strip()
            if b_cookies == "custom_file":
                self._data["auth_method"] = "custom_file"
            elif b_cookies in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi"):
                self._data["auth_method"] = "browser"
            else:
                self._data["auth_method"] = "none"

        from core.i18n import I18nManager
        I18nManager.set_language(self._data.get("language", "en"))
        return self._data

    def save(self) -> bool:
        """Saves current settings dictionary to the JSON file."""
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save settings to {self._settings_path}: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a setting value by key, falling back safely to YouTube if the saved platform is frozen."""
        val = self._data.get(key, default if default is not None else self.DEFAULT_SETTINGS.get(key))
        if key == "selected_platform" and val:
            try:
                from core.platform.detector import PlatformRegistry
                if not PlatformRegistry.is_available(str(val)):
                    return "youtube"
            except Exception:
                pass
        return val

    def set(self, key: str, value: Any) -> None:
        """Sets a setting value and saves to disk."""
        self._data[key] = value
        # Bidirectional alias synchronization
        if key == "include_video_id_in_filename":
            self._data["include_media_id_in_filename"] = value
        elif key == "include_media_id_in_filename":
            self._data["include_video_id_in_filename"] = value
        elif key == "skip_existing":
            self._data["skip_downloaded_media"] = value
        elif key == "skip_downloaded_media":
            self._data["skip_existing"] = value
        elif key == "create_individual_video_folders":
            self._data["create_individual_media_folders"] = value
        elif key == "create_individual_media_folders":
            self._data["create_individual_video_folders"] = value
        elif key == "add_number_to_filename":
            self._data["add_number_prefix"] = value
        elif key == "add_number_prefix":
            self._data["add_number_to_filename"] = value
        elif key == "create_unique_filename":
            self._data["create_unique_folder"] = value
        elif key == "create_unique_folder":
            self._data["create_unique_filename"] = value
        elif key == "unique_filename_folder":
            self._data["unique_folder_name"] = value
        elif key == "unique_folder_name":
            self._data["unique_filename_folder"] = value
        self.save()

    def get_all(self) -> Dict[str, Any]:
        """Returns a copy of all settings."""
        return dict(self._data)
