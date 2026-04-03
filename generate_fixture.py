# /// script
# dependencies = [
#   "requests",
#   "dateparser",
# ]
# ///

import json
import re
import sys
from pathlib import Path
from typing import Optional

# Assuming your CLI tool is saved as main.py as referenced in your tests
from main import (
    SORT_BY_POPULAR,
    YT_CFG_RE,
    YT_HIDDEN_INPUT_RE,
    YT_INITIAL_DATA_RE,
    YOUTUBE_CONSENT_URL,
    YOUTUBE_VIDEO_URL,
    YoutubeCommentDownloader,
)


def generate_fixture(video_id: str, output_path: Path) -> None:
    downloader = YoutubeCommentDownloader()
    url = YOUTUBE_VIDEO_URL.format(youtube_id=video_id)

    print(f"Fetching initial page for video: {video_id}...")
    response = downloader.session.get(url)

    # Handle EU cookie consent if redirected
    if "consent" in str(response.url):
        params = dict(re.findall(YT_HIDDEN_INPUT_RE, response.text))
        params.update(
            {"continue": url, "set_eom": False, "set_ytc": True, "set_apyt": True}
        )
        response = downloader.session.post(YOUTUBE_CONSENT_URL, params=params)

    html = response.text

    # Extract ytcfg
    ytcfg_str = downloader.regex_search(html, YT_CFG_RE, default="")
    if not ytcfg_str:
        print("Error: Could not extract ytcfg from the page.", file=sys.stderr)
        sys.exit(1)

    ytcfg = json.loads(ytcfg_str)

    # Extract Initial Data
    data_str = downloader.regex_search(html, YT_INITIAL_DATA_RE, default="")
    data = json.loads(data_str) if data_str else {}

    # Navigate to the first continuation token (simulating the scraper)
    sort_menu = next(downloader.search_dict(data, "sortFilterSubMenuRenderer"), {}).get(
        "subMenuItems", []
    )
    if not sort_menu:
        section_list = next(downloader.search_dict(data, "sectionListRenderer"), {})
        continuations = list(
            downloader.search_dict(section_list, "continuationEndpoint")
        )
        if not continuations:
            print(
                "Error: Comments are likely disabled for this video.", file=sys.stderr
            )
            sys.exit(1)
        data = downloader.ajax_request(continuations[0], ytcfg)
        sort_menu = next(
            downloader.search_dict(data, "sortFilterSubMenuRenderer"), {}
        ).get("subMenuItems", [])

    if not sort_menu:
        print("Error: Failed to find sort menu.", file=sys.stderr)
        sys.exit(1)

    continuation_endpoint = sort_menu[SORT_BY_POPULAR]["serviceEndpoint"]

    print("Fetching internal API payload...")
    response_data = downloader.ajax_request(continuation_endpoint, ytcfg)

    if not response_data:
        print("Error: Received empty response from AJAX request.", file=sys.stderr)
        sys.exit(1)

    # Compile the fixture
    fixture = {"ytcfg": ytcfg, "response_data": response_data}

    # Ensure directory exists and write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")

    print(f"Success! Fixture saved to {output_path.resolve()}")


def main() -> None:
    video_id = sys.argv[1] if len(sys.argv) > 1 else "dQw4w9WgXcQ"

    # Resolves to ./fixtures/youtube_comment_payload.json relative to this script
    dest_path = Path(__file__).parent / "fixtures" / "youtube_comment_payload.json"

    generate_fixture(video_id, dest_path)


if __name__ == "__main__":
    main()
