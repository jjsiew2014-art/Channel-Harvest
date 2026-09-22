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
from typing import Any, Dict

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
        "save_description": False,
        "save_metadata": False,
        "save_chapters": False,
        "create_channel_folder": True,
        "create_individual_video_folders": False,

        "skip_existing": False,
        "window_width": 1200,
        "window_height": 960,
        "last_channel_url": "https://www.youtube.com/@PythonSimplified",
        "theme": "System",
        "language": "en",
        "auth_method": "none",
        "browser_cookies": "none",
        "browser_profile": "Default",
        "custom_cookie_file": "",
        "last_auth_status": "NOT_CONFIGURED",
        "auto_check_ytdlp_updates": True,
        "auto_check_runtime_updates": True,
        "last_ytdlp_update_check": 0.0,
        "last_runtime_update_check": 0.0,
    }

    def __init__(self, settings_path: Optional[Path] = None):
        self._settings_path = settings_path or get_settings_file()
        self._data: Dict[str, Any] = dict(self.DEFAULT_SETTINGS)
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from JSON file or initializes with defaults."""
        if not self._settings_path.exists():
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
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save settings to {self._settings_path}: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a setting value by key."""
        return self._data.get(key, default if default is not None else self.DEFAULT_SETTINGS.get(key))

    def set(self, key: str, value: Any) -> None:
        """Sets a setting value and saves to disk."""
        self._data[key] = value
        self.save()

    def get_all(self) -> Dict[str, Any]:
        """Returns a copy of all settings."""
        return dict(self._data)
