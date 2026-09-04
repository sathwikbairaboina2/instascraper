import pytest

from app.ig import types as t
from app.ig.embed import EmbedLookup

# Trimmed to the two places the owner's handle actually appears in a real
# embed page: the "View profile" link and the app deep link beside it.
HTML = (
    '<div class="HeaderCta"><a class="ViewProfileButton" '
    'href="https://www.instagram.com/interviewgig_11/?utm_source=ig_embed&amp;ig_rid=Af5" '
    'data-ios-link="user?username=interviewgig_11&amp;utm_source=ig_embed" '
    'target="_blank">View profile</a></div>'
    '<div class="Content EmbedFrame"><a class="EmbeddedMedia" '
    'href="https://www.instagram.com/p/DcBiXJxTeBb/?utm_source=ig_embed"></a></div>'
)


class Fetcher:
    def __init__(self, status=200, body=HTML):
        self.status, self.body = status, body
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        return self.status, self.body


def test_the_owner_is_read_off_the_embed_page(settings):
    lookup = EmbedLookup(settings, fetcher=Fetcher(), spend=lambda: None)

    assert (
        lookup.owner("https://www.instagram.com/p/DcBiXJxTeBb/?igsi=dzRp")
        == "interviewgig_11"
    )


def test_it_asks_for_the_embed_page_not_the_post(settings):
    """The post page needs a logged-in session; the embed page does not."""
    fetcher = Fetcher()
    EmbedLookup(settings, fetcher=fetcher, spend=lambda: None).owner(
        "https://www.instagram.com/p/DcBiXJxTeBb/?igsi=dzRp"
    )

    assert fetcher.calls[0][0] == (
        "https://www.instagram.com/p/DcBiXJxTeBb/embed/captioned/"
    )


def test_the_request_is_spent_before_it_is_sent(settings):
    """One request to instagram.com, counted like every other one."""
    order: list[str] = []
    fetcher = Fetcher()

    def recording(url, timeout):
        order.append("fetch")
        return fetcher(url, timeout)

    EmbedLookup(settings, fetcher=recording, spend=lambda: order.append("spend")).owner(
        "https://www.instagram.com/p/DcBiXJxTeBb/"
    )

    assert order == ["spend", "fetch"]


def test_a_page_without_an_owner_is_not_found(settings):
    """Deleted and private posts render an embed page with no handle on it."""
    lookup = EmbedLookup(settings, fetcher=Fetcher(body="<html>Sorry"), spend=lambda: None)

    with pytest.raises(t.IgNotFound):
        lookup.owner("https://www.instagram.com/p/DcBiXJxTeBb/")


def test_a_failed_request_is_transient(settings):
    lookup = EmbedLookup(settings, fetcher=Fetcher(status=503, body=""), spend=lambda: None)

    with pytest.raises(t.IgTransient):
        lookup.owner("https://www.instagram.com/p/DcBiXJxTeBb/")


def test_a_url_that_is_not_a_post_is_not_found(settings):
    lookup = EmbedLookup(settings, fetcher=Fetcher(), spend=lambda: None)

    with pytest.raises(t.IgNotFound):
        lookup.owner("https://example.com/nope")
