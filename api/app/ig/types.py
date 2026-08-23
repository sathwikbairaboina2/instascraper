from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class IgError(Exception):
    """Base for every failure the adapter is allowed to raise."""


class IgNotFound(IgError):
    """Profile or post does not exist. Terminal."""


class IgPrivate(IgError):
    """Profile exists but is not public. Terminal, out of scope."""


class IgRateLimited(IgError):
    """429 or equivalent. Trips the breaker temporarily."""


class IgChallenge(IgError):
    """Login challenge or dead session. Trips the breaker permanently."""


class IgTransient(IgError):
    """Network blip or 5xx. Retryable."""


@dataclass(frozen=True)
class IgProfile:
    username: str
    user_id: str
    full_name: str
    biography: str
    is_private: bool
    post_count: int
    avatar_url: str


@dataclass(frozen=True)
class IgPost:
    shortcode: str
    kind: str  # image | video | reel | carousel
    taken_at_iso: str
    caption: str
    is_video: bool
    child_count: int
    thumb_url: str
    ig_url: str


@dataclass(frozen=True)
class IgPage:
    posts: list[IgPost]
    next_cursor: str | None  # None means the iterator is exhausted


@dataclass(frozen=True)
class SavedFile:
    child_idx: int
    path: Path
    mime: str
    bytes: int
    width: int | None
    height: int | None


class IgAdapter(Protocol):
    def fetch_profile(self, username: str) -> IgProfile: ...

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> IgPage: ...

    def fetch_media(self, shortcode: str, dest_dir: Path) -> list[SavedFile]: ...

    def download_to(self, url: str, dest: Path) -> SavedFile: ...

    def login(self) -> None: ...
