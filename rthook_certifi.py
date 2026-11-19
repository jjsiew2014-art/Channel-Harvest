"""PyInstaller runtime hook ensuring `certifi.where()` works before any app imports."""

from core.paths import ensure_certifi_bundle

ensure_certifi_bundle()
