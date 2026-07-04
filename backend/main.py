from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.models import Base, Collection
from backend.routers import collections, products


async def _seed_collections() -> None:
    initial = [("Cardinal", "cardinal"), ("Gula", "gula"), ("Acedia", "acedia")]
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Collection))
        if result.scalars().first() is None:
            for name, slug in initial:
                session.add(Collection(name=name, slug=slug))
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_collections()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.include_router(products.router)
app.include_router(collections.router)
