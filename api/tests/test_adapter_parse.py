import json
from pathlib import Path

from app.ig import adapter
from app.ig import types as t

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_image_post():
    post = adapter.post_to_igpost(load("post_image.json"), "CxImage01")
    assert post.kind == "image"
    assert post.is_video is False
    assert post.child_count == 1
    assert post.caption == "a caption"
    assert post.thumb_url.endswith("thumb.jpg")
    assert post.ig_url == "https://www.instagram.com/p/CxImage01/"
    assert post.taken_at_iso.startswith("2026-01-01T")


def test_parse_reel_is_kind_reel_not_video():
    post = adapter.post_to_igpost(load("post_video.json"), "CxVideo01")
    assert post.kind == "reel"
    assert post.is_video is True
    assert post.caption == ""


def test_parse_carousel_counts_children():
    post = adapter.post_to_igpost(load("post_carousel.json"), "CxCarousel1")
    assert post.kind == "carousel"
    assert post.child_count == 3


def test_classify_maps_every_instaloader_failure():
    import instaloader.exceptions as e

    assert isinstance(adapter.classify(e.ProfileNotExistsException("x")), t.IgNotFound)
    assert isinstance(adapter.classify(e.PrivateProfileNotFollowedException("x")), t.IgPrivate)
    assert isinstance(adapter.classify(e.TooManyRequestsException("x")), t.IgRateLimited)
    assert isinstance(adapter.classify(e.LoginRequiredException("x")), t.IgChallenge)
    assert isinstance(adapter.classify(e.ConnectionException("x")), t.IgTransient)
    assert isinstance(adapter.classify(RuntimeError("surprise")), t.IgTransient)


def test_classify_reads_checkpoint_from_message():
    import instaloader.exceptions as e

    err = adapter.classify(e.ConnectionException("checkpoint_required"))
    assert isinstance(err, t.IgChallenge)


def test_classify_maps_query_status_exceptions():
    import instaloader.exceptions as e

    assert isinstance(adapter.classify(e.QueryReturnedNotFoundException("x")), t.IgNotFound)
    assert isinstance(adapter.classify(e.QueryReturnedForbiddenException("x")), t.IgChallenge)


def test_make_adapter_honours_the_fake_flag(settings):
    from app.ig.fake import FakeAdapter

    assert isinstance(adapter.make_adapter(settings), FakeAdapter)


def test_rate_controller_enforces_min_interval():
    from app.ig.rate import PacedRateController

    slept = []
    rc = PacedRateController(context=None, min_interval=2.5, sleep=slept.append)
    rc.sleep(0.1)
    assert slept == [2.5]


def test_rate_controller_respects_a_longer_library_sleep():
    from app.ig.rate import PacedRateController

    slept = []
    rc = PacedRateController(context=None, min_interval=2.5, sleep=slept.append)
    rc.sleep(60.0)
    assert slept == [60.0]
