from __future__ import annotations

import io
import zipfile
import zlib
from typing import BinaryIO

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.core.settings import MIB
from app.services.archive_index import ArchiveError, indexed_zip

ASSETS = {
    "merged": ("mergedimage.png",),
    "preview": ("preview.png",),
    "thumbnail": ("Thumbnails/thumbnail.png", "thumbnail.png"),
}
_PNG = b"\x89PNG\r\n\x1a\n"


def _read_part(archive: zipfile.ZipFile, name: str, limit: int) -> bytes | None:
    try:
        part = archive.getinfo(name)
    except KeyError:
        return None
    if (
        part.file_size > limit
        or part.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        or part.flag_bits & 1
    ):
        return None
    try:
        with archive.open(part) as stream:
            data = stream.read(limit + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        return None
    return data if len(data) <= limit else None


def embedded_preview(source: BinaryIO, asset: str | None = None) -> io.BytesIO | None:
    candidates = (
        ASSETS[asset] if asset else tuple(name for names in ASSETS.values() for name in names)
    )
    try:
        with indexed_zip(source) as archive:
            for name in candidates:
                data = _read_part(archive, name, 16 * MIB)
                if data and data.startswith(_PNG):
                    return io.BytesIO(data)
    except ArchiveError:
        pass
    return None


def _number(value: str | None, limit: int) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal() or len(value) > 8:
        return None
    number = int(value)
    return number if number <= limit else None


def krita_details(source: BinaryIO) -> dict[str, object]:
    with indexed_zip(source) as archive:
        names = set(archive.namelist())
        assets = [key for key, candidates in ASSETS.items() if names.intersection(candidates)]
        xml = _read_part(archive, "maindoc.xml", 512 * 1024)
        width = height = None
        color_space = ""
        layers: list[dict[str, object]] = []
        if xml:
            try:
                root = ElementTree.fromstring(xml)
                image = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1].upper() == "IMAGE"
                    ),
                    None,
                )
            except (ElementTree.ParseError, DefusedXmlException) as exc:
                raise ArchiveError("Invalid Krita metadata") from exc
            if image is not None:
                width = _number(image.get("width"), 1_000_000)
                height = _number(image.get("height"), 1_000_000)
                color_space = (image.get("colorspacename") or "")[:128]
                pending = [(image, 0)]
                while pending and len(layers) < 2048:
                    node, depth = pending.pop()
                    tag = node.tag.rsplit("}", 1)[-1].lower()
                    if tag in {"layer", "mask"}:
                        layers.append(
                            {
                                "name": (node.get("name") or "Untitled")[:256],
                                "type": (node.get("nodetype") or tag)[:80],
                                "visible": node.get("visible", "1") not in {"0", "false"},
                                "opacity": _number(node.get("opacity"), 255),
                                "depth": depth,
                            }
                        )
                        depth += 1
                    if depth <= 32:
                        pending.extend((child, depth) for child in reversed(node))
        return {
            "assets": assets,
            "width": width,
            "height": height,
            "color_space": color_space,
            "layers": layers,
        }
