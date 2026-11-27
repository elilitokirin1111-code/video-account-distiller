"""Render the code-owned SVG application mark to a Windows ICO file."""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()

    app = QGuiApplication([])
    renderer = QSvgRenderer(str(arguments.source.resolve()))
    if not renderer.isValid():
        raise SystemExit(f"Invalid SVG: {arguments.source}")
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(QColor(Qt.GlobalColor.transparent))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 256, 256))
    painter.end()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(arguments.output.resolve()), "ICO"):
        raise SystemExit(f"Could not write ICO: {arguments.output}")
    app.quit()


if __name__ == "__main__":
    main()
