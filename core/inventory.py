"""
core/inventory.py
Persistent Profile Media Inventory for Channel Harvest.

Provides thread-safe local-first SQLite persistence for discovered profile posts and media:
1. Profile-level records and scan execution metadata.
2. Parent post records and author/metadata preservation.
3. Media-level records (images, videos, audio, carousels) with stable deduplication keys.
4. Resumable workflow support (persisting partial scans, pending items, download status).
"""

import sqlite3
import threading
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple

from core.paths import get_app_data_dir


# =============================================================================
# Constants & Enumerations
# =============================================================================

class ScanCompleteness:
    """Standardized scan completeness states."""
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class MediaInventoryType:
    """Standardized media classification types."""
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    REEL = "REEL"
    AUDIO = "AUDIO"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


class MediaDownloadStatus:
    """Download status for individual inventory media items."""
    PENDING = "PENDING"
    WAITING = "WAITING"
    DOWNLOADING = "DOWNLOADING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class ProfileRecord:
    platform: str
    profile_url: str
    profile_id: Optional[str] = None
    display_name: Optional[str] = None
    scan_id: Optional[str] = None
    scan_start_time: Optional[str] = None
    scan_end_time: Optional[str] = None
    scan_status: str = ScanCompleteness.PARTIAL
    scan_completeness_info: Optional[str] = None
    discovered_posts_count: int = 0
    discovered_media_count: int = 0
    downloaded_count: int = 0
    failed_count: int = 0
    last_error_summary: Optional[str] = None


@dataclass
class PostRecord:
    platform: str
    post_id: str
    profile_id: Optional[str] = None
    profile_url: Optional[str] = None
    original_url: Optional[str] = None
    canonical_url: Optional[str] = None
    caption: Optional[str] = None
    author: Optional[str] = None
    publication_date: Optional[str] = None
    post_type: Optional[str] = None  # photo, video, carousel, album
    discovery_source: str = "unknown"
    discovery_timestamp: Optional[str] = None


@dataclass
class MediaItemRecord:
    media_id: str
    platform: str
    parent_post_id: Optional[str] = None
    media_url: Optional[str] = None
    media_type: str = MediaInventoryType.UNKNOWN
    media_sequence_index: int = 1
    media_count: Optional[int] = None
    mime_type: Optional[str] = None
    extension: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    discovery_source: str = "unknown"
    preferred_engine: str = "auto"
    selected_engine: str = "auto"
    download_status: str = MediaDownloadStatus.PENDING
    output_path: Optional[str] = None
    file_size: Optional[int] = None
    last_error: Optional[str] = None
    last_attempt_timestamp: Optional[str] = None
    completed_timestamp: Optional[str] = None


# =============================================================================
# Stable Identity & Deduplication Helpers
# =============================================================================

def generate_stable_media_id(
    platform: str,
    platform_media_id: Optional[str] = None,
    post_id: Optional[str] = None,
    media_sequence_index: int = 1,
    media_url: Optional[str] = None,
) -> str:
    """
    Generates deterministic stable media identity adhering to priority:
    1. Stable platform media ID.
    2. Stable post ID combined with media sequence index.
    3. Canonical media URL reference.
    4. Fallback SHA-256 hash.
    """
    clean_pid = str(post_id).strip() if post_id else ""
    if platform_media_id and str(platform_media_id).strip():
        clean_pmid = str(platform_media_id).strip()
        if clean_pid and clean_pmid == clean_pid:
            return f"{platform}_{clean_pmid}_{media_sequence_index}"
        return f"{platform}_{clean_pmid}"

    if post_id and str(post_id).strip():
        clean_pid = str(post_id).strip()
        return f"{platform}_{clean_pid}_{media_sequence_index}"

    if media_url and str(media_url).strip():
        clean_url = str(media_url).strip().split("?")[0]
        url_hash = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()[:16]
        return f"{platform}_url_{url_hash}_{media_sequence_index}"

    fallback_entropy = f"{platform}_{time.time_ns()}_{media_sequence_index}"
    return f"{platform}_fb_{hashlib.sha256(fallback_entropy.encode()).hexdigest()[:16]}"


