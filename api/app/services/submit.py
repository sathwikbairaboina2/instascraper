"""Hands a prepared recreate payload to instacreator's queue.

The envelope is instacreator's ingest contract (its `Envelope` schema), keyed
on `source_ref` so a redelivered message cannot become a second job. Only the
fields that contract names are sent: our internals stay ours.
"""

import json
from typing import Callable


def envelope_from_payload(payload: dict) -> dict:
    return {
        "source": "instascraper",
        "source_ref": payload["shortcode"],
        "username": payload["username"],
        "ig_url": payload["ig_url"],
        "caption": payload["caption"] or "",
        "kind": payload["kind"],
        "taken_at": payload["taken_at"],
        "slides": payload["slides"],
    }


class Publisher:
    def __init__(
        self,
        endpoint: str,
        queue: str,
        client_factory: Callable | None = None,
    ):
        self._endpoint = endpoint
        self._queue = queue
        self._client_factory = client_factory or self._boto_client
        self._client = None
        self._queue_url: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self._endpoint and self._queue)

    def _boto_client(self):
        import boto3

        # ElasticMQ ignores credentials but boto3 insists on having some;
        # the region is equally decorative for a local endpoint.
        return boto3.client(
            "sqs",
            endpoint_url=self._endpoint,
            region_name="elasticmq",
            aws_access_key_id="x",
            aws_secret_access_key="x",
        )

    def publish(self, envelope: dict) -> None:
        if not self.configured:
            raise RuntimeError("SQS_ENDPOINT is not configured")
        if self._client is None:
            self._client = self._client_factory()
        if self._queue_url is None:
            # Idempotent: SQS returns the existing queue's url.
            self._queue_url = self._client.create_queue(QueueName=self._queue)["QueueUrl"]
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps(envelope)
        )
