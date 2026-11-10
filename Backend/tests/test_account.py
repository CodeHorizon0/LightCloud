from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import Settings
from main import create_app

PASSWORD = "original-password"
NEW_PASSWORD = "updated-password-2026"


class AccountTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.settings = Settings(
            storage_dir=root / "storage",
            database_file=root / "main.db",
            jwt_secret="account-test-key-" * 8,
            allowed_hosts=["testserver"],
        )
        self.client = self.enterContext(TestClient(create_app(self.settings)))
        self.client.post("/auth/register", json={"username": "Alice", "password": PASSWORD})
        self.client.post("/auth/login", json={"username": "Alice", "password": PASSWORD})
        self.token = str(self.client.cookies["access_token"])

    def test_password_validation_csrf_and_failed_attempts_preserve_sessions(self) -> None:
        payload = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
        self.assertEqual(
            self.client.patch("/auth/password", json=payload, headers={"Cookie": ""}).status_code,
            401,
        )
        self.assertEqual(
            self.client.patch(
                "/auth/password", json=payload, headers={"Origin": "https://attacker.test"}
            ).status_code,
            403,
        )
        for current, new, status in [
            ("incorrect", NEW_PASSWORD, 400),
            (PASSWORD, PASSWORD, 400),
            (PASSWORD, "short", 422),
            (PASSWORD, "x" * 129, 422),
            (PASSWORD, "invalid\ud800", 422),
        ]:
            response = self.client.patch(
                "/auth/password",
                content=json.dumps({"current_password": current, "new_password": new}),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(response.status_code, status, response.text)
            self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)

    def test_password_change_revokes_all_devices_but_preserves_account_and_files(self) -> None:
        other = self.enterContext(TestClient(create_app(self.settings)))
        other.post("/auth/login", json={"username": "Alice", "password": PASSWORD})
        other_token = str(other.cookies["access_token"])
        upload = self.client.post(
            "/sync/upload",
            files={"files": ("sample.py", b"print('retained')")},
            data={"revisions": json.dumps({"sample.py": None})},
        )
        self.assertEqual(upload.status_code, 201)
        before = self.client.get("/auth/me").json()["user"]
        changed = self.client.patch(
            "/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertIn("Max-Age=0", changed.headers["set-cookie"])
        for client, token in [(self.client, self.token), (other, other_token)]:
            self.assertEqual(
                client.get("/auth/me", headers={"Cookie": f"access_token={token}"}).status_code, 401
            )
            self.assertEqual(
                client.get("/sync", headers={"Cookie": f"access_token={token}"}).status_code, 401
            )
        self.assertEqual(
            other.post("/auth/login", json={"username": "Alice", "password": PASSWORD}).status_code,
            401,
        )
        self.assertEqual(
            other.post(
                "/auth/login", json={"username": "Alice", "password": NEW_PASSWORD}
            ).status_code,
            200,
        )
        self.assertEqual(other.get("/auth/me").json()["user"], before)
        self.assertEqual(other.get("/download/sample.py").content, b"print('retained')")

    def test_simultaneous_password_changes_have_one_winner(self) -> None:
        other = self.enterContext(TestClient(create_app(self.settings)))

        def change(client: TestClient, password: str) -> int:
            return client.patch(
                "/auth/password",
                headers={"Cookie": f"access_token={self.token}"},
                json={"current_password": PASSWORD, "new_password": password},
            ).status_code

        with ThreadPoolExecutor(2) as executor:
            futures = [
                executor.submit(change, client, password)
                for client, password in [
                    (self.client, "device-one-password"),
                    (other, "device-two-password"),
                ]
            ]
            statuses = [future.result() for future in futures]
        self.assertEqual(sorted(statuses), [200, 401])
        winner = "device-one-password" if statuses[0] == 200 else "device-two-password"
        self.assertEqual(
            self.client.post(
                "/auth/login", json={"username": "Alice", "password": winner}
            ).status_code,
            200,
        )

    def test_code_language_is_server_owned_and_plain_text_stays_plain(self) -> None:
        samples = [
            ("script.py", b"def answer():\n    return 42\n", "python"),
            ("plain.txt", b"def answer(): return 42", None),
            ("page.html", b"<script>alert(1)</script>", "xml"),
            ("pretend.py", b"\x00\x01\x02\xff\x00", None),
        ]
        for name, body, language in samples:
            with self.subTest(name=name):
                response = self.client.post(
                    "/sync/upload",
                    files={"files": (name, body)},
                    data={"revisions": json.dumps({name: None})},
                )
                self.assertEqual(response.status_code, 201, response.text)
                info = self.client.get("/sync").json()["files"][name]
                self.assertEqual(info["code_language"], language)
                if language:
                    self.assertEqual(info["preview_kind"], "text")
