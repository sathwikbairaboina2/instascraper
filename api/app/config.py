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
    ig_min_interval: float
    ig_backoff: int
    adapter: str


def load_settings() -> Settings:
    return Settings(
        ig_username=os.environ.get("IG_USERNAME", ""),
        ig_password=os.environ.get("IG_PASSWORD", ""),
        db_path=Path(os.environ.get("DB_PATH", "/data/app.db")),
        media_dir=Path(os.environ.get("MEDIA_DIR", "/data/media")),
        session_dir=Path(os.environ.get("SESSION_DIR", "/data/session")),
        out_dir=Path(os.environ.get("OUT_DIR_CONTAINER", "/out")),
        page_size=int(os.environ.get("PAGE_SIZE", "36")),
        ig_min_interval=float(os.environ.get("IG_MIN_INTERVAL", "3")),
        ig_backoff=int(os.environ.get("IG_BACKOFF", "900")),
        adapter=os.environ.get("IG_ADAPTER", "real"),
    )
