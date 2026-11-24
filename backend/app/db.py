import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


class _DBAPICursor(Protocol):
    def execute(self, sql: str) -> object: ...
    def close(self) -> None: ...


class _DBAPIConnection(Protocol):
    def cursor(self) -> _DBAPICursor: ...


class Database:
    """Async SQLModel/SQLite database manager with WAL mode and explicit disposal."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self._database_url = database_url
        self._is_memory = ":memory:" in database_url
        self._memory_lock = asyncio.Lock()

        if self._is_memory:
            self.engine: AsyncEngine = create_async_engine(
                database_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine = create_async_engine(database_url, echo=echo)

        if database_url.startswith("sqlite"):
            is_memory = self._is_memory

            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn: _DBAPIConnection, _record: object) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON;")
                if not is_memory:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA synchronous=NORMAL;")
                    cursor.execute("PRAGMA busy_timeout=5000;")
                cursor.close()

        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_models(self) -> None:
        """Register all SQLModel tables and create missing schema in SQLite."""
        import memory.models  # noqa: F401

        if not self._is_memory and self._database_url.startswith("sqlite"):
            db_path = self.engine.url.database
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            if self._database_url.startswith("sqlite"):
                await self._migrate_sqlite_columns(conn)

    async def _migrate_sqlite_columns(self, conn: AsyncConnection) -> None:
        """Idempotently add new columns missing from pre-existing SQLite tables."""
        result = await conn.exec_driver_sql("PRAGMA table_info('agents')")
        rows = result.fetchall()
        column_names = {
            str(row_values[1])
            for row in rows
            if len(row_values := list(row)) > 1
        }
        if rows and "mood" not in column_names:
            await conn.exec_driver_sql(
                "ALTER TABLE agents ADD COLUMN mood VARCHAR NOT NULL DEFAULT 'calm'"
            )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a managed async SQLModel session."""
        if self._is_memory:
            async with self._memory_lock:
                async with self._session_factory() as session:
                    yield session
            return

        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """Dispose the underlying async engine and close pooled connections."""
        await self.engine.dispose()
