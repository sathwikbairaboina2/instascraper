import struct
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import paths
from app.ig import types as t


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A real, solid-colour PNG.

    The fake used to write plain text into .jpg files, which is fine for
    assertions and useless in a browser -- every tile rendered as a broken
    image. Emitting decodable bytes costs a few lines and makes a
    fake-adapter stack actually demonstrable.
    """
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _colour(seed: str) -> tuple[int, int, int]:
    """Stable, distinct-ish colour per shortcode so tiles differ visibly."""
    h = zlib.crc32(seed.encode())
    # Floor well above the page background so every tile reads as an image.
    return (
        100 + (h % 130),
        100 + ((h >> 8) % 130),
        100 + ((h >> 16) % 130),
    )


@dataclass
class CallRecord:
    method: str
    started: float
    ended: float


@dataclass
class FakeAdapter:
    """In-memory IgAdapter used by every test that is not marked `live`."""

    profiles: dict[str, t.IgProfile] = field(default_factory=dict)
    posts: dict[str, list[t.IgPost]] = field(default_factory=dict)
    calls: list[CallRecord] = field(default_factory=list)
    _pending: dict[str, Exception] = field(default_factory=dict)
    delay: float = 0.0
    # One instant per adapter, not per call: a test that reads the same post
    # twice must see the same date both times.
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ---- test controls -------------------------------------------------
    def add_profile(self, username: str, post_count: int = 0, is_private: bool = False):
        self.profiles[username] = t.IgProfile(
            username=username,
            user_id=f"id-{username}",
            full_name=username.title(),
            biography="bio",
            is_private=is_private,
            post_count=post_count,
            avatar_url=f"https://cdn.test/{username}/avatar.jpg",
        )

    def add_posts(
        self,
        username: str,
        count: int,
        child_count: int = 1,
        video: bool = False,
        tags: tuple[str, ...] = (),
        hours_ago: float | None = None,
        likes: int | None = None,
        comments: int | None = None,
        views: int | None = None,
    ):
        """Add posts to a profile's bucket.

        `hours_ago` dates the first post relative to this adapter's start and
        walks an hour further back per post. Left out, posts keep the fixed
        January dates the older tests were written against.
        """
        bucket = self.posts.setdefault(username, [])
        start = len(bucket)
        for i in range(start, start + count):
            shortcode = f"{username}-{i}"
            kind = "carousel" if child_count > 1 else ("reel" if video else "image")
            if hours_ago is None:
                taken = f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00"
            else:
                taken = (
                    self.started_at - timedelta(hours=hours_ago + (i - start))
                ).isoformat()
            caption = " ".join([f"caption {i}", *(f"#{tag}" for tag in tags)])
            bucket.append(
                t.IgPost(
                    shortcode=shortcode,
                    kind=kind,
                    taken_at_iso=taken,
                    caption=caption,
                    is_video=video,
                    child_count=child_count,
                    thumb_url=f"https://cdn.test/{shortcode}/thumb.jpg",
                    ig_url=f"https://instagram.com/p/{shortcode}/",
                    # Engagement varies per post so a ranking has something to
                    # order. Views are reels-only, matching Business Discovery:
                    # a fake that put them on images would let a bug that reads
                    # views off the wrong post type pass every test.
                    like_count=likes if likes is not None else 100 + i * 37,
                    comments_count=comments if comments is not None else 5 + i * 3,
                    view_count=(
                        (views if views is not None else 5000 + i * 911)
                        if video
                        else None
                    ),
                )
            )

    def raise_on(self, method: str, exc: Exception) -> None:
        """Next call to `method` raises `exc`, once."""
        self._pending[method] = exc

    # ---- internals -----------------------------------------------------
    def _enter(self, method: str) -> float:
        if self.delay:
            time.sleep(self.delay)
        started = time.monotonic()
        exc = self._pending.pop(method, None)
        if exc is not None:
            self.calls.append(CallRecord(method, started, time.monotonic()))
            raise exc
        return started

    def _exit(self, method: str, started: float) -> None:
        self.calls.append(CallRecord(method, started, time.monotonic()))

    def _find_post(self, shortcode: str) -> t.IgPost:
        for bucket in self.posts.values():
            for post in bucket:
                if post.shortcode == shortcode:
                    return post
        raise t.IgNotFound(shortcode)

    # ---- IgAdapter -----------------------------------------------------
    def fetch_profile(self, username: str) -> t.IgProfile:
        started = self._enter("fetch_profile")
        try:
            profile = self.profiles.get(username)
            if profile is None:
                raise t.IgNotFound(username)
            return profile
        finally:
            self._exit("fetch_profile", started)

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> t.IgPage:
        started = self._enter("fetch_page")
        try:
            bucket = self.posts.get(username, [])
            offset = int(cursor) if cursor else 0
            window = bucket[offset : offset + limit]
            nxt = offset + len(window)
            return t.IgPage(posts=window, next_cursor=str(nxt) if nxt < len(bucket) else None)
        finally:
            self._exit("fetch_page", started)

    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: t.MediaHint | None = None
    ) -> list[t.SavedFile]:
        started = self._enter("fetch_media")
        try:
            post = self._find_post(shortcode)
            ext = "mp4" if post.is_video else "jpg"
            indices = [0] if post.child_count == 1 else list(range(1, post.child_count + 1))
            saved = []
            for idx in indices:
                dest = dest_dir / paths.full_filename(idx, ext)
                if post.is_video:
                    payload = f"{shortcode}:{idx}".encode()
                else:
                    payload = _png(240, 240, _colour(f"{shortcode}:{idx}"))
                size = paths.atomic_write(dest, lambda fh, p=payload: fh.write(p))
                saved.append(
                    t.SavedFile(
                        child_idx=idx,
                        path=dest,
                        mime="video/mp4" if post.is_video else "image/png",
                        bytes=size,
                        width=240,
                        height=240,
                    )
                )
            return saved
        finally:
            self._exit("fetch_media", started)

    def fetch_url(
        self, url: str, media_root: Path
    ) -> tuple[str, t.IgPost, list[t.SavedFile]]:
        started = self._enter("fetch_url")
        try:
            from app.services.urls import parse_shortcode

            shortcode = parse_shortcode(url)
            if shortcode is None:
                raise t.IgNotFound(url)
            for username, bucket in self.posts.items():
                for post in bucket:
                    if post.shortcode == shortcode:
                        dest_dir = paths.item_dir(media_root, username, shortcode)
                        saved = self.fetch_media(shortcode, dest_dir)
                        return username, post, saved
            raise t.IgNotFound(shortcode)
        finally:
            self._exit("fetch_url", started)

    def download_to(self, url: str, dest: Path) -> t.SavedFile:
        started = self._enter("download_to")
        try:
            payload = _png(160, 160, _colour(url))
            size = paths.atomic_write(dest, lambda fh: fh.write(payload))
            return t.SavedFile(0, dest, "image/png", size, 160, 160)
        finally:
            self._exit("download_to", started)

    def login(self) -> None:
        started = self._enter("login")
        self._exit("login", started)


def seeded_adapter() -> FakeAdapter:
    """The canonical fake dataset.

    Shared by scripts/seed_e2e.py and by make_adapter() when IG_ADAPTER=fake,
    so a fake-adapter stack can actually serve the media it seeded. Without a
    single source, the seeded database references posts the running server's
    adapter has never heard of and every media_fetch fails with IgNotFound.

    Dates are relative because the trending feed asks "in the last 24
    hours", and a dataset pinned to January can only ever answer "nothing".
    """
    adapter = FakeAdapter()
    adapter.add_profile("nike", post_count=8)
    # Today: two tags, overlapping, so the day feed has a ranking to show.
    adapter.add_posts("nike", count=3, tags=("nike", "justdoit"), hours_ago=2)
    adapter.add_posts("nike", count=3, tags=("running",), hours_ago=6)
    # Earlier in the week: present under `week`, absent under `day`, which is
    # what makes the two windows visibly different.
    adapter.add_posts(
        "nike", count=2, child_count=3, tags=("nike", "gear"), hours_ago=72
    )
    # Two reels: without them the REELS tab has nothing to prove itself on,
    # and views never contribute to a score.
    adapter.add_posts("nike", count=2, video=True, tags=("training",), hours_ago=30)
    return adapter
