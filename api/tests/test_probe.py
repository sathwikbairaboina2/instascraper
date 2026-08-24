import struct

from app.probe import dimensions


def write_jpeg(path, width, height):
    """Enough of a JPEG to be read: SOI, a skipped segment, then SOF0."""
    body = b"\xff\xd8"
    comment = b"hello there"
    body += b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
    body += b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width)
    body += b"\x00" * 6
    path.write_bytes(body)


def write_png(path, width, height):
    body = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
    body += struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    path.write_bytes(body)


def write_mp4(path, width, height):
    """moov > trak > tkhd, with the size in the last eight bytes."""
    tkhd_body = b"\x00" * 76 + struct.pack(">II", width << 16, height << 16)
    tkhd = struct.pack(">I", 8 + len(tkhd_body)) + b"tkhd" + tkhd_body
    trak = struct.pack(">I", 8 + len(tkhd)) + b"trak" + tkhd
    moov = struct.pack(">I", 8 + len(trak)) + b"moov" + trak
    ftyp = struct.pack(">I", 16) + b"ftyp" + b"isom" + b"\x00" * 4
    path.write_bytes(ftyp + moov)


def test_reads_a_jpeg(tmp_path):
    p = tmp_path / "a.jpg"
    write_jpeg(p, 1080, 1350)

    assert dimensions(p) == (1080, 1350)


def test_reads_a_png(tmp_path):
    p = tmp_path / "a.png"
    write_png(p, 640, 480)

    assert dimensions(p) == (640, 480)


def test_reads_an_mp4(tmp_path):
    p = tmp_path / "a.mp4"
    write_mp4(p, 720, 1280)

    assert dimensions(p) == (720, 1280)


def test_an_unreadable_file_is_a_missing_dimension_not_a_crash(tmp_path):
    """A format we cannot read must never fail a download that worked."""
    p = tmp_path / "a.bin"
    p.write_bytes(b"not a picture at all")

    assert dimensions(p) is None


def test_a_truncated_jpeg_gives_up_quietly(tmp_path):
    p = tmp_path / "cut.jpg"
    p.write_bytes(b"\xff\xd8\xff\xc0\x00")

    assert dimensions(p) is None


def test_a_missing_file_is_none(tmp_path):
    assert dimensions(tmp_path / "nope.jpg") is None
