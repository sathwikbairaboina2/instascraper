from app.services.urls import parse_shortcode


def test_parses_post_url():
    assert parse_shortcode("https://www.instagram.com/p/C8xPqR9abcd/") == "C8xPqR9abcd"


def test_parses_reel_url():
    assert parse_shortcode("https://www.instagram.com/reel/C8yQvW2xyz/") == "C8yQvW2xyz"


def test_parses_tv_url():
    assert parse_shortcode("https://www.instagram.com/tv/C8zAbCd123/") == "C8zAbCd123"


def test_parses_without_scheme_or_www():
    assert parse_shortcode("instagram.com/p/C8xPqR9abcd") == "C8xPqR9abcd"


def test_parses_with_query_string():
    assert (
        parse_shortcode("https://www.instagram.com/reel/C8yQvW2xyz/?igsh=abc123")
        == "C8yQvW2xyz"
    )


def test_parses_profile_scoped_post_url():
    # Share links sometimes carry the owner: instagram.com/<user>/p/<code>/
    assert parse_shortcode("https://www.instagram.com/natgeo/p/C8xPqR9abcd/") == "C8xPqR9abcd"


def test_rejects_profile_url():
    assert parse_shortcode("https://www.instagram.com/natgeo/") is None


def test_rejects_other_hosts():
    assert parse_shortcode("https://example.com/p/C8xPqR9abcd/") is None


def test_rejects_garbage():
    assert parse_shortcode("not a url at all") is None


def test_rejects_empty():
    assert parse_shortcode("") is None
    assert parse_shortcode("   ") is None


def test_rejects_several_links_run_together():
    """Taking the first of a comma-joined list would silently drop the rest."""
    joined = (
        "https://www.instagram.com/p/C8xPqR9abcd/?igsh=abc,"
        "https://www.instagram.com/p/C8yQvW2xyz/?igsh=def"
    )
    assert parse_shortcode(joined) is None
