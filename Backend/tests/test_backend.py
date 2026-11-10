from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import struct
import tarfile
import tempfile
import threading
import unittest
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import bcrypt
import jwt
from fastapi.testclient import TestClient
from PIL import Image
from starlette.types import Message, Scope

from app.core.auth_helper import JWTService
from app.core.settings import Settings
from app.services.compression import CompressionError, CompressionManager
from main import create_app
from utils import encode_key

PASSWORD = "test-password"
SECRET = "test-key-" * 9


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.settings = Settings(
            storage_dir=self.root / "storage",
            database_file=self.root / "users.db",
            jwt_secret=SECRET,
            max_file_size_mb=1,
            max_batch_size_mb=1,
            max_upload_files=2,
            user_quota_mb=2,
            allowed_hosts=["testserver"],
        )
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app))

    def register(self, username: str = "Alice") -> UUID:
        response = self.client.post(
            "/auth/register", json={"username": username, "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return UUID(response.json()["id"])

    def login(self, username: str = "Alice") -> str:
        response = self.client.post(
            "/auth/login", json={"username": username, "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        return str(self.client.cookies["access_token"])

    def upload(self, name: str, data: bytes) -> int:
        return self.client.post("/upload", files={"files": (name, data)}).status_code

    def test_public_and_protected_routes(self) -> None:
        for method, path in (
            ("GET", "/auth/me"),
            ("GET", "/metadata/stream"),
            ("GET", "/preview/file.txt"),
            ("GET", "/download/file.txt"),
            ("DELETE", "/delete/file.txt"),
            ("DELETE", "/auth/delete"),
            ("POST", "/upload"),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method, path).status_code, 401)

    def test_auth_csrf_and_host(self) -> None:
        self.register("  Alice  ")
        self.login()
        self.assertEqual(self.client.get("/auth/me").json()["user"]["username"], "Alice")
        self.assertEqual(
            self.client.get("/auth/me", headers={"Host": "attacker.test"}).status_code, 400
        )
        self.assertEqual(
            self.client.delete(
                "/auth/delete", headers={"Origin": "https://attacker.test"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                "/auth/delete", headers={"Sec-Fetch-Site": "cross-site"}
            ).status_code,
            403,
        )
        response = self.client.delete(
            "/delete/missing", headers={"Origin": "http://localhost:5173"}
        )
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertEqual(response.status_code, 200)

    def test_logout_revokes_only_current_session_then_logout_all(self) -> None:
        self.register()
        first = self.login()
        second = self.login()
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)
        self.assertEqual(
            self.client.get("/auth/me", headers={"Cookie": f"access_token={second}"}).status_code,
            401,
        )
        self.client.cookies.set("access_token", first, domain="testserver.local", path="/")
        self.assertEqual(self.client.post("/auth/logout-all").status_code, 200)
        response = self.client.get("/auth/me", headers={"Cookie": f"access_token={first}"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_version_mismatch")

    def test_expired_and_incomplete_tokens(self) -> None:
        user = self.register()
        expired = JWTService(SECRET, "HS512").create_access_token(
            user, "Alice", 1, timedelta(seconds=-5)
        )
        response = self.client.get("/auth/me", headers={"Cookie": f"access_token={expired}"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_expired")
        incomplete = jwt.encode({"sub": str(user)}, SECRET, algorithm="HS512")
        self.assertEqual(
            self.client.get(
                "/auth/me", headers={"Cookie": f"access_token={incomplete}"}
            ).status_code,
            401,
        )

    def test_registration_rate_limit(self) -> None:
        for index in range(5):
            self.register(f"user-{index}")
        response = self.client.post(
            "/auth/register", json={"username": "blocked", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "60")

    def test_previews_are_sandboxed_and_private(self) -> None:
        self.register()
        self.login()
        self.assertEqual(self.upload("test.html", b"<script>alert(1)</script>"), 201)
        html = self.client.get("/preview/test.html")
        self.assertEqual(html.status_code, 200)
        self.assertTrue(html.headers["content-type"].startswith("text/plain"))
        self.assertIn("no-store", html.headers["cache-control"])
        self.assertEqual(html.headers["x-content-type-options"], "nosniff")
        self.assertIn("sandbox", html.headers["content-security-policy"])
        self.assertEqual(
            self.upload(
                "test.svg",
                b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            ),
            201,
        )
        svg = self.client.get("/preview/test.svg")
        self.assertEqual(svg.headers["content-type"], "image/svg+xml")
        self.assertIn("default-src 'none'", svg.headers["content-security-policy"])
        download = self.client.get("/download/test.html")
        self.assertEqual(download.headers["content-type"], "application/octet-stream")
        self.assertTrue(download.headers["content-disposition"].startswith("attachment"))

    def test_preview_policy_and_browser_contract(self) -> None:
        self.register()
        self.login()
        limits = self.client.get("/storage/limits").json()
        self.assertEqual(limits["max_file_size"], 1024**2)
        self.assertEqual(limits["max_upload_files"], 2)

        html = self.client.post(
            "/upload", files={"files": ("demo.html", b"<script>demo()</script>")}
        )
        self.assertEqual(html.json()[0]["preview_kind"], "text")
        self.assertEqual(self.client.get("/preview/demo.html").headers["X-Preview-Kind"], "text")
        markdown = self.client.post("/upload", files={"files": ("readme.md", b"# Heading")})
        item = markdown.json()[0]
        self.assertEqual(item["preview_kind"], "markdown")
        self.assertEqual(
            self.client.get("/preview/readme.md").headers["X-Preview-Kind"], "markdown"
        )
        head = self.client.head("/download/readme.md")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(head.headers["Content-Length"], "9")
        replaced = self.client.post("/upload", files={"files": ("readme.md", b"# Updated")})
        self.assertNotEqual(item["revision"], replaced.json()[0]["revision"])
        large = self.client.post("/upload", files={"files": ("large.md", b"x" * (256 * 1024 + 1))})
        self.assertIsNone(large.json()[0]["preview_kind"])
        self.assertEqual(self.client.get("/preview/large.md").status_code, 415)

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("other", b"data")
        forged = self.client.post("/upload", files={"files": ("archive.png", archive.getvalue())})
        self.assertEqual(forged.json()[0]["preview_kind"], "archive")
        self.assertEqual(
            self.client.get("/preview/archive.png").json()["entries"][0]["name"], "other"
        )

    def test_krita_preview_extracts_only_the_embedded_image(self) -> None:
        self.register()
        self.login()
        image = io.BytesIO()
        Image.new("RGB", (60, 40), "red").save(image, format="PNG")
        document = io.BytesIO()
        with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("mergedimage.png", image.getvalue())
        uploaded = self.client.post(
            "/upload", files={"files": ("drawing.kra", document.getvalue())}
        )
        self.assertEqual(uploaded.json()[0]["preview_kind"], "krita")
        response = self.client.get("/preview/drawing.kra")
        self.assertEqual(response.headers["X-Preview-Kind"], "krita")
        self.assertEqual(response.headers["Content-Type"], "image/jpeg")
        self.assertTrue(response.content.startswith(b"\xff\xd8"))

        broken = io.BytesIO()
        with zipfile.ZipFile(broken, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("mergedimage.png", b"x" * (16 * 1024**2 + 1))
        self.assertEqual(self.upload("broken.kra", broken.getvalue()), 201)
        self.assertEqual(self.client.get("/preview/broken.kra").status_code, 415)

    def test_office_preview_classifies_packages_and_checks_revision(self) -> None:
        user_id = self.register()
        self.login()
        packages = {
            "word/document.xml": "document",
            "xl/workbook.xml": "spreadsheet",
            "ppt/presentation.xml": "presentation",
        }
        for index, (member, kind) in enumerate(packages.items()):
            with self.subTest(kind=kind):
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w") as archive:
                    archive.writestr("[Content_Types].xml", b"<Types/>")
                    archive.writestr("_rels/.rels", b"<Relationships/>")
                    archive.writestr(member, b"<content/>")
                name = f"office{index}"
                response = self.client.post("/upload", files={"files": (name, data.getvalue())})
                metadata = response.json()[0]
                self.assertEqual(metadata["preview_kind"], kind)
                revision = metadata["revision"]
                preview = self.client.head(f"/preview/{name}?rev={revision}")
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(preview.headers["X-Preview-Account"], str(user_id))
                self.assertEqual(preview.headers["X-File-Revision"], revision)
                self.assertEqual(preview.content, b"")
                self.assertEqual(
                    self.client.get(f"/preview/{name}?rev={revision}").content, data.getvalue()
                )
                self.assertEqual(self.client.head(f"/preview/{name}?rev=stale").status_code, 409)

    def test_archive_headers_are_read_without_extracting_members(self) -> None:
        from app.services.archive_index import RAR_MIME, TAR_MIME, ZIP_MIME, archive_index

        class CountedBytes(io.BytesIO):
            def __init__(self, value: bytes) -> None:
                super().__init__(value)
                self.bytes_read = 0

            def read(self, size: int | None = -1, /) -> bytes:
                data = super().read(size)
                self.bytes_read += len(data)
                return data

        payload = b"x" * (2 * 1024**2)
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("docs/manual.txt", payload)
        tarred = io.BytesIO()
        with tarfile.open(fileobj=tarred, mode="w") as tar:
            member = tarfile.TarInfo("docs/manual.txt")
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))

        def rar_block(kind: int, flags: int, data: bytes = b"") -> bytes:
            header = struct.pack("<BHH", kind, flags, 7 + len(data)) + data
            return struct.pack("<H", zlib.crc32(header) & 0xFFFF) + header

        name = b"docs/manual.txt"
        rared = b"Rar!\x1a\x07\x00" + rar_block(0x73, 0, bytes(6))
        rared += (
            rar_block(
                0x74,
                0x8000,
                struct.pack(
                    "<LLBLLBBHL",
                    len(payload),
                    len(payload),
                    3,
                    zlib.crc32(payload),
                    0x00210000,
                    20,
                    0x30,
                    len(name),
                    0o100644,
                )
                + name,
            )
            + payload
            + rar_block(0x7B, 0)
        )
        for mime, content in (
            (ZIP_MIME, zipped.getvalue()),
            (TAR_MIME, tarred.getvalue()),
            (RAR_MIME, rared),
        ):
            with self.subTest(mime=mime):
                source = CountedBytes(content)
                result = archive_index(source, mime)
                self.assertEqual(
                    result["entries"],
                    [
                        {
                            "name": "docs/manual.txt",
                            "size": len(payload),
                            "packed": None if mime == TAR_MIME else len(payload),
                            "type": "file",
                            "encrypted": False,
                        }
                    ],
                )
                self.assertLess(source.bytes_read, 128 * 1024)

    def test_krita_metadata_and_transparent_assets(self) -> None:
        self.register()
        self.login()
        image = io.BytesIO()
        Image.new("RGBA", (40, 20), (8, 20, 30, 50)).save(image, "PNG")
        document = io.BytesIO()
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr("mergedimage.png", image.getvalue())
            archive.writestr("preview.png", image.getvalue())
            archive.writestr(
                "maindoc.xml",
                '<DOC><IMAGE width="40" height="20"><layers><layer name="Group"><layers><layer name="Ink" visible="0" opacity="125"/></layers></layer></layers></IMAGE></DOC>',
            )
        self.assertEqual(self.upload("layers.kra", document.getvalue()), 201)
        details = self.client.get("/preview/layers.kra?view=details")
        self.assertEqual(details.json()["width"], 40)
        self.assertEqual(details.json()["assets"], ["merged", "preview"])
        self.assertEqual(details.json()["layers"][1]["depth"], 1)
        self.assertFalse(details.json()["layers"][1]["visible"])
        asset = self.client.get("/preview/layers.kra?asset=preview")
        self.assertEqual(asset.headers["Content-Type"], "image/png")
        with Image.open(io.BytesIO(asset.content)) as png:
            self.assertEqual(png.mode, "RGBA")
        self.assertEqual(self.client.get("/preview/layers.kra?asset=unknown").status_code, 400)

    def test_raster_preview_is_rendered(self) -> None:
        self.register()
        self.login()
        output = io.BytesIO()
        Image.new("RGBA", (300, 200), "red").save(output, format="PNG")
        self.assertEqual(self.upload("image.png", output.getvalue()), 201)
        response = self.client.get("/preview/image.png")
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertTrue(response.content.startswith(b"\xff\xd8"))

    def test_raw_and_compressed_ranges_and_cache_conditions(self) -> None:
        self.register()
        self.login()
        raw, compressed = bytes(range(128)), b"abcdefgh" * 70_000
        result = self.client.post(
            "/upload",
            files=[
                ("files", ("raw.bin", raw)),
                ("files", ("nested/packed.txt", compressed)),
            ],
        )
        self.assertEqual(result.status_code, 201, result.text)
        self.assertTrue(result.json()[1]["stored_as_compressed"])
        self.assertNotIn("stored_path", result.json()[1])
        for name, content in (("raw.bin", raw), ("nested/packed.txt", compressed)):
            url = f"/download/{name}"
            with self.subTest(url=url):
                full = self.client.get(url)
                self.assertEqual(full.content, content)
                last = self.client.get(url, headers={"Range": "bytes=-15"})
                self.assertEqual(last.status_code, 206)
                self.assertEqual(last.content, content[-15:])
                self.assertEqual(
                    last.headers["content-range"],
                    f"bytes {len(content) - 15}-{len(content) - 1}/{len(content)}",
                )
                open_ended = self.client.get(url, headers={"Range": "bytes=3-"})
                self.assertEqual(open_ended.content, content[3:])
                bad = self.client.get(url, headers={"Range": "bytes=99999999-"})
                self.assertEqual(bad.status_code, 416)
                self.assertEqual(bad.headers["content-range"], f"bytes */{len(content)}")
                self.assertEqual(
                    self.client.get(
                        url, headers={"If-None-Match": full.headers["etag"]}
                    ).status_code,
                    304,
                )
                self.assertEqual(
                    self.client.get(
                        url,
                        headers={
                            "If-None-Match": '"other"',
                            "If-Modified-Since": full.headers["last-modified"],
                        },
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    self.client.get(
                        url, headers={"Range": "bytes=0-1", "If-Range": '"other"'}
                    ).content,
                    content,
                )

    def test_upload_limits_and_invalid_names(self) -> None:
        self.register()
        self.login()
        self.assertEqual(self.upload("../test.txt", b"x"), 400)
        self.assertEqual(self.upload("C:/test.txt", b"x"), 400)
        unsafe = self.client.request("DELETE", "/delete", json={"filenames": ["bad\nname"]})
        self.assertEqual(unsafe.status_code, 400)
        self.assertEqual(self.upload("too-big", b"X" * (1024**2 + 1)), 413)
        chunked = self.client.post(
            "/upload",
            headers={"Content-Type": "multipart/form-data; boundary=abc"},
            content=iter(
                [
                    b'--abc\r\nContent-Disposition: form-data; name="files"; filename="x"\r\n\r\n',
                    b"x" * 800_000,
                    b"x" * 300_000,
                    b"\r\n--abc--\r\n",
                ]
            ),
        )
        self.assertEqual(chunked.status_code, 413, chunked.text)
        bad = self.client.post(
            "/upload",
            headers={"Content-Type": "multipart/form-data; boundary=abc"},
            content=b'--abc\r\nContent-Disposition: form-data; name="files"; filename="x"\r\n\r\nunterminated',
        )
        self.assertEqual(bad.status_code, 400)
        duplicate = self.client.post(
            "/upload", files=[("files", ("a", b"x")), ("files", ("./a", b"y"))]
        )
        self.assertEqual(duplicate.status_code, 400)
        excessive = self.client.post(
            "/upload", files=[("files", (name, b"x")) for name in ("a", "b", "c")]
        )
        self.assertEqual(excessive.status_code, 400)
        self.assertEqual(self.client.get("/download/a").status_code, 404)

    def test_batch_quota_leaves_previous_files_in_place(self) -> None:
        self.register()
        self.login()
        body = b"abcde" * 180_000
        self.assertEqual(self.upload("first", body), 201)
        self.assertEqual(self.upload("second", body), 201)
        upload = self.client.post(
            "/upload",
            files=[
                ("files", ("first", b"updated")),
                ("files", ("third", b"a" * 1_000_000)),
            ],
        )
        self.assertEqual(upload.status_code, 201)
        rejected = self.client.post(
            "/upload",
            files=[
                ("files", ("third", b"replacement")),
                ("files", ("fourth", body)),
            ],
        )
        self.assertEqual(rejected.status_code, 201)
        denied = self.client.post(
            "/upload",
            files=[
                ("files", ("first", b"should-not-commit")),
                ("files", ("fifth", body)),
            ],
        )
        self.assertEqual(denied.status_code, 507, denied.text)
        self.assertEqual(self.client.get("/download/first").content, b"updated")
        self.assertEqual(self.client.get("/download/fifth").status_code, 404)

    def test_users_cannot_access_each_others_files_or_old_account_data(self) -> None:
        original = self.register()
        self.login()
        self.assertEqual(self.upload("secret.txt", b"secret"), 201)
        self.register("Bob")
        self.login("Bob")
        self.assertEqual(self.client.get("/download/secret.txt").status_code, 404)
        self.assertEqual(self.client.delete("/delete/secret.txt").json()["deleted"], [])
        self.login()
        self.assertEqual(self.client.delete("/auth/delete").status_code, 200)
        replacement = self.register()
        self.assertNotEqual(original, replacement)
        self.login()
        self.assertEqual(self.client.get("/download/secret.txt").status_code, 404)

    def test_concurrent_uploads_and_overwrite(self) -> None:
        self.register()
        token = self.login()

        def upload(index: int) -> int:
            response = self.client.post(
                "/upload",
                headers={"Cookie": f"access_token={token}"},
                files={"files": (f"file-{index}", bytes([index]))},
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(upload, range(2))), [201, 201])
        self.assertEqual(self.upload("file-0", b"replacement"), 201)
        self.assertEqual(self.client.get("/download/file-0").content, b"replacement")
        self.assertEqual(self.client.get("/download/file-1").content, b"\x01")
        self.assertEqual(
            self.client.delete("/delete/file-1").json(), {"deleted": ["file-1"], "missing": []}
        )
        self.assertEqual(self.client.get("/download/file-1").status_code, 404)


class MigrationTests(unittest.TestCase):
    def test_migrates_database_and_legacy_blob_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_id = uuid4()
            database = root / "old.db"
            with sqlite3.connect(database) as db:
                db.execute(
                    "CREATE TABLE users (id CHAR(32) PRIMARY KEY, username VARCHAR NOT NULL UNIQUE, password_hash VARCHAR NOT NULL, token_version INTEGER NOT NULL)"
                )
                password = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
                db.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?)", (user_id.hex, "Legacy", password, 1)
                )
            data = root / "storage"
            legacy = data / encode_key("Legacy")
            legacy.mkdir(parents=True)
            blob = legacy / f"{uuid4().hex}_файл.txt"
            blob.write_bytes(b"old data")
            (legacy / "metadata.json").write_text(
                json.dumps(
                    {
                        encode_key("файл.txt"): {
                            "stored_path": f"C:/old-location/{legacy.name}/{blob.name}",
                            "stored_as_compressed": False,
                            "compression_algorithm": "copy",
                            "original_size": 8,
                            "stored_size": 8,
                            "compression_percent": 0.0,
                            "mime": "text/plain",
                            "category": "text",
                        }
                    }
                ),
                encoding="utf-8",
            )
            app = create_app(
                Settings(
                    storage_dir=data,
                    database_file=database,
                    allowed_hosts=["testserver"],
                    jwt_secret=SECRET,
                )
            )
            with TestClient(app) as client:
                self.assertEqual(
                    client.post(
                        "/auth/login", json={"username": "Legacy", "password": PASSWORD}
                    ).status_code,
                    200,
                )
                self.assertEqual(client.get("/download/файл.txt").content, b"old data")
                self.assertFalse(legacy.exists())
                self.assertTrue((data / f"acct-{user_id.hex}" / blob.name).is_file())


class CompressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_codecs_and_corrupt_frames(self) -> None:
        manager = CompressionManager()
        raw = b"line aaaaaaaaaaaaaaaaaaaaaaa\n" * 250_000
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "input.txt"
            path.write_bytes(raw)
            analysis = await manager.analyze_path(path)
            for algorithm in ("copy", "zlib", "lzma", "bz2"):
                with self.subTest(algorithm=algorithm):
                    compressed = await manager.compress_bytes(
                        raw, algorithm=algorithm, filename_hint="data.txt"
                    )
                    self.assertEqual(
                        await manager.decompress_bytes(compressed, max_size=len(raw)), raw
                    )
                    with self.assertRaises(CompressionError):
                        await manager.decompress_bytes(compressed[:-1])
                    with self.assertRaises(CompressionError):
                        await manager.decompress_bytes(compressed + b"trailing")
                    with self.assertRaises(CompressionError):
                        await manager.decompress_bytes(compressed, max_size=len(raw) - 1)
                    packed = root / f"{algorithm}.cmp"
                    await manager.compress_path(
                        path, packed, algorithm=algorithm, analysis=analysis
                    )
                    stream = await manager.stream_decompressed_path(packed)
                    self.assertEqual(b"".join([part async for part in stream]), raw)
                    decoded = await manager.decompress_path(packed, root / f"{algorithm}.txt")
                    self.assertEqual(decoded.read_bytes(), raw)


class StorageRefactorTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_snapshot_reuses_unchanged_file_and_detects_replacement(self) -> None:
        from app.db.database import UserDatabase
        from app.models import FileMetadata
        from app.services.metadata import MetadataStore

        with tempfile.TemporaryDirectory() as directory:
            database = UserDatabase(Path(directory) / "main.db")
            await database.initialize()
            try:
                user = await database.create_user("Snapshots", "test-hash")
                store = MetadataStore(database, user.id)
                empty = await store.snapshot(None)
                self.assertEqual(empty.data, "{}")
                self.assertIs(await store.snapshot(empty), empty)
                record: FileMetadata = {
                    "stored_path": "a" * 32,
                    "stored_as_compressed": False,
                    "compression_algorithm": "copy",
                    "original_size": 5,
                    "stored_size": 5,
                    "compression_percent": 0.0,
                    "mime": "text/plain",
                    "category": "text",
                }
                await store.commit({"example.txt": record})
                original = await store.snapshot(empty)
                self.assertEqual(json.loads(original.data)["example.txt"]["preview_kind"], "text")
                self.assertIs(await store.snapshot(original), original)
                await store.commit({"example.txt": {**record, "stored_path": "b" * 32}})
                replaced = await store.snapshot(original)
                self.assertNotEqual(replaced.data, original.data)
                await store.commit({}, ["example.txt"])
                self.assertEqual((await store.snapshot(replaced)).data, "{}")
            finally:
                await database.close()

    async def test_cancelled_waiter_allows_commit_and_event_to_finish(self) -> None:
        from app.services.sse import METADATA_CHANGED, EventBroker
        from app.services.storage import commit_storage_change

        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        committed: list[bool] = []

        def write() -> None:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(3):
                raise RuntimeError("Storage write timed out")
            committed.append(True)

        broker = EventBroker()
        account = uuid4()
        async with broker.subscribe(account) as queue:

            async def async_write() -> None:
                await asyncio.to_thread(write)

            task = asyncio.create_task(commit_storage_change(broker, account, async_write))
            try:
                await asyncio.wait_for(entered.wait(), timeout=3)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(committed, [True])
            self.assertEqual(queue.get_nowait(), METADATA_CHANGED)


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_sse_snapshot_upload_update_and_revocation(self) -> None:
        import httpx2

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                Settings(
                    storage_dir=root / "storage",
                    database_file=root / "db",
                    jwt_secret=SECRET,
                    allowed_hosts=["testserver"],
                )
            )
            async with (
                app.router.lifespan_context(app),
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
                ) as client,
            ):
                self.assertEqual(
                    (
                        await client.post(
                            "/auth/register", json={"username": "Alice", "password": PASSWORD}
                        )
                    ).status_code,
                    201,
                )
                self.assertEqual(
                    (
                        await client.post(
                            "/auth/login", json={"username": "Alice", "password": PASSWORD}
                        )
                    ).status_code,
                    200,
                )
                queue: asyncio.Queue[Message] = asyncio.Queue()
                scope: Scope = {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/metadata/stream",
                    "raw_path": b"/metadata/stream",
                    "root_path": "",
                    "query_string": b"",
                    "headers": [
                        (b"host", b"testserver"),
                        (b"cookie", f"access_token={client.cookies['access_token']}".encode()),
                    ],
                    "client": ("127.0.0.1", 1234),
                    "server": ("testserver", 80),
                }

                async def receive() -> Message:
                    return {"type": "http.request", "body": b"", "more_body": False}

                task = asyncio.create_task(app(scope, receive, queue.put))
                try:
                    self.assertEqual((await asyncio.wait_for(queue.get(), 5))["status"], 200)
                    initial = (await asyncio.wait_for(queue.get(), 5))["body"]
                    self.assertIn(b"data: {}", initial)
                    response = await client.post(
                        "/upload", files={"files": ("sse.txt", b"payload")}
                    )
                    self.assertEqual(response.status_code, 201)
                    while True:
                        body = (await asyncio.wait_for(queue.get(), 5))["body"]
                        if b"event: metadata_update" in body:
                            self.assertIn(b"sse.txt", body)
                            self.assertNotIn(b"stored_path", body)
                            self.assertIn(b"preview_kind", body)
                            break
                    self.assertEqual((await client.post("/auth/logout")).status_code, 200)
                    await asyncio.wait_for(task, 5)
                    remaining: list[bytes] = []
                    while not queue.empty():
                        remaining.append(queue.get_nowait().get("body", b""))
                    self.assertIn(b"event: close_connection", b"".join(remaining))
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
