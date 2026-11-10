from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException

from app.services.metadata import Metadata, MetadataSnapshot
from app.services.preview_policy import file_revision

SYNC_INTERVAL = 1
MAX_REVISIONS_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class SyncSnapshot:
    account: str
    cursor: str
    files: dict[str, dict[str, object]]

    @classmethod
    def from_metadata(cls, account: UUID, snapshot: MetadataSnapshot) -> SyncSnapshot:
        files: dict[str, dict[str, object]] = json.loads(snapshot.data)
        canonical = json.dumps(
            files,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        cursor = hashlib.sha256(f"{account}\0{canonical}".encode()).hexdigest()
        return cls(str(account), cursor, files)

    def payload(self) -> dict[str, object]:
        return {
            "protocol": 1,
            "account": self.account,
            "cursor": self.cursor,
            "files": self.files,
        }

    def patch(self, previous: SyncSnapshot) -> dict[str, object]:
        return {
            "protocol": 1,
            "account": self.account,
            "from": previous.cursor,
            "cursor": self.cursor,
            "upsert": {
                name: entry
                for name, entry in self.files.items()
                if previous.files.get(name) != entry
            },
            "deleted": [name for name in previous.files if name not in self.files],
        }


def check_revisions(metadata: Metadata, names: list[str], revisions: dict[str, str | None]) -> None:
    if set(names) != revisions.keys():
        raise HTTPException(400, "A base revision is required for every file")
    conflicts = []
    for name in names:
        current = file_revision(metadata[name]) if name in metadata else None
        if revisions[name] != current:
            conflicts.append({"path": name, "expected": revisions[name], "current": current})
    if conflicts:
        raise HTTPException(
            409,
            {
                "code": "sync_conflict",
                "detail": "Files changed on another device. Account updates arrive automatically. Keep the server version or save a copy.",
                "conflicts": conflicts,
            },
        )


def parse_revisions(value: object) -> dict[str, str | None]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_REVISIONS_BYTES:
        raise HTTPException(400, "Invalid file revisions")
    try:
        data: object = json.loads(value)
    except ValueError as exc:
        raise HTTPException(400, "Invalid file revisions") from exc
    if not isinstance(data, dict) or len(data) > 1000:
        raise HTTPException(400, "Invalid file revisions")
    result: dict[str, str | None] = {}
    for name, revision in data.items():
        if not isinstance(name, str) or (
            revision is not None
            and (
                not isinstance(revision, str)
                or len(revision) != 24
                or any(char not in "0123456789abcdef" for char in revision)
            )
        ):
            raise HTTPException(400, "Invalid file revisions")
        result[name] = revision
    return result
