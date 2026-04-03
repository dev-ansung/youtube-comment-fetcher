# /// script
# dependencies = [
#   "requests",
#   "dateparser",
# ]
# ///

import argparse
import csv
import json
import re
import sys
import time
from typing import Any, Dict, Generator, Iterator, Optional

import dateparser
import requests

YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v={youtube_id}"
YOUTUBE_CONSENT_URL = "https://consent.youtube.com/save"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36"
SORT_BY_POPULAR = 0
SORT_BY_RECENT = 1
YT_CFG_RE = r"ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;"
YT_INITIAL_DATA_RE = r'(?:window\s*\[\s*["\']ytInitialData["\']\s*\]|ytInitialData)\s*=\s*({.+?})\s*;\s*(?:var\s+meta|</script|\n)'
YT_HIDDEN_INPUT_RE = r'<input\s+type="hidden"\s+name="([A-Za-z0-9_]+)"\s+value="([A-Za-z0-9_\-\.]*)"\s*(?:required|)\s*>'

_VIDEO_ID_PATTERNS = [
    r"(?:v=)([a-zA-Z0-9_-]{11})",
    r"youtu\.be/([a-zA-Z0-9_-]{11})",
    r"/shorts/([a-zA-Z0-9_-]{11})",
    r"/embed/([a-zA-Z0-9_-]{11})",
    r"/v/([a-zA-Z0-9_-]{11})",
]


