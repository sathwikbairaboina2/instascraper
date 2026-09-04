import json

import pytest

from app.services.submit import Publisher, envelope_from_payload

PAYLOAD = {
    "shortcode": "nike-0",
    "username": "nike",
    "ig_url": "https://instagram.com/p/nike-0/",
    "caption": "caption 0",
    "kind": "image",
    "taken_at": "2026-01-01T00:00:00+00:00",
    "prepared_at": "2026-08-27T00:00:00+00:00",
    "slides": [
        {"index": 0, "path": "nike/nike-0/full.jpg", "mime": "image/jpeg",
         "bytes": 10, "width": 240, "height": 240},
    ],
}


class FakeSqs:
    def __init__(self):
        self.created: list[str] = []
        self.sent: list[tuple[str, str]] = []

    def create_queue(self, QueueName):
        self.created.append(QueueName)
        return {"QueueUrl": f"http://sqs.test/queue/{QueueName}"}

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append((QueueUrl, MessageBody))
        return {"MessageId": "m1"}


def test_the_envelope_carries_what_instacreator_ingests():
    envelope = envelope_from_payload(PAYLOAD)

    assert envelope["source"] == "instascraper"
    assert envelope["source_ref"] == "nike-0"
    assert envelope["username"] == "nike"
    assert envelope["kind"] == "image"
    assert envelope["slides"] == PAYLOAD["slides"]
    # The receiver's schema does not know prepared_at; sending it anyway
    # couples the queue contract to our internals.
    assert "prepared_at" not in envelope


def test_publish_sends_the_envelope_as_json():
    sqs = FakeSqs()
    publisher = Publisher("http://sqs.test", "recreate-jobs", client_factory=lambda: sqs)

    publisher.publish(envelope_from_payload(PAYLOAD))

    assert sqs.created == ["recreate-jobs"]
    url, body = sqs.sent[0]
    assert url.endswith("/recreate-jobs")
    assert json.loads(body)["source_ref"] == "nike-0"


def test_the_queue_is_created_once_not_per_message():
    sqs = FakeSqs()
    publisher = Publisher("http://sqs.test", "recreate-jobs", client_factory=lambda: sqs)

    publisher.publish(envelope_from_payload(PAYLOAD))
    publisher.publish(envelope_from_payload(PAYLOAD))

    assert sqs.created == ["recreate-jobs"]
    assert len(sqs.sent) == 2


def test_unconfigured_publisher_says_so():
    publisher = Publisher("", "recreate-jobs")
    assert publisher.configured is False
    with pytest.raises(RuntimeError):
        publisher.publish({})
