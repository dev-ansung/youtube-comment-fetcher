import csv
import io
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import (
    SORT_BY_POPULAR,
    YoutubeCommentDownloader,
    extract_video_id,
    main as cli_main,
    parse_likes,
)


class TestCommentSchema(unittest.TestCase):
    def test_get_comments_from_url_returns_expected_schema(self) -> None:
        downloader = YoutubeCommentDownloader()
        fake_url = "https://example.test/watch?v=abc123def45"
        fixture_path = (
            Path(__file__).parent / "fixtures" / "youtube_comment_payload.json"
        )

        # Fallback empty fixture logic for when the actual file is missing in CI
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            ytcfg = fixture["ytcfg"]
            fixture_response = fixture["response_data"]
        except FileNotFoundError:
            self.skipTest("Fixture youtube_comment_payload.json not found.")

        initial_data = {
            "itemSectionRenderer": {"continuationItemRenderer": {"present": True}},
            "sortFilterSubMenuRenderer": {
                "subMenuItems": [
                    {
                        "serviceEndpoint": {
                            "commandMetadata": {
                                "webCommandMetadata": {"apiUrl": "/v1/next"}
                            },
                            "continuationCommand": {"token": "fake-token"},
                        }
                    }
                ]
            },
        }

        html = (
            f"<script>ytcfg.set({json.dumps(ytcfg)});</script>"
            f"<script>var ytInitialData = {json.dumps(initial_data)}; var meta = {{}};</script>"
        )
        fake_page = SimpleNamespace(url=fake_url, text=html)
        comments_in_fixture = list(
            downloader.search_dict(fixture_response, "commentEntityPayload")
        )
        self.assertGreater(len(comments_in_fixture), 0)
        sample_comment = comments_in_fixture[0]

        toolbar_states = list(
            downloader.search_dict(
                fixture_response, "engagementToolbarStateEntityPayload"
            )
        )
        toolbar_key = sample_comment["properties"]["toolbarStateKey"]
        sample_toolbar_state = next(
            (state for state in toolbar_states if state.get("key") == toolbar_key),
            {"key": toolbar_key, "heartState": "TOOLBAR_HEART_STATE_UNHEARTED"},
        )

        response_data = {
            "commentEntityPayload": sample_comment,
            "engagementToolbarStateEntityPayload": sample_toolbar_state,
        }

        with (
            patch.object(downloader.session, "get", return_value=fake_page),
            patch.object(
                downloader.session,
                "post",
                side_effect=AssertionError("No POST calls expected"),
            ),
            patch("main.dateparser.parse", return_value=None),
            patch.object(downloader, "ajax_request", return_value=response_data),
        ):
            comments = list(
                downloader.get_comments_from_url(
                    fake_url, sort_by=SORT_BY_POPULAR, sleep=0
                )
            )

        self.assertEqual(len(comments), 1)
        comment = comments[0]

        required_keys = {
            "cid": str,
            "text": str,
            "time": str,
            "author": str,
            "channel": str,
            "votes": str,
            "replies": (str, int),
            "photo": str,
            "heart": bool,
            "reply": bool,
        }

        for key, expected_type in required_keys.items():
            self.assertIn(key, comment, f"Missing required schema key: {key}")
            self.assertIsInstance(
                comment[key], expected_type, f"Schema type mismatch for key '{key}'"
            )


