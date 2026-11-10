from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.services.file_names import normalize_name
from app.services.metadata import Metadata
from utils import decode_key


class LegacyEntry(BaseModel):
    stored_path: str
    stored_as_compressed: bool
    compression_algorithm: str
    original_size: int = Field(ge=0)
    stored_size: int = Field(ge=0)
    compression_percent: float
    mime: str
    category: str
    preview_profiled: bool = False


def read_legacy_metadata(path: Path) -> Metadata:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Invalid metadata object")
        result: Metadata = {}
        for encoded, value in raw.items():
            name = decode_key(encoded)
            if normalize_name(name, 32) != name or name in result:
                raise ValueError("Invalid legacy filename")
            entry = LegacyEntry.model_validate(value)
            if not math.isfinite(entry.compression_percent):
                raise ValueError("Invalid compression value")
            result[name] = {
                "stored_path": entry.stored_path,
                "stored_as_compressed": entry.stored_as_compressed,
                "compression_algorithm": entry.compression_algorithm,
                "original_size": entry.original_size,
                "stored_size": entry.stored_size,
                "compression_percent": entry.compression_percent,
                "mime": entry.mime,
                "category": entry.category,
                "preview_profiled": entry.preview_profiled,
            }
        return result
    except (ValueError, OSError, ValidationError) as exc:
        raise HTTPException(
            409, "Legacy file metadata could not be migrated; original data was retained"
        ) from exc