class YoutubeCommentDownloader:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.cookies.set("CONSENT", "YES+cb", domain=".youtube.com")

    def ajax_request(
        self,
        endpoint: Dict[str, Any],
        ytcfg: Dict[str, Any],
        retries: int = 5,
        sleep: int = 20,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        url = (
            "https://www.youtube.com"
            + endpoint["commandMetadata"]["webCommandMetadata"]["apiUrl"]
        )
        data = {
            "context": ytcfg["INNERTUBE_CONTEXT"],
            "continuation": endpoint["continuationCommand"]["token"],
        }

        for _ in range(retries):
            try:
                response = self.session.post(
                    url,
                    params={"key": ytcfg["INNERTUBE_API_KEY"]},
                    json=data,
                    timeout=timeout,
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code in [403, 413]:
                    return {}
            except requests.exceptions.Timeout:
                pass
            time.sleep(sleep)
        return {}

    def get_comments(
        self, youtube_id: str, *args: Any, **kwargs: Any
    ) -> Iterator[Dict[str, Any]]:
        return self.get_comments_from_url(
            YOUTUBE_VIDEO_URL.format(youtube_id=youtube_id), *args, **kwargs
        )

    def get_comments_from_url(
        self,
        youtube_url: str,
        sort_by: int = SORT_BY_RECENT,
        language: Optional[str] = None,
        sleep: float = 0.1,
    ) -> Iterator[Dict[str, Any]]:
        response = self.session.get(youtube_url)

        if "consent" in str(response.url):
            params = dict(re.findall(YT_HIDDEN_INPUT_RE, response.text))
            params.update(
                {
                    "continue": youtube_url,
                    "set_eom": False,
                    "set_ytc": True,
                    "set_apyt": True,
                }
            )
            response = self.session.post(YOUTUBE_CONSENT_URL, params=params)

        html = response.text
        ytcfg_str = self.regex_search(html, YT_CFG_RE, default="")
        if not ytcfg_str:
            return
        ytcfg = json.loads(ytcfg_str)

        if language:
            ytcfg["INNERTUBE_CONTEXT"]["client"]["hl"] = language

        data_str = self.regex_search(html, YT_INITIAL_DATA_RE, default="")
        data = json.loads(data_str) if data_str else {}

        item_section = next(self.search_dict(data, "itemSectionRenderer"), None)
        renderer = (
            next(self.search_dict(item_section, "continuationItemRenderer"), None)
            if item_section
            else None
        )
        if not renderer:
            return

        sort_menu = next(self.search_dict(data, "sortFilterSubMenuRenderer"), {}).get(
            "subMenuItems", []
        )
        if not sort_menu:
            section_list = next(self.search_dict(data, "sectionListRenderer"), {})
            continuations = list(self.search_dict(section_list, "continuationEndpoint"))
            data = self.ajax_request(continuations[0], ytcfg) if continuations else {}
            sort_menu = next(
                self.search_dict(data, "sortFilterSubMenuRenderer"), {}
            ).get("subMenuItems", [])

        if not sort_menu or sort_by >= len(sort_menu):
            raise RuntimeError("Failed to set sorting")

        continuations = [sort_menu[sort_by]["serviceEndpoint"]]

        while continuations:
            continuation = continuations.pop()
            response_data = self.ajax_request(continuation, ytcfg)

            if not response_data:
                break

            error = next(self.search_dict(response_data, "externalErrorMessage"), None)
            if error:
                raise RuntimeError("Error returned from server: " + error)

            actions = list(
                self.search_dict(response_data, "reloadContinuationItemsCommand")
            ) + list(self.search_dict(response_data, "appendContinuationItemsAction"))

            for action in actions:
                for item in action.get("continuationItems", []):
                    if action["targetId"] in [
                        "comments-section",
                        "engagement-panel-comments-section",
                        "shorts-engagement-panel-comments-section",
                    ]:
                        continuations[:0] = [
                            ep for ep in self.search_dict(item, "continuationEndpoint")
                        ]
                    if (
                        action["targetId"].startswith("comment-replies-item")
                        and "continuationItemRenderer" in item
                    ):
                        continuations.append(
                            next(self.search_dict(item, "buttonRenderer"))["command"]
                        )

            surface_payloads = self.search_dict(
                response_data, "commentSurfaceEntityPayload"
            )
            payments = {
                payload["key"]: next(self.search_dict(payload, "simpleText"), "")
                for payload in surface_payloads
                if "pdgCommentChip" in payload
            }
            if payments:
                view_models = [
                    vm["commentViewModel"]
                    for vm in self.search_dict(response_data, "commentViewModel")
                ]
                surface_keys = {
                    vm["commentSurfaceKey"]: vm["commentId"]
                    for vm in view_models
                    if "commentSurfaceKey" in vm
                }
                payments = {
                    surface_keys[key]: payment
                    for key, payment in payments.items()
                    if key in surface_keys
                }

            toolbar_payloads = self.search_dict(
                response_data, "engagementToolbarStateEntityPayload"
            )
            toolbar_states = {payload["key"]: payload for payload in toolbar_payloads}

            for comment in reversed(
                list(self.search_dict(response_data, "commentEntityPayload"))
            ):
                properties = comment["properties"]
                cid = properties["commentId"]
                author = comment["author"]
                toolbar = comment["toolbar"]
                toolbar_state = toolbar_states.get(properties["toolbarStateKey"], {})

                result = {
                    "cid": cid,
                    "text": properties["content"]["content"],
                    "time": properties["publishedTime"],
                    "author": author["displayName"],
                    "channel": author["channelId"],
                    "votes": toolbar.get("likeCountNotliked", "").strip() or "0",
                    "replies": toolbar.get("replyCount", 0),
                    "photo": author.get("avatarThumbnailUrl", ""),
                    "heart": toolbar_state.get("heartState", "")
                    == "TOOLBAR_HEART_STATE_HEARTED",
                    "reply": "." in cid,
                }

                try:
                    time_str = result["time"].split("(")[0].strip()
                    parsed_date = dateparser.parse(time_str)
                    if parsed_date:
                        result["time_parsed"] = parsed_date.timestamp()
                except AttributeError:
                    pass

                if cid in payments:
                    result["paid"] = payments[cid]

                yield result
            time.sleep(sleep)

    @staticmethod
    def regex_search(
        text: str, pattern: str, group: int = 1, default: Any = None
    ) -> Any:
        match = re.search(pattern, text)
        return match.group(group) if match else default

    @staticmethod
    def search_dict(partial: Any, search_key: str) -> Generator[Any, None, None]:
        stack = [partial]
        while stack:
            current_item = stack.pop()
            if isinstance(current_item, dict):
                for key, value in current_item.items():
                    if key == search_key:
                        yield value
                    else:
                        stack.append(value)
            elif isinstance(current_item, list):
                stack.extend(current_item)


def extract_video_id(url_or_id: str) -> str:
    for pattern in _VIDEO_ID_PATTERNS:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url_or_id):
        return url_or_id
    raise ValueError(f"Could not extract a YouTube video ID from: {url_or_id}")


def parse_likes(likes_str: str) -> int:
    likes_str = likes_str.strip().upper()
    if not likes_str or likes_str == "0":
        return 0
    multiplier = 1
    if likes_str.endswith("K"):
        multiplier = 1000
        likes_str = likes_str[:-1]
    elif likes_str.endswith("M"):
        multiplier = 1000000
        likes_str = likes_str[:-1]

    try:
        return int(float(likes_str) * multiplier)
    except ValueError:
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch YouTube comments via CLI.")
    parser.add_argument("url", help="YouTube video URL or ID")
    parser.add_argument(
        "--limit", type=int, default=100, help="Max comments to fetch (0 for all)"
    )
    parser.add_argument(
        "--sort", choices=["top", "new"], default="top", help="Sort order"
    )
    parser.add_argument("--language", type=str, help="Language code (e.g., 'en', 'es')")
    parser.add_argument(
        "--format",
        choices=["json", "jsonl", "csv", "text"],
        default="text",
        help="Output format",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    parser.add_argument(
        "--no-replies", action="store_true", help="Only fetch top-level comments"
    )
    parser.add_argument(
        "--min-likes", type=int, default=0, help="Minimum likes required"
    )
    parser.add_argument(
        "--age", type=int, help="Maximum age of comments to fetch in days"
    )

    args = parser.parse_args()

    try:
        video_id = extract_video_id(args.url)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    sort_mapping = {"top": SORT_BY_POPULAR, "new": SORT_BY_RECENT}
    downloader = YoutubeCommentDownloader()

    cutoff_timestamp = None
    if args.age is not None and args.age > 0:
        cutoff_timestamp = time.time() - (args.age * 86400)

    fetched_count = 0
    collected_json = []

    csv_writer = None
    csv_fields = [
        "cid",
        "text",
        "time",
        "author",
        "channel",
        "votes",
        "replies",
        "photo",
        "heart",
        "reply",
        "time_parsed",
        "paid",
    ]

    if args.format == "csv":
        csv_writer = csv.DictWriter(
            sys.stdout, fieldnames=csv_fields, extrasaction="ignore"
        )
        csv_writer.writeheader()

    print(f"Fetching comments for video: {video_id}...", file=sys.stderr)

    try:
        generator = downloader.get_comments_from_url(
            YOUTUBE_VIDEO_URL.format(youtube_id=video_id),
            sort_by=sort_mapping[args.sort],
            language=args.language,
        )

        for comment in generator:
            if args.limit > 0 and fetched_count >= args.limit:
                break

            if args.no_replies and comment.get("reply"):
                continue

            if (
                args.min_likes > 0
                and parse_likes(comment.get("votes", "0")) < args.min_likes
            ):
                continue

            if cutoff_timestamp and comment.get("time_parsed"):
                if comment["time_parsed"] < cutoff_timestamp:
                    if args.sort == "new":
                        break
                    continue

            fetched_count += 1
            if fetched_count % 50 == 0:
                print(
                    f"\rFetched {fetched_count} comments...",
                    file=sys.stderr,
                    end="",
                    flush=True,
                )

            if args.format == "json":
                collected_json.append(comment)
            elif args.format == "jsonl":
                print(json.dumps(comment))
            elif args.format == "csv" and csv_writer:
                csv_writer.writerow(comment)
            elif args.format == "text":
                print(f"{comment['author']}: {comment['text']}\n")

        print(f"\rCompleted. Fetched {fetched_count} comments.", file=sys.stderr)

        if args.format == "json":
            indent = 2 if args.pretty else None
            print(json.dumps(collected_json, indent=indent))

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\nFailed to fetch comments: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
