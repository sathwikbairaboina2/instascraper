import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import runtime
from app.config import Settings, load_settings
from app.ig.factory import make_adapter
from app.routes import activity as activity_routes
from app.routes import downloads as download_routes
from app.routes import hashtags as hashtag_routes
from app.routes import health as health_routes
from app.routes import media as media_routes
from app.routes import profiles as profile_routes
from app.routes import recreate as recreate_routes
from app.routes import status as status_routes
from app.routes import urls as url_routes
from app.worker.breaker import Breaker
from app.worker.handlers import HANDLERS
from app.worker.pacer import Pacer
from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(message)s")
# httpx logs every request line at INFO, which for us means every media url
# including its signed `oh=`/`oe=` parameters. Those are credentials with an
# expiry, and they bury the one line per job this app actually emits.
logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(
    settings: Settings | None = None,
    adapter=None,
    start_worker: bool = True,
) -> FastAPI:
    base = settings or load_settings()
    # An injected adapter pins the runtime: the test suite supplies its own
    # fake and must keep the base paths it also opens directly.
    name = base.adapter if adapter is not None else runtime.read_selection(base)
    active = base if adapter is not None else runtime.settings_for(base, name)
    holder = runtime.RuntimeConfig(
        base, runtime.Runtime(name, active, adapter or make_adapter(active))
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = app.state.runtime.current
        result = runtime.prepare_data_root(current.settings)
        # json.dumps, not %s: a dict interpolated into a string emits Python
        # repr with single quotes, which is not parseable JSON.
        logging.info(json.dumps({"event": "sweep", **result}))

        if start_worker:
            worker = Worker(
                app.state.runtime,
                app.state.breaker,
                app.state.pacer,
                app.state.cdn_pacer,
                HANDLERS,
            )
            worker.start()
            app.state.worker = worker
        yield
        worker = getattr(app.state, "worker", None)
        if worker is not None:
            worker.shutdown()

    app = FastAPI(title="instascraper", lifespan=lifespan)
    app.state.runtime = holder
    app.state.breaker = Breaker()
    app.state.pacer = Pacer(min_interval=base.ig_min_interval)
    app.state.cdn_pacer = Pacer(min_interval=base.cdn_min_interval)
    app.state.worker = None

    from app.services.submit import Publisher

    app.state.publisher = Publisher(base.sqs_endpoint, base.sqs_queue)

    app.include_router(status_routes.router, prefix="/api")
    app.include_router(recreate_routes.router, prefix="/api")
    app.include_router(activity_routes.router, prefix="/api")
    app.include_router(profile_routes.router, prefix="/api")
    app.include_router(media_routes.router, prefix="/api")
    app.include_router(download_routes.router, prefix="/api")
    app.include_router(hashtag_routes.router, prefix="/api")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(url_routes.router, prefix="/api")
    return app


app = create_app()
