from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"ssl": False},
    # Воркеры живут сутками, и соединение из пула к моменту следующего запроса
    # может быть уже мёртвым (закрыл Postgres, выбросил NAT). pre_ping проверяет
    # его перед выдачей и молча переподключается — иначе первый запрос после
    # долгого простоя падает, а выглядит это как «работало, пока не постояло ночь».
    pool_pre_ping=True,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
