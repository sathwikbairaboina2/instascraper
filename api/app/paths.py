import os
import shutil
import unicodedata
from pathlib import Path
from typing import BinaryIO, Callable

PostFiles = tuple[str, list[tuple[int, str]]]
NamedFile = tuple[str, int, str]

# Letters, numbers and marks, plus underscore and its relatives. Marks are the
# reason this is a category test rather than a regex class: `\w` excludes
# combining marks, so a Devanagari name is cut at its first vowel sign and the
# feature quietly becomes Latin-only. Same rule the hashtag parser uses, for
# the same reason.
_KEEP = ("L", "N", "M")

# Leaves room for the `_07b.jpg` that gets appended, well inside the 255-byte
# component limit every filesystem we care about enforces. A name longer than
# this is truncated rather than refused: the alternative is an OSError from
# deep inside the writer, which is what this used to do.
MAX_BASE = 120


def item_dir(media_root: Path, username: str, shortcode: str) -> Path:
    return media_root / username / shortcode


def rel_path(media_root: Path, absolute: Path) -> str:
    return absolute.relative_to(media_root).as_posix()


def full_filename(child_idx: int, ext: str) -> str:
    return f"full.{ext}" if child_idx == 0 else f"full_{child_idx}.{ext}"


def sanitize_base(base: str) -> str:
    """Collapse anything that cannot be part of a name into a single underscore.

    Path separators and traversal sequences cannot survive this, so a base
    filename can never escape the output directory.

    Unicode letters are kept. Stripping them would silently delete most of a
    name written in Hindi, Arabic or Japanese, and collapse two different
    non-Latin names onto the same `download` fallback.
    """
    out: list[str] = []
    for ch in base.strip():
        category = unicodedata.category(ch)
        if category[0] in _KEEP or category == "Pc":
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")

    cleaned = "".join(out).strip("_")
    # Truncating can strand a trailing underscore that was legal mid-name.
    return cleaned[:MAX_BASE].strip("_") or "download"


def download_names(posts: list[PostFiles], base: str) -> list[NamedFile]:
    width = max(2, len(str(len(posts))))
    out: list[NamedFile] = []
    for index, (shortcode, files) in enumerate(posts, start=1):
        num = str(index).zfill(width)
        if len(files) == 1:
            child_idx, ext = files[0]
            out.append((shortcode, child_idx, f"{base}_{num}.{ext}"))
            continue
        for offset, (child_idx, ext) in enumerate(files):
            letter = chr(ord("a") + offset)
            out.append((shortcode, child_idx, f"{base}_{num}{letter}.{ext}"))
    return out


def atomic_write(dest: Path, write: Callable[[BinaryIO], None]) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with part.open("wb") as fh:
            write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        size = part.stat().st_size
        os.replace(part, dest)
        return size
    except BaseException:
        # The cleanup must not raise over the top of the real failure. An
        # unwritable path fails the unlink for the same reason it failed the
        # open, and the second error is the one that reaches the caller --
        # naming the tidy-up instead of the problem.
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_copy(src: Path, dest: Path) -> None:
    with src.open("rb") as fh:
        atomic_write(dest, lambda out: shutil.copyfileobj(fh, out))


def unique_dest(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 1
    while True:
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
