# YouTube Comment Fetcher

A fast, minimalist CLI tool to scrape YouTube comments without requiring a YouTube Data API key. Designed to be "pipe-friendly" for data extraction, NLP processing, and terminal workflows.

## Features

* **No API Key Required:** Uses YouTube's internal AJAX API.
* **Flexible Output:** Supports `json`, `jsonl` (for streaming/piping), `csv`, and `text`.
* **Smart Filtering:** Filter by minimum likes, maximum comment age, or exclude replies.
* **Sorting:** Fetch "Top" comments or "Newest" first.
* **Zero System Clutter:** Designed to be run instantly via `uvx` without global installation.

## Prerequisites

You need to have [uv](https://docs.astral.sh/uv/) installed on your system:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Usage

You can run the tool directly from the repository using `uvx`:

```bash
uvx git+https://github.com/dev-ansung/youtube-comment-fetcher "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Examples

**1. Quick Text Preview:**
Get a readable text output of the top 50 comments.
```bash
uvx git+https://github.com/dev-ansung/youtube-comment-fetcher "dQw4w9WgXcQ" \
  --limit 50 \
  --format text
```

**2. Data Pipeline (JSONL + jq):**
Stream output as JSON Lines and extract only the comment text.
```bash
uvx git+https://github.com/dev-ansung/youtube-comment-fetcher "dQw4w9WgXcQ" \
  --format jsonl | jq -r '.text'
```

**3. Advanced Filtering to CSV:**
Export top-level comments (no replies) from the last 30 days that have at least 100 likes.
```bash
uvx git+https://github.com/dev-ansung/youtube-comment-fetcher "dQw4w9WgXcQ" \
  --no-replies \
  --age 30 \
  --min-likes 100 \
  --format csv > comments.csv
```

## Options

| Flag | Default | Description |
| :--- | :--- | :--- |
| `url` | **Required** | The full YouTube video URL or 11-character Video ID. |
| `--limit` | `100` | Maximum number of comments to fetch. Set to `0` for no limit. |
| `--sort` | `top` | Sort order: `top` (Popular) or `new` (Recent). |
| `--language` | `None` | Optional language code (e.g., `en`, `es`) to influence parsing. |
| `--format` | `json` | Output format: `json`, `jsonl`, `csv`, or `text`. |
| `--pretty` | `False` | Indent standard `json` output for readability. |
| `--no-replies`| `False` | Only fetch top-level comments (skip reply threads). |
| `--min-likes` | `0` | Skip comments with fewer than this many likes. |
| `--age` | `None` | Maximum age of comments to fetch, in days. |

## Data Schema (JSON/JSONL/CSV)

The exported data contains the following fields:

* `cid`: Unique comment ID
* `text`: The comment content
* `time`: Human-readable time (e.g., "3 days ago")
* `time_parsed`: Unix timestamp of the comment
* `author`: Display name of the commenter
* `channel`: YouTube channel ID of the author
* `votes`: Formatted like count (e.g., "1.5K")
* `replies`: Number of replies to this comment
* `photo`: URL to the author's avatar
* `heart`: Boolean indicating if the creator hearted the comment
* `reply`: Boolean indicating if this is a reply to another comment
* `paid`: (Optional) Text indicating Super Thanks or paid amount

## Development & Testing

Clone the repository to run tests or update fixtures:

```bash
git clone https://github.com/dev-ansung/youtube-comment-fetcher.git
cd youtube-comment-fetcher

# Run the test suite
uv run python -m unittest discover -s tests -v

# Generate a new mock payload fixture for testing
uv run generate_fixture.py
```

## License

MIT