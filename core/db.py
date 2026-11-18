"""SQLAlchemy metadata and connection-scoped PostgreSQL coordination."""

import time
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Lock, RLock

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def now():
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Job(Base):
    __tablename__ = "request_jobs"
    __table_args__ = (
        Index(
            "uq_request_jobs_busy",
            "chat_id",
            "user_id",
            unique=True,
            postgresql_where=text("busy"),
            sqlite_where=text("busy = 1"),
        ),
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(String(36), unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    question: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    busy: Mapped[bool] = mapped_column(Boolean, default=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    active_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("doc_id", "version"), UniqueConstraint("doc_id", "checksum"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    status: Mapped[str] = mapped_column(String(16), default="indexing")
    chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Database:
    def __init__(self, url=None):
        options = (
            {}
            if url
            else {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
        )
        self.engine = create_engine(url or "sqlite://", pool_pre_ping=True, **options)
        session_class = Session
        if not url:
            # StaticPool shares one in-memory SQLite connection in mock/stub mode.
            # Serialize its sessions; PostgreSQL uses independent pooled connections.
            mutex = RLock()

            class MemorySession(Session):
                def __enter__(self):
                    mutex.acquire()
                    return super().__enter__()

                def __exit__(self, *args):
                    try:
                        return super().__exit__(*args)
                    finally:
                        mutex.release()

            session_class = MemorySession
        self.sessions = sessionmaker(self.engine, class_=session_class, expire_on_commit=False)
        self._locks = {key: Lock() for key in (71001, 71002, 71003)}
        if not url:  # isolated stub/test mode only; production uses Alembic
            Base.metadata.create_all(self.engine)

    @contextmanager
    def lock(self, key, blocking=True):
        if self.engine.dialect.name != "postgresql":
            acquired = self._locks[key].acquire(blocking=blocking)
            try:
                yield acquired
            finally:
                if acquired:
                    self._locks[key].release()
            return
        while True:
            connection = self.engine.connect()
            try:
                acquired = connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                )
                connection.commit()
            except BaseException:
                connection.close()
                raise
            if acquired:
                break
            connection.close()
            if not blocking:
                yield False
                return
            # Do not exhaust the connection pool with blocked advisory-lock waiters.
            time.sleep(0.05)
        try:
            yield True
        finally:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()
            finally:
                connection.close()
