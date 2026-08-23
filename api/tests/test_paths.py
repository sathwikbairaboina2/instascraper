import pytest

from app import paths


def test_full_filename_single_vs_carousel():
    assert paths.full_filename(0, "jpg") == "full.jpg"
    assert paths.full_filename(1, "mp4") == "full_1.mp4"
    assert paths.full_filename(12, "jpg") == "full_12.jpg"


def test_item_dir_layout(tmp_path):
    d = paths.item_dir(tmp_path, "nike", "ABC123")
    assert d == tmp_path / "nike" / "ABC123"


def test_rel_path_is_relative_to_media_root(tmp_path):
    p = tmp_path / "nike" / "ABC123" / "full.jpg"
    assert paths.rel_path(tmp_path, p) == "nike/ABC123/full.jpg"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("nike_ss26", "nike_ss26"),
        ("../../etc/passwd", "etc_passwd"),
        ("a/b\\c", "a_b_c"),
        ("  spaced  name ", "spaced_name"),
        ("", "download"),
        ("." * 5, "download"),
    ],
)
def test_sanitize_base_strips_separators_and_traversal(raw, expected):
    assert paths.sanitize_base(raw) == expected


def test_download_names_single_items_zero_padded():
    posts = [("A", [(0, "jpg")]), ("B", [(0, "mp4")]), ("C", [(0, "jpg")])]
    assert paths.download_names(posts, "trip") == [
        ("A", 0, "trip_01.jpg"),
        ("B", 0, "trip_02.mp4"),
        ("C", 0, "trip_03.jpg"),
    ]


def test_download_names_carousel_children_get_letters():
    posts = [("A", [(1, "jpg"), (2, "jpg"), (3, "mp4")]), ("B", [(0, "jpg")])]
    assert paths.download_names(posts, "set") == [
        ("A", 1, "set_01a.jpg"),
        ("A", 2, "set_01b.jpg"),
        ("A", 3, "set_01c.mp4"),
        ("B", 0, "set_02.jpg"),
    ]


def test_download_names_widen_padding_past_99():
    posts = [(f"S{i}", [(0, "jpg")]) for i in range(1, 101)]
    names = paths.download_names(posts, "big")
    assert names[0][2] == "big_001.jpg"
    assert names[-1][2] == "big_100.jpg"


def test_atomic_write_leaves_no_part_file(tmp_path):
    dest = tmp_path / "x" / "full.jpg"
    n = paths.atomic_write(dest, lambda fh: fh.write(b"hello"))
    assert n == 5
    assert dest.read_bytes() == b"hello"
    assert list(tmp_path.rglob("*.part")) == []


def test_atomic_write_removes_part_on_failure(tmp_path):
    dest = tmp_path / "x" / "full.jpg"

    def boom(fh):
        fh.write(b"partial")
        raise RuntimeError("network died")

    with pytest.raises(RuntimeError):
        paths.atomic_write(dest, boom)
    assert not dest.exists()
    assert list(tmp_path.rglob("*.part")) == []


def test_unique_dest_suffixes_on_collision(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    assert paths.unique_dest(tmp_path, "a.jpg").name == "a-1.jpg"
    (tmp_path / "a-1.jpg").write_bytes(b"1")
    assert paths.unique_dest(tmp_path, "a.jpg").name == "a-2.jpg"


def test_atomic_copy(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"abc")
    dest = tmp_path / "out" / "dst.jpg"
    paths.atomic_copy(src, dest)
    assert dest.read_bytes() == b"abc"
    assert list((tmp_path / "out").glob("*.part")) == []
