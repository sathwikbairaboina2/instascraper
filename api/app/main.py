import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.config import Settings, load_settings
from app.ig.factory import make_adapter
from app.routes import activity as activity_routes
from app.routes import downloads as download_routes
from app.routes import health as health_routes
from app.routes import media as media_routes
from app.routes import profiles as profile_routes
from app.routes import status as status_routes
from app.worker import sweep
from app.worker.breaker import Breaker
from app.worker.handlers import HANDLERS
from app.worker.pacer import Pacer
from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(
    settings: Settings | None = None,
    adapter=None,
    start_worker: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    adapter = adapter or make_adapter(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.get_conn(settings)
        db.init_schema(conn)
        db.migrate(conn)
        for directory in (settings.media_dir, settings.out_dir):
            directory.mkdir(parents=True, exist_ok=True)
        result = sweep.sweep(conn, settings.media_dir)
        # json.dumps, not %s: a dict interpolated into a string emits Python
        # repr with single quotes, which is not parseable JSON.
        logging.info(json.dumps({"event": "sweep", **result}))

        if start_worker:
            worker = Worker(
                settings=settings,
                adapter=adapter,
                breaker=app.state.breaker,
                pacer=app.state.pacer,
                handlers=HANDLERS,
            )
            worker.start()
            app.state.worker = worker
        yield
        worker = getattr(app.state, "worker", None)
        if worker is not None:
            worker.shutdown()

    app = FastAPI(title="instascraper", lifespan=lifespan)
    app.state.settings = settings
    app.state.adapter = adapter
    app.state.breaker = Breaker()
    app.state.pacer = Pacer(min_interval=settings.ig_min_interval)
    app.state.worker = None

    app.include_router(status_routes.router, prefix="/api")
    app.include_router(activity_routes.router, prefix="/api")
    app.include_router(profile_routes.router, prefix="/api")
    app.include_router(media_routes.router, prefix="/api")
    app.include_router(download_routes.router, prefix="/api")
    app.include_router(health_routes.router, prefix="/api")
    return app


app = create_app()