# =============================================================================
# Persistent Profile Media Inventory Storage
# =============================================================================

class ProfileMediaInventory:
    """
    Local-first SQLite storage for discovered profiles, posts, and media items.
    Thread-safe connection handling and transaction isolation.
    """

    _DEFAULT_DB_FILENAME = "profile_inventory.db"

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            self.db_path = get_app_data_dir() / self._DEFAULT_DB_FILENAME
        else:
            self.db_path = Path(db_path)

        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns thread-local sqlite3 connection with WAL mode enabled."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            if str(self.db_path) != ":memory:":
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for high concurrent read/write throughput
            if str(self.db_path) != ":memory:":
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except Exception:
                    pass
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._local.conn = conn
        return self._local.conn

    def _init_database(self) -> None:
        """Creates database schema if not already initialized."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    platform TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    profile_id TEXT,
                    display_name TEXT,
                    scan_id TEXT,
                    scan_start_time TEXT,
                    scan_end_time TEXT,
                    scan_status TEXT DEFAULT 'PARTIAL',
                    scan_completeness_info TEXT,
                    discovered_posts_count INTEGER DEFAULT 0,
                    discovered_media_count INTEGER DEFAULT 0,
                    downloaded_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    last_error_summary TEXT,
                    PRIMARY KEY (platform, profile_url)
                );

                CREATE TABLE IF NOT EXISTS posts (
                    platform TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    profile_id TEXT,
                    profile_url TEXT,
                    original_url TEXT,
                    canonical_url TEXT,
                    caption TEXT,
                    author TEXT,
                    publication_date TEXT,
                    post_type TEXT,
                    discovery_source TEXT,
                    discovery_timestamp TEXT,
                    PRIMARY KEY (platform, post_id)
                );

                CREATE TABLE IF NOT EXISTS media_items (
                    media_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    parent_post_id TEXT,
                    media_url TEXT,
                    media_type TEXT DEFAULT 'UNKNOWN',
                    media_sequence_index INTEGER DEFAULT 1,
                    media_count INTEGER,
                    mime_type TEXT,
                    extension TEXT,
                    width INTEGER,
                    height INTEGER,
                    duration REAL,
                    discovery_source TEXT,
                    preferred_engine TEXT DEFAULT 'auto',
                    selected_engine TEXT DEFAULT 'auto',
                    download_status TEXT DEFAULT 'PENDING',
                    output_path TEXT,
                    file_size INTEGER,
                    last_error TEXT,
                    last_attempt_timestamp TEXT,
                    completed_timestamp TEXT,
                    PRIMARY KEY (platform, media_id)
                );

                CREATE INDEX IF NOT EXISTS idx_posts_profile ON posts(platform, profile_id);
                CREATE INDEX IF NOT EXISTS idx_media_parent ON media_items(platform, parent_post_id);
                CREATE INDEX IF NOT EXISTS idx_media_status ON media_items(platform, download_status);
                """)

    def close(self) -> None:
        """Closes thread-local database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    def __del__(self):
        self.close()

    # -------------------------------------------------------------------------
    # Profile Operations
    # -------------------------------------------------------------------------

    def upsert_profile(self, profile: ProfileRecord) -> None:
        """Inserts or updates a profile inventory record."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                INSERT INTO profiles (
                    platform, profile_url, profile_id, display_name, scan_id,
                    scan_start_time, scan_end_time, scan_status, scan_completeness_info,
                    discovered_posts_count, discovered_media_count, downloaded_count,
                    failed_count, last_error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, profile_url) DO UPDATE SET
                    profile_id = COALESCE(excluded.profile_id, profiles.profile_id),
                    display_name = COALESCE(excluded.display_name, profiles.display_name),
                    scan_id = COALESCE(excluded.scan_id, profiles.scan_id),
                    scan_start_time = COALESCE(excluded.scan_start_time, profiles.scan_start_time),
                    scan_end_time = COALESCE(excluded.scan_end_time, profiles.scan_end_time),
                    scan_status = excluded.scan_status,
                    scan_completeness_info = COALESCE(excluded.scan_completeness_info, profiles.scan_completeness_info),
                    discovered_posts_count = excluded.discovered_posts_count,
                    discovered_media_count = excluded.discovered_media_count,
                    downloaded_count = excluded.downloaded_count,
                    failed_count = excluded.failed_count,
                    last_error_summary = excluded.last_error_summary;
                """, (
                    profile.platform, profile.profile_url, profile.profile_id,
                    profile.display_name, profile.scan_id, profile.scan_start_time,
                    profile.scan_end_time, profile.scan_status, profile.scan_completeness_info,
                    profile.discovered_posts_count, profile.discovered_media_count,
                    profile.downloaded_count, profile.failed_count, profile.last_error_summary
                ))

    def get_profile(self, platform: str, profile_url: str) -> Optional[ProfileRecord]:
        """Retrieves profile record by platform and profile URL."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute("""
                SELECT * FROM profiles WHERE platform = ? AND profile_url = ?;
            """, (platform, profile_url)).fetchone()
            if row:
                return ProfileRecord(**dict(row))
            return None

    def update_profile_scan_status(
        self,
        platform: str,
        profile_url: str,
        scan_status: str,
        scan_end_time: Optional[str] = None,
        completeness_info: Optional[str] = None,
        last_error_summary: Optional[str] = None,
    ) -> None:
        """Updates scan completeness and terminal status for a profile."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                UPDATE profiles SET
                    scan_status = ?,
                    scan_end_time = COALESCE(?, scan_end_time),
                    scan_completeness_info = COALESCE(?, scan_completeness_info),
                    last_error_summary = COALESCE(?, last_error_summary)
                WHERE platform = ? AND profile_url = ?;
                """, (
                    scan_status, scan_end_time, completeness_info,
                    last_error_summary, platform, profile_url
                ))

    # -------------------------------------------------------------------------
    # Post Operations
    # -------------------------------------------------------------------------

    def upsert_post(self, post: PostRecord) -> None:
        """Inserts or updates a post record in inventory."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                INSERT INTO posts (
                    platform, post_id, profile_id, profile_url, original_url,
                    canonical_url, caption, author, publication_date, post_type,
                    discovery_source, discovery_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, post_id) DO UPDATE SET
                    profile_id = COALESCE(excluded.profile_id, posts.profile_id),
                    profile_url = COALESCE(excluded.profile_url, posts.profile_url),
                    original_url = COALESCE(excluded.original_url, posts.original_url),
                    canonical_url = COALESCE(excluded.canonical_url, posts.canonical_url),
                    caption = COALESCE(excluded.caption, posts.caption),
                    author = COALESCE(excluded.author, posts.author),
                    publication_date = COALESCE(excluded.publication_date, posts.publication_date),
                    post_type = COALESCE(excluded.post_type, posts.post_type),
                    discovery_source = excluded.discovery_source,
                    discovery_timestamp = COALESCE(excluded.discovery_timestamp, posts.discovery_timestamp);
                """, (
                    post.platform, post.post_id, post.profile_id, post.profile_url,
                    post.original_url, post.canonical_url, post.caption, post.author,
                    post.publication_date, post.post_type, post.discovery_source,
                    post.discovery_timestamp
                ))

    def get_post(self, platform: str, post_id: str) -> Optional[PostRecord]:
        """Retrieves a post by platform and post ID."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute("""
                SELECT * FROM posts WHERE platform = ? AND post_id = ?;
            """, (platform, post_id)).fetchone()
            if row:
                return PostRecord(**dict(row))
            return None

    def get_posts_for_profile(self, platform: str, profile_id_or_url: str) -> List[PostRecord]:
        """Retrieves all posts associated with a profile."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute("""
                SELECT * FROM posts
                WHERE platform = ? AND (profile_id = ? OR profile_url = ?)
                ORDER BY publication_date DESC, rowid DESC;
            """, (platform, profile_id_or_url, profile_id_or_url)).fetchall()
            return [PostRecord(**dict(r)) for r in rows]

    # -------------------------------------------------------------------------
    # Media Item Operations
    # -------------------------------------------------------------------------

    def upsert_media_item(self, item: MediaItemRecord) -> None:
        """Inserts or updates a media item record with deduplication protection."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                INSERT INTO media_items (
                    media_id, platform, parent_post_id, media_url, media_type,
                    media_sequence_index, media_count, mime_type, extension,
                    width, height, duration, discovery_source, preferred_engine,
                    selected_engine, download_status, output_path, file_size,
                    last_error, last_attempt_timestamp, completed_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, media_id) DO UPDATE SET
                    parent_post_id = COALESCE(excluded.parent_post_id, media_items.parent_post_id),
                    media_url = COALESCE(excluded.media_url, media_items.media_url),
                    media_type = excluded.media_type,
                    media_sequence_index = excluded.media_sequence_index,
                    media_count = COALESCE(excluded.media_count, media_items.media_count),
                    mime_type = COALESCE(excluded.mime_type, media_items.mime_type),
                    extension = COALESCE(excluded.extension, media_items.extension),
                    width = COALESCE(excluded.width, media_items.width),
                    height = COALESCE(excluded.height, media_items.height),
                    duration = COALESCE(excluded.duration, media_items.duration),
                    preferred_engine = excluded.preferred_engine,
                    selected_engine = excluded.selected_engine,
                    output_path = COALESCE(excluded.output_path, media_items.output_path),
                    file_size = COALESCE(excluded.file_size, media_items.file_size);
                """, (
                    item.media_id, item.platform, item.parent_post_id, item.media_url,
                    item.media_type, item.media_sequence_index, item.media_count,
                    item.mime_type, item.extension, item.width, item.height, item.duration,
                    item.discovery_source, item.preferred_engine, item.selected_engine,
                    item.download_status, item.output_path, item.file_size,
                    item.last_error, item.last_attempt_timestamp, item.completed_timestamp
                ))

    def get_media_item(self, platform: str, media_id: str) -> Optional[MediaItemRecord]:
        """Retrieves a media item record by platform and media ID."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute("""
                SELECT * FROM media_items WHERE platform = ? AND media_id = ?;
            """, (platform, media_id)).fetchone()
            if row:
                return MediaItemRecord(**dict(row))
            return None

    def get_media_items_for_post(self, platform: str, post_id: str) -> List[MediaItemRecord]:
        """Retrieves all media items belonging to a parent post ordered by sequence."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute("""
                SELECT * FROM media_items
                WHERE platform = ? AND parent_post_id = ?
                ORDER BY media_sequence_index ASC, rowid ASC;
            """, (platform, post_id)).fetchall()
            return [MediaItemRecord(**dict(r)) for r in rows]

    def get_media_items_for_profile(self, platform: str, profile_id_or_url: str) -> List[MediaItemRecord]:
        """Retrieves all media items across all posts of a profile."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute("""
                SELECT m.* FROM media_items m
                INNER JOIN posts p ON m.platform = p.platform AND m.parent_post_id = p.post_id
                WHERE p.platform = ? AND (p.profile_id = ? OR p.profile_url = ?)
                ORDER BY p.publication_date DESC, m.media_sequence_index ASC;
            """, (platform, profile_id_or_url, profile_id_or_url)).fetchall()
            return [MediaItemRecord(**dict(r)) for r in rows]

    def get_pending_media_items(self, platform: str, profile_id_or_url: Optional[str] = None) -> List[MediaItemRecord]:
        """Retrieves media items pending or failed for download retry."""
        with self._lock:
            conn = self._get_connection()
            if profile_id_or_url:
                rows = conn.execute("""
                    SELECT m.* FROM media_items m
                    INNER JOIN posts p ON m.platform = p.platform AND m.parent_post_id = p.post_id
                    WHERE p.platform = ? AND (p.profile_id = ? OR p.profile_url = ?)
                      AND m.download_status IN ('PENDING', 'WAITING', 'FAILED')
                    ORDER BY p.publication_date DESC, m.media_sequence_index ASC;
                """, (platform, profile_id_or_url, profile_id_or_url)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM media_items
                    WHERE platform = ? AND download_status IN ('PENDING', 'WAITING', 'FAILED')
                    ORDER BY rowid ASC;
                """, (platform,)).fetchall()
            return [MediaItemRecord(**dict(r)) for r in rows]

    def update_media_download_status(
        self,
        platform: str,
        media_id: str,
        status: str,
        output_path: Optional[str] = None,
        file_size: Optional[int] = None,
        last_error: Optional[str] = None,
        selected_engine: Optional[str] = None,
    ) -> None:
        """Updates download status, output path, and errors for a media item."""
        with self._lock:
            conn = self._get_connection()
            now_str = datetime.now(timezone.utc).isoformat()
            completed_str = now_str if status == MediaDownloadStatus.COMPLETED else None

            with conn:
                conn.execute("""
                UPDATE media_items SET
                    download_status = ?,
                    output_path = COALESCE(?, output_path),
                    file_size = COALESCE(?, file_size),
                    last_error = ?,
                    selected_engine = COALESCE(?, selected_engine),
                    last_attempt_timestamp = ?,
                    completed_timestamp = COALESCE(?, completed_timestamp)
                WHERE platform = ? AND media_id = ?;
                """, (
                    status, output_path, file_size, last_error,
                    selected_engine, now_str, completed_str,
                    platform, media_id
                ))

    def get_inventory_summary(self, platform: str, profile_url: str) -> Dict[str, Any]:
        """Calculates live summary counts directly from the inventory database."""
        with self._lock:
            conn = self._get_connection()
            p_row = conn.execute("""
                SELECT * FROM profiles WHERE platform = ? AND profile_url = ?;
            """, (platform, profile_url)).fetchone()

            post_count = conn.execute("""
                SELECT COUNT(*) FROM posts WHERE platform = ? AND profile_url = ?;
            """, (platform, profile_url)).fetchone()[0]

            media_stats = conn.execute("""
                SELECT
                    COUNT(*) as total_media,
                    SUM(CASE WHEN m.media_type = 'IMAGE' THEN 1 ELSE 0 END) as image_count,
                    SUM(CASE WHEN m.media_type = 'VIDEO' THEN 1 ELSE 0 END) as video_count,
                    SUM(CASE WHEN m.media_type NOT IN ('IMAGE', 'VIDEO') THEN 1 ELSE 0 END) as other_count,
                    SUM(CASE WHEN m.download_status = 'COMPLETED' THEN 1 ELSE 0 END) as downloaded_count,
                    SUM(CASE WHEN m.download_status = 'FAILED' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN m.download_status = 'SKIPPED' THEN 1 ELSE 0 END) as skipped_count
                FROM media_items m
                INNER JOIN posts p ON m.platform = p.platform AND m.parent_post_id = p.post_id
                WHERE p.platform = ? AND p.profile_url = ?;
            """, (platform, profile_url)).fetchone()

            return {
                "platform": platform,
                "profile_url": profile_url,
                "profile": dict(p_row) if p_row else None,
                "posts_count": post_count,
                "media_count": media_stats["total_media"] or 0,
                "image_count": media_stats["image_count"] or 0,
                "video_count": media_stats["video_count"] or 0,
                "other_count": media_stats["other_count"] or 0,
                "downloaded_count": media_stats["downloaded_count"] or 0,
                "failed_count": media_stats["failed_count"] or 0,
                "skipped_count": media_stats["skipped_count"] or 0,
            }
