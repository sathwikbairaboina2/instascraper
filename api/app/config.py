import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ig_username: str
    ig_password: str
    db_path: Path
    media_dir: Path
    session_dir: Path
    out_dir: Path
    page_size: int
    first_page_size: int
    ig_min_interval: float
    ig_backoff: int
    adapter: str
    anonymous: bool
    max_sleep: float


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    username = os.environ.get("IG_USERNAME", "")
    password = os.environ.get("IG_PASSWORD", "")
    # No credentials means anonymous rather than broken: the app still runs and
    # reports what Instagram says. IG_ANONYMOUS forces it even when set.
    anonymous = _truthy(os.environ.get("IG_ANONYMOUS", "")) or not (username and password)

    return Settings(
        ig_username=username,
        ig_password=password,
        db_path=Path(os.environ.get("DB_PATH", "/data/app.db")),
        media_dir=Path(os.environ.get("MEDIA_DIR", "/data/media")),
        session_dir=Path(os.environ.get("SESSION_DIR", "/data/session")),
        out_dir=Path(os.environ.get("OUT_DIR_CONTAINER", "/out")),
        page_size=int(os.environ.get("PAGE_SIZE", "36")),
        # The first page is spent before the user has confirmed the profile is
        # the right one, and every post on it costs a thumbnail request. Keep
        # it small; "Load more" is where a full page is asked for.
        first_page_size=int(os.environ.get("FIRST_PAGE_SIZE", "3")),
        ig_min_interval=float(os.environ.get("IG_MIN_INTERVAL", "3")),
        ig_backoff=int(os.environ.get("IG_BACKOFF", "900")),
        adapter=os.environ.get("IG_ADAPTER", "real"),
        anonymous=anonymous,
        max_sleep=float(os.environ.get("IG_MAX_SLEEP", "60")),
    )
