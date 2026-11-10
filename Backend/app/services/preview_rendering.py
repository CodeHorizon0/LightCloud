from __future__ import annotations

import io
from typing import BinaryIO

from PIL import Image, ImageOps

from app.services.archive_index import archive_index
from app.services.compression.manager import decompress_chunks
from app.services.krita import embedded_preview, krita_details
from app.services.preview_policy import PreviewKind

MAX_PREVIEW_PIXELS = 24_000_000


def _image_preview(source: BinaryIO, *, alpha: bool = False) -> bytes | None:
    try:
        with Image.open(source) as image:
            if image.width * image.height > MAX_PREVIEW_PIXELS:
                return None
            image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            oriented = ImageOps.exif_transpose(image)
            output = io.BytesIO()
            if alpha:
                oriented.convert("RGBA").save(output, "PNG", compress_level=3)
                return output.getvalue()
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                converted = Image.new("RGB", rgba.size, "white")
                converted.paste(rgba, mask=rgba.getchannel("A"))
            else:
                converted = oriented.convert("RGB")
            converted.save(output, "JPEG", quality=76, progressive=True, optimize=True)
            return output.getvalue()
    except (Image.DecompressionBombError, OSError, ValueError):
        return None


def render_preview(
    source: BinaryIO,
    frame: tuple[str, int, bytes] | None,
    kind: PreviewKind,
    mime: str,
    view: str,
    asset: str | None,
) -> bytes | dict[str, object] | None:
    if frame is not None:
        with io.BytesIO() as decoded:
            for chunk in decompress_chunks(source, frame):
                decoded.write(chunk)
            decoded.seek(0)
            return render_preview(decoded, None, kind, mime, view, asset)
    if kind == "archive":
        return archive_index(source, mime)
    if kind == "krita":
        if view == "details":
            return krita_details(source)
        embedded = embedded_preview(source, asset)
        if embedded is None:
            return None
        with embedded:
            return _image_preview(embedded, alpha=asset is not None)
    return _image_preview(source)
