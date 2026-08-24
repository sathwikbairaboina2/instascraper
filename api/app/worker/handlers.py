import json

from app import paths
from app.clock import now_iso
from app.ig import types as t
from app.worker.runner import HandlerContext


def handle_profile_sync(ctx: HandlerContext, payload: dict) -> None:
    username = payload["username"]

    ctx.pacer.wait()
    profile = ctx.adapter.fetch_profile(username)

    ctx.conn.execute(
        "INSERT INTO profiles (username, ig_user_id, full_name, biography,"
        " is_private, post_count, followers_count, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(username) DO UPDATE SET"
        " ig_user_id=excluded.ig_user_id, full_name=excluded.full_name,"
        " biography=excluded.biography, is_private=excluded.is_private,"
        " post_count=excluded.post_count,"
        " followers_count=excluded.followers_count",
        (
            profile.username,
            profile.user_id,
            profile.full_name,
            profile.biography,
            int(profile.is_private),
            profile.post_count,
            profile.followers_count,
            now_iso(),
        ),
    )

    if profile.is_private:
        raise t.IgPrivate(f"{username} is private")

    avatar_dest = ctx.settings.media_dir / username / "avatar.jpg"
    ctx.cdn_pacer.wait()
    ctx.adapter.download_to(profile.avatar_url, avatar_dest)

    ctx.conn.execute(
        "UPDATE profiles SET avatar_path=?, last_synced_at=? WHERE username=?",
        (paths.rel_path(ctx.settings.media_dir, avatar_dest), now_iso(), username),
    )

    row = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if row["next_cursor"] == "":
        # Exhausted, and nothing else clears that state. A sync is a
        # deliberate "look again", and Business Discovery serves newest
        # first, so the walk restarts at the front rather than resuming
        # from a cursor that has nothing left behind it.
        ctx.conn.execute(
            "UPDATE profiles SET next_cursor=NULL WHERE username=?", (username,)
        )
    elif row["next_cursor"] is not None:
        return  # a walk is already part-way through; leave its cursor alone
    ctx.enqueue("page_fetch", {"username": username})


def handle_page_fetch(ctx: HandlerContext, payload: dict) -> None:
    username = payload["username"]
    row = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if row is None:
        raise t.IgNotFound(f"{username} has not been synced")

    cursor = row["next_cursor"]
    if cursor == "":
        return  # exhausted; never hit Instagram again for this profile

    # A null cursor means nothing has been indexed yet: take the cheap first
    # page. Every later page is a deliberate "Load more".
    limit = ctx.settings.first_page_size if cursor is None else ctx.settings.page_size

    ctx.pacer.wait()
    page = ctx.adapter.fetch_page(username, cursor, limit)

    for post in page.posts:
        # Business Discovery has no per-media endpoint, so the urls in this
        # listing are the only ones we will ever be handed. Keep them.
        sources_json = json.dumps(
            [
                {
                    "child_idx": s.child_idx,
                    "url": s.url,
                    "mime": s.mime,
                    "is_video": s.is_video,
                }
                for s in post.sources
            ]
        )
        ctx.conn.execute(
            "INSERT INTO media_items (shortcode, username, kind, taken_at, caption,"
            " is_video, child_count, ig_url, discovered_at, src_urls, src_urls_at,"
            " like_count, comments_count, view_count)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(shortcode) DO UPDATE SET"
            " caption=excluded.caption, child_count=excluded.child_count,"
            " src_urls=excluded.src_urls, src_urls_at=excluded.src_urls_at,"
            # Counts move after a post is published, so a re-index refreshes
            # them rather than keeping whatever they were on first sight.
            " like_count=excluded.like_count,"
            " comments_count=excluded.comments_count,"
            " view_count=excluded.view_count",
            (
                post.shortcode,
                username,
                post.kind,
                post.taken_at_iso,
                post.caption,
                int(post.is_video),
                post.child_count,
                post.ig_url,
                now_iso(),
                sources_json,
                now_iso(),
                post.like_count,
                post.comments_count,
                post.view_count,
            ),
        )

        thumb_dest = paths.item_dir(ctx.settings.media_dir, username, post.shortcode) / "thumb.jpg"
        if not thumb_dest.exists():
            ctx.cdn_pacer.wait()
            saved = ctx.adapter.download_to(post.thumb_url, thumb_dest)
            ctx.conn.execute(
                "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
                " width, height) VALUES (?,'thumb',0,?,?,?,?,?)"
                " ON CONFLICT(shortcode, role, child_idx) DO UPDATE SET"
                " path=excluded.path, bytes=excluded.bytes",
                (
                    post.shortcode,
                    paths.rel_path(ctx.settings.media_dir, thumb_dest),
                    saved.mime,
                    saved.bytes,
                    saved.width,
                    saved.height,
                ),
            )

    ctx.conn.execute(
        "UPDATE profiles SET next_cursor=? WHERE username=?",
        ("" if page.next_cursor is None else page.next_cursor, username),
    )


def handle_media_fetch(ctx: HandlerContext, payload: dict) -> None:
    shortcode = payload["shortcode"]
    item = ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if item is None:
        raise t.IgNotFound(f"unknown shortcode {shortcode}")
    if item["full_status"] == "ready":
        return

    ctx.conn.execute(
        "UPDATE media_items SET full_status='fetching', full_error=NULL WHERE shortcode=?",
        (shortcode,),
    )

    dest_dir = paths.item_dir(ctx.settings.media_dir, item["username"], shortcode)
    # The adapter has no database access, so anything it cannot look up for
    # itself -- which profile owns this post, and the urls we last saw --
    # has to travel with the call.
    sources = tuple(
        t.MediaSource(
            child_idx=int(entry["child_idx"]),
            url=entry["url"],
            mime=entry["mime"],
            is_video=bool(entry["is_video"]),
        )
        for entry in json.loads(item["src_urls"] or "[]")
    )
    hint = t.MediaHint(
        username=item["username"],
        sources=sources,
        captured_at=item["src_urls_at"] or "",
    )
    try:
        ctx.pacer.wait()
        saved_files = ctx.adapter.fetch_media(shortcode, dest_dir, hint)
    except t.IgError as exc:
        ctx.conn.execute(
            "UPDATE media_items SET full_status='failed', full_error=? WHERE shortcode=?",
            (str(exc), shortcode),
        )
        raise

    for saved in saved_files:
        ctx.conn.execute(
            "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
            " width, height) VALUES (?,'full',?,?,?,?,?,?)"
            " ON CONFLICT(shortcode, role, child_idx) DO UPDATE SET"
            " path=excluded.path, mime=excluded.mime, bytes=excluded.bytes,"
            " width=excluded.width, height=excluded.height",
            (
                shortcode,
                saved.child_idx,
                paths.rel_path(ctx.settings.media_dir, saved.path),
                saved.mime,
                saved.bytes,
                saved.width,
                saved.height,
            ),
        )

    ctx.conn.execute(
        "UPDATE media_items SET full_status='ready', full_error=NULL WHERE shortcode=?",
        (shortcode,),
    )


HANDLERS = {
    "profile_sync": handle_profile_sync,
    "page_fetch": handle_page_fetch,
    "media_fetch": handle_media_fetch,
}
