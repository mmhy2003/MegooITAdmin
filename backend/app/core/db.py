from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_options() -> dict[str, Any]:
    if get_settings().db_null_pool:
        return {"poolclass": NullPool}
    return {"pool_pre_ping": True}


engine = create_async_engine(get_settings().database_url, **_engine_options())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request: committed after the handler, rolled back if it raises."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def flush_unique(session: AsyncSession, constraint: str, detail: str) -> None:
    """Flushes. A clash on the unique `constraint`, from a request that won the race past a check, answers 409."""
    try:
        await session.flush()
    except IntegrityError as e:
        if f'"{constraint}"' not in str(e.orig):
            raise
        raise HTTPException(409, detail) from e


# scope="function": the commit and the audit guard run before the response is sent, so a failed commit
# answers 500. The guard depends on this same alias, so FastAPI's dependency cache gives it the handler's session.
DbSession = Annotated[AsyncSession, Depends(get_session, scope="function")]
