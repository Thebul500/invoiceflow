"""invoiceflow — FastAPI application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .database import init_db
from .engine.ingestor import process_queue, start_watcher
from .routes.health import router as health_router
from .routes.invoices import router as invoices_router
from .routes.purchase_orders import router as po_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: create tables on startup, start watch folder ingestor."""
    await init_db()

    observer, handler = start_watcher(settings.watch_dir)
    handler.set_loop(asyncio.get_running_loop())
    task = asyncio.create_task(process_queue(handler))
    logger.info("Watch folder ingestor active: %s", settings.watch_dir)

    yield

    task.cancel()
    observer.stop()
    observer.join()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="invoiceflow",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(invoices_router)
    app.include_router(po_router)
    return app


app = create_app()