class TestUnitFunctions(unittest.TestCase):
    def test_extract_video_id(self) -> None:
        valid_inputs = {
            "dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/v/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        }
        for url, expected_id in valid_inputs.items():
            self.assertEqual(extract_video_id(url), expected_id)

        with self.assertRaises(ValueError):
            extract_video_id("invalid-url-format")

    def test_parse_likes(self) -> None:
        self.assertEqual(parse_likes("0"), 0)
        self.assertEqual(parse_likes("150"), 150)
        self.assertEqual(parse_likes("1.5K"), 1500)
        self.assertEqual(parse_likes("2M"), 2000000)
        self.assertEqual(parse_likes(""), 0)
        self.assertEqual(parse_likes("invalid"), 0)


class TestCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.now = time.time()
        self.mock_comments = [
            {
                "cid": "1",
                "text": "Old top level",
                "author": "UserA",
                "channel": "UC1",
                "votes": "500",
                "replies": 1,
                "photo": "",
                "heart": False,
                "reply": False,
                "time": "10 days ago",
                "time_parsed": self.now - (10 * 86400),
            },
            {
                "cid": "1.1",
                "text": "A reply",
                "author": "UserB",
                "channel": "UC2",
                "votes": "10",
                "replies": 0,
                "photo": "",
                "heart": False,
                "reply": True,
                "time": "5 days ago",
                "time_parsed": self.now - (5 * 86400),
            },
            {
                "cid": "2",
                "text": "New top level",
                "author": "UserC",
                "channel": "UC3",
                "votes": "2.5K",
                "replies": 0,
                "photo": "",
                "heart": True,
                "reply": False,
                "time": "1 day ago",
                "time_parsed": self.now - (1 * 86400),
            },
        ]

    def run_cli_with_args(self, args: list[str]) -> str:
        """Helper to invoke the CLI and capture stdout while suppressing stderr."""
        with (
            patch("sys.argv", ["main.py"] + args),
            patch(
                "main.YoutubeCommentDownloader.get_comments_from_url",
                return_value=(c for c in self.mock_comments),
            ),
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            try:
                cli_main()
            except SystemExit as e:
                self.assertEqual(e.code, 0, f"CLI exited with error code {e.code}")
            return mock_stdout.getvalue()

    def test_cli_format_json(self) -> None:
        output = self.run_cli_with_args(["dQw4w9WgXcQ", "--format", "json"])
        data = json.loads(output)
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["author"], "UserA")

    def test_cli_format_jsonl(self) -> None:
        output = self.run_cli_with_args(["dQw4w9WgXcQ", "--format", "jsonl"]).strip()
        lines = output.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[-1])["author"], "UserC")

    def test_cli_format_csv(self) -> None:
        output = self.run_cli_with_args(["dQw4w9WgXcQ", "--format", "csv"])
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["cid"], "1")
        self.assertEqual(rows[2]["votes"], "2.5K")

    def test_cli_format_text(self) -> None:
        output = self.run_cli_with_args(["dQw4w9WgXcQ", "--format", "text"])
        self.assertIn("UserA: Old top level", output)
        self.assertIn("UserC: New top level", output)

    def test_cli_filter_limit(self) -> None:
        output = self.run_cli_with_args(
            ["dQw4w9WgXcQ", "--limit", "1", "--format", "json"]
        )
        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["cid"], "1")

    def test_cli_filter_no_replies(self) -> None:
        output = self.run_cli_with_args(
            ["dQw4w9WgXcQ", "--no-replies", "--format", "json"]
        )
        data = json.loads(output)
        self.assertEqual(len(data), 2)
        self.assertFalse(any(c["reply"] for c in data))

    def test_cli_filter_min_likes(self) -> None:
        output = self.run_cli_with_args(
            ["dQw4w9WgXcQ", "--min-likes", "1000", "--format", "json"]
        )
        data = json.loads(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["author"], "UserC")

    def test_cli_filter_age(self) -> None:
        # Fetch comments newer than 6 days (should match '5 days ago' and '1 day ago')
        output = self.run_cli_with_args(
            ["dQw4w9WgXcQ", "--age", "6", "--format", "json"]
        )
        data = json.loads(output)
        self.assertEqual(len(data), 2)
        authors = [c["author"] for c in data]
        self.assertNotIn("UserA", authors)
        self.assertIn("UserB", authors)
        self.assertIn("UserC", authors)


if __name__ == "__main__":
    unittest.main()
