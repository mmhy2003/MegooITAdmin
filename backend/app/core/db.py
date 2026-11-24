from collections.abc import AsyncIterator, Mapping
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


async def flush_refusing(session: AsyncSession, refusals: Mapping[str, tuple[int, str]]) -> None:
    """Flushes. A violation of one of the named constraints, from a request that won the race past a check,
    answers its (status, detail)."""
    try:
        await session.flush()
    except IntegrityError as e:
        for constraint, (status, detail) in refusals.items():
            if f'"{constraint}"' in str(e.orig):
                raise HTTPException(status, detail) from e
        raise


async def flush_unique(session: AsyncSession, constraint: str, detail: str) -> None:
    """Flushes. A clash on the unique `constraint`, from a request that won the race past a check, answers 409."""
    await flush_refusing(session, {constraint: (409, detail)})


# scope="function": the commit and the audit guard run before the response is sent, so a failed commit
# answers 500. The guard depends on this same alias, so FastAPI's dependency cache gives it the handler's session.
DbSession = Annotated[AsyncSession, Depends(get_session, scope="function")]
