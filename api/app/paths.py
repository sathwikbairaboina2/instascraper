import os
import re
import shutil
from pathlib import Path
from typing import BinaryIO, Callable

PostFiles = tuple[str, list[tuple[int, str]]]
NamedFile = tuple[str, int, str]

_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def item_dir(media_root: Path, username: str, shortcode: str) -> Path:
    return media_root / username / shortcode


def rel_path(media_root: Path, absolute: Path) -> str:
    return absolute.relative_to(media_root).as_posix()


def full_filename(child_idx: int, ext: str) -> str:
    return f"full.{ext}" if child_idx == 0 else f"full_{child_idx}.{ext}"


def sanitize_base(base: str) -> str:
    """Collapse anything that is not alphanumeric into a single underscore.

    Path separators and traversal sequences cannot survive this, so a base
    filename can never escape the output directory.
    """
    cleaned = _UNSAFE.sub("_", base.strip()).strip("_")
    return cleaned or "download"


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
        part.unlink(missing_ok=True)
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
