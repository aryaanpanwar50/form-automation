"""Render the application SVG icon as a macOS .icns file."""

from __future__ import annotations

import ast
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def read_app_icon_svg() -> str:
    desktop_source = (
        Path(__file__).resolve().parents[1] / "src" / "form_automation" / "desktop.py"
    )
    module = ast.parse(desktop_source.read_text(encoding="utf-8"))
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "APP_ICON_SVG"
            for target in statement.targets
        ):
            value = ast.literal_eval(statement.value)
            if isinstance(value, str):
                return value
    raise RuntimeError("APP_ICON_SVG was not found in desktop.py")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "assets" / "form-automation.icns"
    renderer = QSvgRenderer(QByteArray(read_app_icon_svg().encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("The app SVG icon could not be loaded")

    chunks: list[bytes] = []
    # Modern ICNS files hold PNG data.  The tags are Apple's standard size tags.
    for tag, size in (
        (b"icp4", 16),
        (b"icp5", 32),
        (b"icp6", 64),
        (b"ic07", 128),
        (b"ic08", 256),
        (b"ic09", 512),
        (b"ic10", 1024),
    ):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not render the {size}px macOS icon")
        png_data = bytes(buffer.data())
        chunks.append(tag + struct.pack(">I", len(png_data) + 8) + png_data)

    contents = b"".join(chunks)
    destination.write_bytes(b"icns" + struct.pack(">I", len(contents) + 8) + contents)
    print(f"Generated {destination}")


if __name__ == "__main__":
    main()
