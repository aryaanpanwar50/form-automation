"""Render the application SVG icon as a macOS .icns file."""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
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
    iconset = root / "assets" / "form-automation.iconset"
    destination = root / "assets" / "form-automation.icns"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True)
    renderer = QSvgRenderer(QByteArray(read_app_icon_svg().encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("The app SVG icon could not be loaded")

    for points in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = points * scale
            image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            suffix = "" if scale == 1 else "@2x"
            if not image.save(str(iconset / f"icon_{points}x{points}{suffix}.png")):
                raise RuntimeError(f"Could not render the {pixels}px macOS icon")

    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(destination)], check=True)
    shutil.rmtree(iconset)
    print(f"Generated {destination}")


if __name__ == "__main__":
    main()
