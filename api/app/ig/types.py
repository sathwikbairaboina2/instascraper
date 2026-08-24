from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class IgError(Exception):
    """Base for every failure the adapter is allowed to raise."""


class IgNotFound(IgError):
    """Profile or post does not exist. Terminal."""


class IgPrivate(IgError):
    """Profile exists but is not public. Terminal, out of scope."""


class IgRateLimited(IgError):
    """429 or equivalent. Trips the breaker temporarily.

    `retry_after` is how long Instagram asked us to wait. Honour it: coming
    back sooner than requested is what turns a rate limit into a blocked IP.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


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
    # Business Discovery always returns this; the fake adapter and older
    # recorded payloads do not, so it defaults rather than being required.
    followers_count: int = 0


@dataclass(frozen=True)
class MediaSource:
    """One downloadable file belonging to a post.

    `child_idx` is 0 for a single-media post and 1..N for carousel children,
    matching `paths.full_filename`.
    """

    child_idx: int
    url: str
    mime: str
    is_video: bool


@dataclass(frozen=True)
class MediaHint:
    """What the handler knows about a post that the adapter cannot look up.

    Business Discovery has no per-media endpoint, so refreshing an expired
    url means re-listing the owning profile. The adapter has no database
    access, so the handler passes the owner and the last known urls here.
    """

    username: str
    sources: tuple[MediaSource, ...]
    captured_at: str


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
    sources: tuple[MediaSource, ...] = ()


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


@runtime_checkable
class IgAdapter(Protocol):
    def fetch_profile(self, username: str) -> IgProfile: ...

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> IgPage: ...

    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: MediaHint | None = None
    ) -> list[SavedFile]: ...

    def download_to(self, url: str, dest: Path) -> SavedFile: ...

    def login(self) -> None: ...
