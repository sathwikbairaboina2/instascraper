import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    media_dir: Path
    out_dir: Path
    page_size: int
    first_page_size: int
    ig_min_interval: float
    cdn_min_interval: float
    ig_backoff: int
    adapter: str
    graph_token: str
    graph_user_id: str
    graph_version: str
    graph_refresh_pages: int
    graph_usage_limit: float
    reel_max_per_hour: int
    reel_max_per_day: int
    reel_timeout: float
    reel_min_interval: float
    # Where prepared recreate payloads are handed to instacreator. Empty
    # endpoint means the handoff is off and submit answers 503.
    sqs_endpoint: str = ""
    sqs_queue: str = "recreate-jobs"


def load_settings() -> Settings:
    return Settings(
        db_path=Path(os.environ.get("DB_PATH", "/data/app.db")),
        media_dir=Path(os.environ.get("MEDIA_DIR", "/data/media")),
        out_dir=Path(os.environ.get("OUT_DIR_CONTAINER", "/out")),
        page_size=int(os.environ.get("PAGE_SIZE", "36")),
        # A Graph page of 200 costs the same single call as a page of 3, so
        # this is bounded by thumbnail fetches rather than by quota. Twelve
        # fills the first screen of the grid.
        first_page_size=int(os.environ.get("FIRST_PAGE_SIZE", "12")),
        ig_min_interval=float(os.environ.get("IG_MIN_INTERVAL", "3")),
        # Thumbnails and avatars come from Meta's CDN, which does not spend
        # the Graph quota. Pacing them is politeness, not rate-limit
        # avoidance, so the floor is far below the one on api calls.
        cdn_min_interval=float(os.environ.get("IG_CDN_MIN_INTERVAL", "0.5")),
        ig_backoff=int(os.environ.get("IG_BACKOFF", "900")),
        adapter=os.environ.get("IG_ADAPTER", "graph"),
        graph_token=os.environ.get("IG_GRAPH_TOKEN", ""),
        graph_user_id=os.environ.get("IG_GRAPH_USER_ID", ""),
        # Deliberately no source-level default: pinning a Graph version in
        # code means a Meta deprecation becomes a code change.
        graph_version=os.environ.get("IG_GRAPH_VERSION", ""),
        # How many pages deep to look when refreshing an expired media url.
        graph_refresh_pages=int(os.environ.get("IG_GRAPH_REFRESH_PAGES", "2")),
        graph_usage_limit=float(os.environ.get("IG_GRAPH_USAGE_LIMIT", "90")),
        # Our own caps on scraping instagram.com for reel video, which the
        # Graph API will not serve. Conservative rather than authoritative:
        # Instagram publishes no thresholds, so these are a footprint we
        # chose, not a line anyone drew for us.
        reel_max_per_hour=int(os.environ.get("IG_REEL_MAX_PER_HOUR", "20")),
        reel_max_per_day=int(os.environ.get("IG_REEL_MAX_PER_DAY", "100")),
        reel_timeout=float(os.environ.get("IG_REEL_TIMEOUT", "120")),
        reel_min_interval=float(os.environ.get("IG_REEL_MIN_INTERVAL", "20")),
        sqs_endpoint=os.environ.get("SQS_ENDPOINT", ""),
        sqs_queue=os.environ.get("SQS_QUEUE", "recreate-jobs"),
    )
