import sqlite3

from app import paths
from app.config import Settings
from app.services import activity


class NotReady(Exception):
    def __init__(self, shortcodes: list[str]):
        super().__init__(", ".join(shortcodes))
        self.shortcodes = shortcodes


def collect(conn: sqlite3.Connection, shortcodes: list[str]) -> list[paths.PostFiles]:
    """Resolve a selection into ordered (shortcode, [(child_idx, ext)]) pairs.

    Ordered oldest-first so the generated sequence reads chronologically,
    which is the opposite of the newest-first grid on purpose.
    """
    placeholders = ",".join("?" * len(shortcodes))
    rows = conn.execute(
        f"SELECT shortcode, full_status FROM media_items WHERE shortcode IN ({placeholders})"
        " ORDER BY taken_at ASC, shortcode",
        shortcodes,
    ).fetchall()

    found = {r["shortcode"] for r in rows}
    not_ready = [s for s in shortcodes if s not in found]
    not_ready += [r["shortcode"] for r in rows if r["full_status"] != "ready"]
    if not_ready:
        raise NotReady(sorted(set(not_ready)))

    out: list[paths.PostFiles] = []
    for row in rows:
        files = conn.execute(
            "SELECT child_idx, path FROM media_files WHERE shortcode=? AND role='full'"
            " ORDER BY child_idx",
            (row["shortcode"],),
        ).fetchall()
        out.append(
            (row["shortcode"], [(f["child_idx"], f["path"].rsplit(".", 1)[-1]) for f in files])
        )
    return out


def run(conn: sqlite3.Connection, settings: Settings, shortcodes: list[str], base: str) -> dict:
    posts = collect(conn, shortcodes)
    safe_base = paths.sanitize_base(base)
    named = paths.download_names(posts, safe_base)

    settings.out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for shortcode, child_idx, filename in named:
        row = conn.execute(
            "SELECT path FROM media_files WHERE shortcode=? AND role='full' AND child_idx=?",
            (shortcode, child_idx),
        ).fetchone()
        src = settings.media_dir / row["path"]
        dest = paths.unique_dest(settings.out_dir, filename)
        paths.atomic_copy(src, dest)
        written.append(dest.name)

    activity.record(
        conn,
        "download",
        posts[0][0] if len(posts) == 1 else None,
        {
            "base": safe_base,
            "count": len(written),
            "out": str(settings.out_dir),
            "shortcodes": [p[0] for p in posts],
        },
    )
    return {"written": written, "out_dir": str(settings.out_dir), "count": len(written)}
