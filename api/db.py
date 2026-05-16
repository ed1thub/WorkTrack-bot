import ssl as _ssl
from pathlib import Path

import asyncpg

import config

_pool: asyncpg.Pool | None = None
_SCHEMA = Path(__file__).parent / "schema.sql"


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        url = config.DATABASE_URL
        kwargs: dict = {"min_size": 1, "max_size": 5}
        # Neon requires SSL; strip the sslmode query param and pass ssl context explicitly.
        if "sslmode=require" in url or "neon.tech" in url:
            kwargs["ssl"] = _ssl.create_default_context()
            url = url.split("?")[0]
        _pool = await asyncpg.create_pool(url, **kwargs)
    return _pool


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA.read_text())


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
