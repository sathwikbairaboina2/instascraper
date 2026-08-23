import json
from datetime import datetime, timezone
from pathlib import Path

import instaloader
import instaloader.exceptions as ie

from app import paths
from app.config import Settings
from app.ig import types as t
from app.ig.rate import PacedRateController

_CHALLENGE_HINTS = ("checkpoint", "challenge", "login_required", "please wait")


def classify(exc: Exception) -> t.IgError:
    """Map an Instaloader failure onto the five cases the runner handles.

    When Instagram rotates something, this is usually the first function
    that needs updating.
    """
    message = str(exc)
    if isinstance(
        exc,
        (
            ie.ProfileNotExistsException,
            ie.PostChangedException,
            ie.QueryReturnedNotFoundException,
        ),
    ):
        return t.IgNotFound(message)
    if isinstance(
        exc, (ie.PrivateProfileNotFollowedException, ie.ProfileHasNoPicsException)
    ):
        return t.IgPrivate(message)
    if isinstance(exc, ie.TooManyRequestsException):
        return t.IgRateLimited(message)
    if isinstance(
        exc,
        (
            ie.LoginRequiredException,
            ie.LoginException,
            ie.BadCredentialsException,
            ie.TwoFactorAuthRequiredException,
            ie.QueryReturnedForbiddenException,
        ),
    ):
        return t.IgChallenge(message)
    if any(hint in message.lower() for hint in _CHALLENGE_HINTS):
        return t.IgChallenge(message)
    return t.IgTransient(message)


def _caption(node: dict) -> str:
    edges = node.get("edge_media_to_caption", {}).get("edges", [])
    return edges[0]["node"]["text"] if edges else ""


def _kind(node: dict) -> str:
    typename = node.get("__typename", "")
    if typename == "GraphSidecar":
        return "carousel"
    if node.get("is_video"):
        return "reel" if node.get("product_type") == "clips" else "video"
    return "image"


def _dimensions(node: dict) -> tuple[int | None, int | None]:
    dims = node.get("dimensions") or {}
    return dims.get("width"), dims.get("height")


def post_to_igpost(node: dict, shortcode: str) -> t.IgPost:
    children = node.get("edge_sidecar_to_children", {}).get("edges", [])
    taken = datetime.fromtimestamp(node["taken_at_timestamp"], tz=timezone.utc)
    return t.IgPost(
        shortcode=shortcode,
        kind=_kind(node),
        taken_at_iso=taken.isoformat(),
        caption=_caption(node),
        is_video=bool(node.get("is_video")),
        child_count=len(children) or 1,
        thumb_url=node.get("thumbnail_src") or node["display_url"],
        ig_url=f"https://www.instagram.com/p/{shortcode}/",
    )


class InstaloaderAdapter:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._loader = instaloader.Instaloader(
            quiet=True,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            rate_controller=lambda ctx: PacedRateController(ctx, settings.ig_min_interval),
        )
        self._session_file = settings.session_dir / f"{settings.ig_username}.session"
        self._logged_in = False

    # ---- session -------------------------------------------------------
    def login(self) -> None:
        try:
            if self._session_file.exists():
                self._loader.load_session_from_file(
                    self._settings.ig_username, str(self._session_file)
                )
            else:
                self._loader.login(self._settings.ig_username, self._settings.ig_password)
                self._session_file.parent.mkdir(parents=True, exist_ok=True)
                self._loader.save_session_to_file(str(self._session_file))
            self._logged_in = True
        except Exception as exc:
            raise classify(exc) from exc

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    # ---- reads ---------------------------------------------------------
    def fetch_profile(self, username: str) -> t.IgProfile:
        self._ensure_login()
        try:
            p = instaloader.Profile.from_username(self._loader.context, username)
            return t.IgProfile(
                username=p.username,
                user_id=str(p.userid),
                full_name=p.full_name or "",
                biography=p.biography or "",
                is_private=bool(p.is_private),
                post_count=int(p.mediacount),
                avatar_url=p.profile_pic_url,
            )
        except Exception as exc:
            raise classify(exc) from exc

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> t.IgPage:
        self._ensure_login()
        try:
            profile = instaloader.Profile.from_username(self._loader.context, username)
            iterator = profile.get_posts()
            if cursor:
                frozen = instaloader.FrozenNodeIterator(**json.loads(cursor))
                iterator.thaw(frozen)

            posts: list[t.IgPost] = []
            exhausted = False
            for _ in range(limit):
                try:
                    post = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                posts.append(post_to_igpost(post._node, post.shortcode))

            next_cursor = None if exhausted else json.dumps(iterator.freeze()._asdict())
            return t.IgPage(posts=posts, next_cursor=next_cursor)
        except Exception as exc:
            raise classify(exc) from exc

    def fetch_media(self, shortcode: str, dest_dir: Path) -> list[t.SavedFile]:
        self._ensure_login()
        try:
            post = instaloader.Post.from_shortcode(self._loader.context, shortcode)
            targets: list[tuple[int, str, bool, int | None, int | None]] = []
            if post.typename == "GraphSidecar":
                for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                    url = node.video_url if node.is_video else node.display_url
                    targets.append((idx, url, node.is_video, None, None))
            else:
                url = post.video_url if post.is_video else post.url
                width, height = _dimensions(post._node)
                targets.append((0, url, post.is_video, width, height))

            saved: list[t.SavedFile] = []
            for child_idx, url, is_video, width, height in targets:
                ext = "mp4" if is_video else "jpg"
                dest = dest_dir / paths.full_filename(child_idx, ext)
                saved.append(
                    self._download(
                        url,
                        dest,
                        child_idx,
                        "video/mp4" if is_video else "image/jpeg",
                        width,
                        height,
                    )
                )
            return saved
        except t.IgError:
            raise
        except Exception as exc:
            raise classify(exc) from exc

    def download_to(self, url: str, dest: Path) -> t.SavedFile:
        self._ensure_login()
        return self._download(url, dest, 0, "image/jpeg", None, None)

    def _download(self, url, dest, child_idx, mime, width, height) -> t.SavedFile:
        try:
            resp = self._loader.context.get_raw(url)
            size = paths.atomic_write(dest, lambda fh: fh.write(resp.content))
        except Exception as exc:
            raise classify(exc) from exc
        return t.SavedFile(child_idx, dest, mime, size, width, height)


def make_adapter(settings: Settings):
    if settings.adapter == "fake":
        from app.ig.fake import seeded_adapter

        return seeded_adapter()
    return InstaloaderAdapter(settings)
