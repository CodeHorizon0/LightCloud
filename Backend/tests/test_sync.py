from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import bcrypt
from fastapi.testclient import TestClient
from httpx2 import Response
from starlette.types import Message, Scope

from app.core.settings import Settings
from main import create_app

PASSWORD = "test-password"
SECRET = "sync-test-key-" * 8


class SyncApiTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.settings = Settings(
            storage_dir=root / "storage",
            database_file=root / "db",
            jwt_secret=SECRET,
            allowed_hosts=["testserver"],
            max_upload_files=2,
            max_file_size_mb=1,
            max_batch_size_mb=1,
        )
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app))
        self.client.post("/auth/register", json={"username": "Alice", "password": PASSWORD})
        response = self.client.post("/auth/login", json={"username": "Alice", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)

    def upload(self, values: dict[str, bytes], revisions: dict[str, str | None]) -> Response:
        return self.client.post(
            "/sync/upload",
            files=[("files", (name, body)) for name, body in values.items()],
            data={"revisions": json.dumps(revisions)},
        )

    def test_snapshot_etag_and_account_isolation(self) -> None:
        self.assertEqual(self.client.get("/sync", headers={"Cookie": ""}).status_code, 401)
        empty = self.client.get("/sync")
        self.assertEqual(empty.json()["files"], {})
        self.assertEqual(empty.headers["cache-control"], "no-store")
        self.assertEqual(
            self.client.get("/sync", headers={"If-None-Match": empty.headers["etag"]}).status_code,
            304,
        )
        self.assertEqual(self.upload({"one.txt": b"first"}, {"one.txt": None}).status_code, 201)
        snapshot = self.client.get("/sync", headers={"If-None-Match": empty.headers["etag"]})
        self.assertEqual(snapshot.status_code, 200)
        self.assertNotIn("stored_path", snapshot.text)
        self.assertEqual(snapshot.json()["files"]["one.txt"]["preview_kind"], "text")
        self.client.post("/auth/register", json={"username": "Other", "password": PASSWORD})
        self.client.post("/auth/login", json={"username": "Other", "password": PASSWORD})
        other = self.client.get("/sync", headers={"If-None-Match": empty.headers["etag"]})
        self.assertEqual(other.status_code, 200)
        self.assertNotEqual(other.headers["etag"], empty.headers["etag"])
        self.assertEqual(other.json()["files"], {})

    def test_upload_conflict_and_batch_atomicity(self) -> None:
        self.assertEqual(self.upload({"one.txt": b"first"}, {"one.txt": None}).status_code, 201)
        first = self.client.get("/sync").json()["files"]["one.txt"]["revision"]
        self.assertEqual(self.upload({"one.txt": b"second"}, {"one.txt": first}).status_code, 201)
        conflict = self.upload(
            {"one.txt": b"lost", "two.txt": b"uncommitted"}, {"one.txt": first, "two.txt": None}
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "sync_conflict")
        self.assertEqual(conflict.json()["conflicts"][0]["path"], "one.txt")
        self.assertEqual(self.client.get("/download/one.txt").content, b"second")
        self.assertEqual(self.client.get("/download/two.txt").status_code, 404)
        self.assertEqual(
            self.upload({"one.txt": b"create collision"}, {"one.txt": None}).status_code, 409
        )
        self.assertEqual(self.upload({"one.txt": b"bad"}, {}).status_code, 400)
        self.assertEqual(
            self.client.post("/sync/upload", files={"files": ("x.txt", b"missing")}).status_code,
            428,
        )

    def test_stale_deletion_never_deletes_new_version(self) -> None:
        self.upload({"one.txt": b"first", "two.txt": b"keep"}, {"one.txt": None, "two.txt": None})
        files = self.client.get("/sync").json()["files"]
        old = files["one.txt"]["revision"]
        self.upload({"one.txt": b"newer"}, {"one.txt": old})
        response = self.client.request(
            "DELETE",
            "/sync/delete",
            json={
                "filenames": ["one.txt", "two.txt"],
                "revisions": {"one.txt": old, "two.txt": files["two.txt"]["revision"]},
            },
        )
        self.assertEqual(response.status_code, 409)
        current = self.client.get("/sync").json()["files"]
        self.assertEqual(set(current), {"one.txt", "two.txt"})
        result = self.client.request(
            "DELETE",
            "/sync/delete",
            json={
                "filenames": ["one.txt"],
                "revisions": {"one.txt": current["one.txt"]["revision"]},
            },
        )
        self.assertEqual(result.json()["deleted"], ["one.txt"])
        self.assertEqual(
            self.upload({"one.txt": b"stale resurrection"}, {"one.txt": old}).status_code, 409
        )

    def test_concurrent_devices_have_exactly_one_winner(self) -> None:
        self.upload({"one.txt": b"initial"}, {"one.txt": None})
        revision = self.client.get("/sync").json()["files"]["one.txt"]["revision"]
        token = self.client.cookies["access_token"]
        second_app = create_app(self.settings)
        other = self.enterContext(TestClient(second_app))

        def write(client: TestClient, body: bytes) -> int:
            return client.post(
                "/sync/upload",
                headers={"Cookie": f"access_token={token}"},
                files={"files": ("one.txt", body)},
                data={"revisions": json.dumps({"one.txt": revision})},
            ).status_code

        with ThreadPoolExecutor(2) as executor:
            statuses = list(
                executor.map(
                    lambda pair: write(*pair),
                    [(self.client, b"device one"), (other, b"device two")],
                )
            )
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertIn(self.client.get("/download/one.txt").content, [b"device one", b"device two"])
        self.assertEqual(
            self.client.get("/sync").json()["cursor"],
            other.get("/sync", headers={"Cookie": f"access_token={token}"}).json()["cursor"],
        )

    def test_parallel_additions_and_deletions_preserve_unrelated_files(self) -> None:
        token = str(self.client.cookies["access_token"])
        other = self.enterContext(TestClient(create_app(self.settings)))
        headers = {"Cookie": f"access_token={token}"}
        expected: set[str] = set()
        with ThreadPoolExecutor(2) as executor:
            for index in range(8):
                names = [f"first-{index}.txt", f"second-{index}.txt"]
                writes = [
                    executor.submit(
                        client.post,
                        "/sync/upload",
                        headers=headers,
                        files={"files": (name, name.encode())},
                        data={"revisions": json.dumps({name: None})},
                    )
                    for client, name in zip((self.client, other), names, strict=True)
                ]
                self.assertEqual([future.result().status_code for future in writes], [201, 201])
                expected.update(names)
                state = self.client.get("/sync").json()["files"]
                self.assertEqual(set(state), expected)
                remove, keep = names
                new_name = f"third-{index}.txt"
                deletion = executor.submit(
                    self.client.request,
                    "DELETE",
                    "/sync/delete",
                    headers=headers,
                    json={"filenames": [remove], "revisions": {remove: state[remove]["revision"]}},
                )
                addition = executor.submit(
                    other.post,
                    "/sync/upload",
                    headers=headers,
                    files={"files": (new_name, b"added")},
                    data={"revisions": json.dumps({new_name: None})},
                )
                self.assertEqual(deletion.result().status_code, 200)
                self.assertEqual(addition.result().status_code, 201)
                expected.remove(remove)
                expected.add(new_name)
                self.assertEqual(set(self.client.get("/sync").json()["files"]), expected)
                self.assertEqual(self.client.get(f"/download/{keep}").content, keep.encode())

    def test_upgrade_removes_unwanted_fields_and_preserves_account_files(self) -> None:
        from utils import encode_key

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_id = uuid4()
            password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
            database = root / "users.db"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE users (id CHAR(32) PRIMARY KEY, username VARCHAR NOT NULL UNIQUE, password_hash VARCHAR NOT NULL, token_version INTEGER NOT NULL, legacy_storage BOOLEAN NOT NULL DEFAULT 0, display_name VARCHAR NOT NULL DEFAULT '', bio VARCHAR NOT NULL DEFAULT '', profile_revision INTEGER NOT NULL DEFAULT 1)"
                )
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id.hex,
                        "Existing",
                        password_hash,
                        1,
                        0,
                        "Extra name",
                        "Extra description",
                        2,
                    ),
                )
            account = root / "storage" / f"acct-{user_id.hex}"
            account.mkdir(parents=True)
            leaf = uuid4().hex
            content = b"Existing file remains accessible"
            (account / leaf).write_bytes(content)
            (account / "metadata.json").write_text(
                json.dumps(
                    {
                        encode_key("existing.txt"): {
                            "stored_path": leaf,
                            "stored_as_compressed": False,
                            "compression_algorithm": "copy",
                            "original_size": len(content),
                            "stored_size": len(content),
                            "compression_percent": 0.0,
                            "mime": "text/plain",
                            "category": "text",
                            "preview_profiled": True,
                        }
                    }
                )
            )
            settings = Settings(
                storage_dir=root / "storage",
                database_file=database,
                jwt_secret=SECRET,
                allowed_hosts=["testserver"],
            )
            with TestClient(create_app(settings)) as client:
                login = client.post(
                    "/auth/login", json={"username": "Existing", "password": PASSWORD}
                )
                self.assertEqual(login.status_code, 200)
                self.assertEqual(
                    client.get("/auth/me").json()["user"],
                    {"id": str(user_id), "username": "Existing"},
                )
                self.assertEqual(client.get("/download/existing.txt").content, content)
                self.assertNotIn("profile", client.get("/sync").json())
                self.assertEqual(client.patch("/auth/profile", json={}).status_code, 404)
            with sqlite3.connect(settings.database_file) as connection:
                names = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
                self.assertTrue({"display_name", "bio", "profile_revision"}.isdisjoint(names))
                self.assertEqual(
                    connection.execute(
                        "SELECT id, username, password_hash, token_version FROM users"
                    ).fetchone(),
                    (user_id.hex, "Existing", password_hash, 1),
                )


class SyncStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_patch_delete_and_revocation_across_workers(self) -> None:
        from unittest.mock import patch

        import httpx2

        import app.api.routes.sync as sync_routes

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                storage_dir=root / "storage",
                database_file=root / "db",
                jwt_secret=SECRET,
                allowed_hosts=["testserver"],
            )
            first, second = create_app(settings), create_app(settings)
            async with (
                first.router.lifespan_context(first),
                second.router.lifespan_context(second),
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=first), base_url="http://testserver"
                ) as client,
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=second), base_url="http://testserver"
                ) as other,
            ):
                await client.post(
                    "/auth/register", json={"username": "Alice", "password": PASSWORD}
                )
                await client.post("/auth/login", json={"username": "Alice", "password": PASSWORD})
                token = str(client.cookies["access_token"])
                other.cookies.set("access_token", token)
                initial = (await client.get("/sync")).json()
                self.assertTrue(UUID(initial["account"]))
                queue: asyncio.Queue[Message] = asyncio.Queue()
                scope: Scope = {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/sync/stream",
                    "raw_path": b"/sync/stream",
                    "root_path": "",
                    "query_string": f"cursor={initial['cursor']}".encode(),
                    "headers": [
                        (b"host", b"testserver"),
                        (b"cookie", f"access_token={token}".encode()),
                    ],
                    "client": ("127.0.0.1", 1234),
                    "server": ("testserver", 80),
                }

                async def receive() -> Message:
                    return {"type": "http.request", "body": b"", "more_body": False}

                async def event(name: str) -> dict[str, object]:
                    while True:
                        body = (await asyncio.wait_for(queue.get(), 5)).get("body", b"").decode()
                        if f"event: {name}\n" in body:
                            return (
                                json.loads(body.split("data: ", 1)[1])
                                if body.split("data: ", 1)[1].strip()
                                else {}
                            )

                with patch.object(sync_routes, "SYNC_INTERVAL", 0.05):
                    task = asyncio.create_task(first(scope, receive, queue.put))
                    try:
                        self.assertEqual((await asyncio.wait_for(queue.get(), 5))["status"], 200)
                        self.assertEqual((await event("sync_ready"))["cursor"], initial["cursor"])
                        # The second app has a separate event broker and shares only persisted storage.
                        response = await other.post(
                            "/sync/upload",
                            files={"files": ("remote.txt", b"remote")},
                            data={"revisions": json.dumps({"remote.txt": None})},
                        )
                        self.assertEqual(response.status_code, 201)
                        changed = await event("sync_patch")
                        self.assertEqual(changed["from"], initial["cursor"])
                        upserts = changed["upsert"]
                        assert isinstance(upserts, dict)
                        self.assertIn("remote.txt", upserts)
                        state = (await other.get("/sync")).json()
                        response = await other.request(
                            "DELETE",
                            "/sync/delete",
                            json={
                                "filenames": ["remote.txt"],
                                "revisions": {
                                    "remote.txt": state["files"]["remote.txt"]["revision"]
                                },
                            },
                        )
                        self.assertEqual(response.status_code, 200)
                        deleted = await event("sync_patch")
                        self.assertEqual(deleted["deleted"], ["remote.txt"])
                        self.assertEqual(deleted["from"], state["cursor"])
                        await other.post("/auth/logout")
                        await event("close_connection")
                        await asyncio.wait_for(task, 5)
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
