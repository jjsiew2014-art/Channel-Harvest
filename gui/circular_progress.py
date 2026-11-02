"""
circular_progress.py
Lightweight circular spinner / progress indicator for Channel Harvest.
Displays an animated rotating arc during scanning and can optionally display determinate progress.
"""

from typing import Optional
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPaintEvent


class CircularProgressIndicator(QWidget):
    """
    Circular progress indicator displayed between the source URL input and scan button.
    Renders a smooth, anti-aliased rotating spinner arc while a scan is in progress.
    """

    def __init__(self, parent: Optional[QWidget] = None, size: int = 24):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._is_spinning: bool = False
        self._angle: int = 0
        self._progress: Optional[float] = None

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._on_timer_tick)
        self.setVisible(False)

    @property
    def is_spinning(self) -> bool:
        return self._is_spinning

    def start_spinning(self) -> None:
        """Starts rotation animation and makes widget visible."""
        self._is_spinning = True
        self._angle = 0
        self._progress = None
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop_spinning(self) -> None:
        """Stops animation and hides the spinner."""
        self._is_spinning = False
        self._timer.stop()
        self._angle = 0
        self._progress = None
        self.setVisible(False)
        self.update()

    def set_progress(self, percent: Optional[float]) -> None:
        """
        Sets determinate progress (0.0 - 100.0) or None for indeterminate spinning.
        """
        self._progress = percent
        if percent is not None and not self.isVisible():
            self.setVisible(True)
        self.update()

    def _on_timer_tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.isVisible():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        pen_width = 2.5
        margin = pen_width / 2.0 + 1.0
        rect = QRectF(margin, margin, width - 2 * margin, height - 2 * margin)

        # Draw subtle track ring
        track_color = QColor(148, 163, 184, 70)  # Slate-400 with alpha
        track_pen = QPen(track_color, pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)

        # Draw active spinner / progress arc
        accent_color = QColor(2, 132, 199)  # Vibrant primary sky-blue (#0284c7)
        arc_pen = QPen(accent_color, pen_width)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)

        if self._progress is not None:
            # Determinate arc from 12 o'clock (90 degrees in Qt) clockwise
            span_angle = int(-(self._progress / 100.0) * 360 * 16)
            painter.drawArc(rect, 90 * 16, span_angle)
        else:
            # Indeterminate rotating arc (100-degree arc spinning clockwise)
            start_angle = int(-self._angle * 16)
            span_angle = int(-100 * 16)
            painter.drawArc(rect, start_angle, span_angle)

        painter.end()
