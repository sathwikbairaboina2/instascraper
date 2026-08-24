"""The trending feed, over the http surface.

Rows are inserted directly rather than driven through the fake adapter:
these tests are about the window and the ranking, and hand-written rows say
exactly what date and engagement each post has.
"""
from datetime import datetime, timedelta, timezone


def _insert(conn, shortcode, caption, hours_ago, likes=0, comments=0, views=None):
    taken = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    conn.execute(
        "INSERT INTO profiles (username, created_at) VALUES ('nike', ?)"
        " ON CONFLICT(username) DO NOTHING",
        (taken,),
    )
    conn.execute(
        "INSERT INTO media_items"
        " (shortcode, username, kind, taken_at, caption, is_video, child_count,"
        "  like_count, comments_count, view_count, ig_url, discovered_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            shortcode, "nike", "image", taken, caption, 0, 1,
            likes, comments, views,
            f"https://instagram.com/p/{shortcode}/", taken,
        ),
    )


def test_trending_ranks_tags_inside_the_window(client, conn):
    _insert(conn, "a", "#nike #run", hours_ago=2, likes=100, comments=5)
    _insert(conn, "b", "#run", hours_ago=3, likes=10)

    body = client.get("/api/hashtags/trending?window=day").json()

    assert body["window"] == "day"
    assert [i["tag"] for i in body["items"]] == ["run", "nike"]
    assert body["items"][0]["score"] == 115
    assert body["items"][0]["post_count"] == 2


def test_day_window_excludes_a_post_from_last_week(client, conn):
    _insert(conn, "old", "#vintage", hours_ago=48, likes=999)
    _insert(conn, "new", "#fresh", hours_ago=1, likes=1)

    day = client.get("/api/hashtags/trending?window=day").json()
    week = client.get("/api/hashtags/trending?window=week").json()

    assert [i["tag"] for i in day["items"]] == ["fresh"]
    assert [i["tag"] for i in week["items"]] == ["vintage", "fresh"]


def test_a_post_just_inside_the_cutoff_is_counted(client, conn):
    _insert(conn, "edge-in", "#edge", hours_ago=23.9, likes=1)
    body = client.get("/api/hashtags/trending?window=day").json()
    assert [i["tag"] for i in body["items"]] == ["edge"]


def test_a_post_just_outside_the_cutoff_is_not(client, conn):
    _insert(conn, "edge-out", "#edge", hours_ago=24.1, likes=1)
    body = client.get("/api/hashtags/trending?window=day").json()
    assert body["items"] == []
    assert body["total"] == 0


def test_views_count_towards_the_score(client, conn):
    _insert(conn, "reel", "#reel", hours_ago=1, likes=1, comments=1, views=1000)
    body = client.get("/api/hashtags/trending?window=day").json()
    assert body["items"][0]["score"] == 1002
    assert body["items"][0]["view_count"] == 1000


def test_pages_do_not_overlap_or_skip(client, conn):
    for i in range(10):
        _insert(conn, f"p{i}", f"#tag{i:02d}", hours_ago=1, likes=100 - i)

    first = client.get("/api/hashtags/trending?window=day&limit=4&offset=0").json()
    second = client.get("/api/hashtags/trending?window=day&limit=4&offset=4").json()
    third = client.get("/api/hashtags/trending?window=day&limit=4&offset=8").json()

    assert first["total"] == 10
    assert [len(p["items"]) for p in (first, second, third)] == [4, 4, 2]
    seen = [i["tag"] for p in (first, second, third) for i in p["items"]]
    assert len(set(seen)) == 10, "pages must not repeat a tag"


def test_since_is_reported_so_the_ui_can_say_what_it_covered(client, conn):
    body = client.get("/api/hashtags/trending?window=week").json()
    since = datetime.fromisoformat(body["since"])
    delta = datetime.now(timezone.utc) - since
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)


def test_an_unknown_window_is_a_400(client):
    res = client.get("/api/hashtags/trending?window=month")
    assert res.status_code == 400
    assert "month" in str(res.json()["detail"])


def test_an_empty_window_is_an_empty_list_not_an_error(client):
    body = client.get("/api/hashtags/trending?window=day").json()
    assert body == {"window": "day", "since": body["since"], "total": 0, "items": []}
