"""Record real Business Discovery responses as test fixtures.

Run once, with a live token, to refresh tests/fixtures/graph/. Redacts the
token, our own node id, and fbtrace_id before writing, because these files
are committed.

    python scripts/capture_graph_fixtures.py nike
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings  # noqa: E402
from app.ig.graph import GraphAdapter, _MEDIA_FIELDS, _PROFILE_FIELDS  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "graph"


def redact(payload: dict, settings) -> dict:
    text = json.dumps(payload)
    if settings.graph_token:
        text = text.replace(settings.graph_token, "REDACTED")
    if settings.graph_user_id:
        text = text.replace(settings.graph_user_id, "SELF")
    scrubbed = json.loads(text)
    scrubbed.pop("fbtrace_id", None)
    return scrubbed


def main(target: str) -> int:
    settings = load_settings()
    if not settings.graph_token:
        print("IG_GRAPH_TOKEN must be set to capture fixtures.")
        return 1

    adapter = GraphAdapter(settings)
    OUT.mkdir(parents=True, exist_ok=True)

    profile = adapter._get(f"business_discovery.username({target}){{{_PROFILE_FIELDS}}}")
    (OUT / "profile.json").write_text(json.dumps(redact(profile, settings), indent=2))

    media = adapter._get(
        f"business_discovery.username({target}){{media.limit(6){{{_MEDIA_FIELDS}}}}}"
    )
    (OUT / "media_page.json").write_text(json.dumps(redact(media, settings), indent=2))

    print(f"Wrote fixtures for {target} to {OUT}")
    print("Review both files for anything personal before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "nike"))
