"""Render the desktop app SVG icon into a multi-size Windows .ico file."""

from __future__ import annotations

import ast
import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def read_app_icon_svg() -> str:
    desktop_source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "form_automation"
        / "desktop.py"
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
    renderer = QSvgRenderer(QByteArray(read_app_icon_svg().encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("The app SVG icon could not be loaded")

    images: list[tuple[int, bytes]] = []
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()

        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Could not allocate an icon image buffer")
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode the {size}px icon image")
        images.append((size, bytes(buffer.data())))

    header_size = 6 + 16 * len(images)
    offset = header_size
    directory_entries = bytearray()
    image_data = bytearray()
    for size, png_data in images:
        dimension = 0 if size == 256 else size
        directory_entries.extend(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(png_data),
                offset,
            )
        )
        image_data.extend(png_data)
        offset += len(png_data)

    destination = Path(__file__).resolve().parents[1] / "assets" / "form-automation.ico"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        struct.pack("<HHH", 0, 1, len(images)) + directory_entries + image_data
    )
    print(f"Generated {destination}")


if __name__ == "__main__":
    main()
