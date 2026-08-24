"""Pixel dimensions read from a file's own header.

The Graph CDN does not report them and neither does yt-dlp on the path we
use, so the only honest source is the bytes we just wrote. A payload that
cannot say how big a picture is forces whoever receives it to open every
file to find out.

Everything here returns None rather than raising: a dimension we cannot read
is a missing field, never a failed download.
"""

import struct
from pathlib import Path

# Start-of-frame markers carry the size. The others are skipped by length.
_JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}

Size = tuple[int, int] | None


def _jpeg(fh) -> Size:
    fh.seek(2)  # past SOI
    while True:
        byte = fh.read(1)
        if not byte:
            return None
        if byte != b"\xff":
            continue
        marker = fh.read(1)
        while marker == b"\xff":  # fill bytes are legal between markers
            marker = fh.read(1)
        if not marker:
            return None
        code = marker[0]
        if code in _JPEG_SOF:
            fh.read(3)  # segment length, then sample precision
            height, width = struct.unpack(">HH", fh.read(4))
            return width, height
        length = fh.read(2)
        if len(length) < 2:
            return None
        fh.seek(struct.unpack(">H", length)[0] - 2, 1)


def _png(fh) -> Size:
    fh.seek(16)  # signature, IHDR length and type
    raw = fh.read(8)
    if len(raw) < 8:
        return None
    width, height = struct.unpack(">II", raw)
    return width, height


def _mp4(fh) -> Size:
    """Walk the box tree to tkhd, whose last two fields are the size.

    Only descends the containers that can hold it, so a large mdat is
    skipped rather than read.
    """
    def walk(start: int, end: int, depth: int) -> Size:
        pos = start
        while pos < end and depth < 5:
            fh.seek(pos)
            header = fh.read(8)
            if len(header) < 8:
                return None
            size = struct.unpack(">I", header[:4])[0]
            kind = header[4:8]
            if size == 0:
                size = end - pos
            elif size == 1:  # 64 bit size follows the header
                extended = fh.read(8)
                if len(extended) < 8:
                    return None
                size = struct.unpack(">Q", extended)[0]
            if size < 8:
                return None

            if kind == b"tkhd":
                fh.seek(pos + 8)
                version = fh.read(1)[0]
                # The width and height are the last eight bytes, as 16.16
                # fixed point.
                fh.seek(pos + size - 8)
                raw = fh.read(8)
                if len(raw) < 8:
                    return None
                width, height = struct.unpack(">II", raw)
                found = (width >> 16, height >> 16)
                # A track with no visual size is audio; keep looking.
                if found[0] and found[1]:
                    return found
                _ = version
            elif kind in (b"moov", b"trak", b"mdia"):
                inner = walk(pos + 8, pos + size, depth + 1)
                if inner:
                    return inner

            pos += size
        return None

    fh.seek(0, 2)
    return walk(0, fh.tell(), 0)


def dimensions(path: Path) -> Size:
    """Width and height, or None when the format is one we cannot read."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if head[:2] == b"\xff\xd8":
                return _jpeg(fh)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return _png(fh)
            if head[4:8] == b"ftyp":
                return _mp4(fh)
    except (OSError, struct.error, IndexError):
        return None
    return None
