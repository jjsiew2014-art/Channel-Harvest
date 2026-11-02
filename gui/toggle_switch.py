"""
toggle_switch.py
Modern pill-shaped animated toggle switch control for Channel Harvest.

Designed to match contemporary macOS / Windows 11 switch aesthetics:
- Smooth animated sliding white thumb
- Distinct ON / OFF pill tracks adapted to Light and Dark themes
- Fully accessible via standard isChecked(), setChecked(bool), toggled(bool) signals
"""

from typing import Optional
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from gui.styles import ThemeManager


class ToggleSwitch(QAbstractButton):
    """
    Modern pill-shaped toggle switch control.
    Supports isChecked(), setChecked(bool), toggled(bool) with animated thumb transition.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._thumb_position = 0.0  # 0.0 = left (OFF), 1.0 = right (ON)

        self._anim = QPropertyAnimation(self, b"thumb_position", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._handle_toggled)

    def _get_thumb_position(self) -> float:
        return self._thumb_position

    def _set_thumb_position(self, pos: float) -> None:
        self._thumb_position = pos
        self.update()

    thumb_position = Property(float, _get_thumb_position, _set_thumb_position)

    def _handle_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._thumb_position = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        r = h / 2.0

        is_dark = ThemeManager.is_dark()

        # Track background color
        if self.isChecked():
            track_color = QColor("#2563eb") if is_dark else QColor("#0066cc")
        else:
            track_color = QColor("#374151") if is_dark else QColor("#cbd5e1")

        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Thumb
        margin = 3.0
        thumb_size = h - 2 * margin
        start_x = margin
        end_x = w - margin - thumb_size
        current_x = start_x + (end_x - start_x) * self._thumb_position

        # White thumb knob
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(current_x, margin, thumb_size, thumb_size))
