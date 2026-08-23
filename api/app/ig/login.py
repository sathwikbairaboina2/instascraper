import sys

from app.config import Settings, load_settings
from app.ig import types as t
from app.ig.adapter import make_adapter


def main(settings: Settings | None = None, adapter_factory=make_adapter, out=print) -> int:
    settings = settings or load_settings()

    if not settings.ig_username or not settings.ig_password:
        out("IG_USERNAME and IG_PASSWORD must be set in .env before logging in.")
        return 1

    settings.session_dir.mkdir(parents=True, exist_ok=True)
    out(f"Logging in as {settings.ig_username}...")

    try:
        adapter_factory(settings).login()
    except t.IgError as exc:
        out(f"Login failed: {exc}")
        out("If this is a checkpoint, open Instagram in a browser, clear the")
        out("challenge for this account, then run this command again.")
        return 1

    out(f"Session saved to {settings.session_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
