"""
metadata package
Platform-specific metadata TXT templates and exporter for Channel Harvest.
"""

from metadata.base_formatter import BaseMetadataFormatter
from metadata.youtube_formatter import YouTubeMetadataFormatter
from metadata.tiktok_formatter import TikTokMetadataFormatter
from metadata.bilibili_formatter import BilibiliMetadataFormatter
from metadata.facebook_formatter import FacebookMetadataFormatter
from metadata.instagram_formatter import InstagramMetadataFormatter
from metadata.x_formatter import XMetadataFormatter
from metadata.generic_formatter import GenericMetadataFormatter
from metadata.metadata_exporter import MetadataExporter

__all__ = [
    "BaseMetadataFormatter",
    "YouTubeMetadataFormatter",
    "TikTokMetadataFormatter",
    "BilibiliMetadataFormatter",
    "FacebookMetadataFormatter",
    "InstagramMetadataFormatter",
    "XMetadataFormatter",
    "GenericMetadataFormatter",
    "MetadataExporter",
]
