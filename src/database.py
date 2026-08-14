import os
import uuid

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    event,
    text,
    Column,
    String,
    DateTime,
    Boolean,
    Integer,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY as PG_ARRAY
from sqlalchemy.types import TypeDecorator, CHAR, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    db_url = "sqlite:///chat_history.db"
elif db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

IS_SQLITE = db_url.startswith("sqlite")

connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class GUID(TypeDecorator):
    """UUID on Postgres, CHAR(36) string elsewhere."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return str(value)


class StringArray(TypeDecorator):
    """TEXT[] on Postgres, JSON-encoded list elsewhere."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(String))
        return dialect.type_descriptor(JSON())


JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_uuid() -> str:
    return str(uuid.uuid4())

# Application identity (Google OAuth accounts, API keys)

class DBUser(Base):
    """
    Application user account.

    Authentication is Google OAuth only — there is no local password field.
    `id` is the Google OAuth "sub" (subject) claim, used as the stable
    external identifier for the account.
    """
    __tablename__ = "app_users"

    id = Column(String(255), primary_key=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    username = Column(String(255), nullable=True)
    api_key = Column(String(64), unique=True, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chat_profile = relationship("ChatUser", back_populates="app_user", uselist=False)

    def __repr__(self) -> str:
        return f"<DBUser id={self.id!r} email={self.email!r}>"


class ChatUser(Base):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=new_uuid)
    identifier = Column(String(320), nullable=False, unique=True)  # == app_users.email
    app_user_id = Column(
        String(255), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    metadata_ = Column("metadata", JSONType, nullable=False, default=dict)
    createdAt = Column(String)

    app_user = relationship("DBUser", back_populates="chat_profile")
    threads = relationship("Thread", back_populates="user", cascade="all, delete-orphan")


class Thread(Base):
    __tablename__ = "threads"

    id = Column(GUID(), primary_key=True, default=new_uuid)
    createdAt = Column(String)
    name = Column(String)
    userId = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    userIdentifier = Column(String)
    tags = Column(StringArray())
    metadata_ = Column("metadata", JSONType)

    user = relationship("ChatUser", back_populates="threads")
    steps = relationship("Step", back_populates="thread", cascade="all, delete-orphan")
    elements = relationship("Element", back_populates="thread", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="thread", cascade="all, delete-orphan")


class Step(Base):
    __tablename__ = "steps"

    id = Column(GUID(), primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    threadId = Column(GUID(), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False, index=True)
    parentId = Column(GUID(), index=True, nullable=True)
    streaming = Column(Boolean, nullable=False, default=False)
    waitForAnswer = Column(Boolean)
    isError = Column(Boolean)
    metadata_ = Column("metadata", JSONType)
    tags = Column(StringArray())
    input = Column(String)
    output = Column(String)
    createdAt = Column(String)
    command = Column(String)
    start = Column(String)
    end = Column(String)
    generation = Column(JSONType)
    showInput = Column(String)
    language = Column(String)
    indent = Column(Integer)
    defaultOpen = Column(Boolean)
    modes = Column(JSONType)

    thread = relationship("Thread", back_populates="steps")


class Element(Base):
    __tablename__ = "elements"

    id = Column(GUID(), primary_key=True, default=new_uuid)
    threadId = Column(GUID(), ForeignKey("threads.id", ondelete="CASCADE"), nullable=True, index=True)
    type = Column(String)
    url = Column(String)
    chainlitKey = Column(String)
    name = Column(String, nullable=False)
    display = Column(String)
    objectKey = Column(String)
    size = Column(String)
    page = Column(Integer)
    language = Column(String)
    forId = Column(GUID(), index=True, nullable=True)
    mime = Column(String)
    props = Column(JSONType)
    autoPlay = Column(Boolean)
    playerConfig = Column(String)

    thread = relationship("Thread", back_populates="elements")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(GUID(), primary_key=True, default=new_uuid)
    forId = Column(GUID(), index=True, nullable=False)
    threadId = Column(GUID(), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Integer, nullable=False)
    comment = Column(String)

    thread = relationship("Thread", back_populates="feedbacks")

# Helpers

def get_async_db_url() -> str:
    """Return the async SQLAlchemy connection string (asyncpg / aiosqlite)."""
    raw_url = os.getenv("DATABASE_URL")
    if not raw_url:
        return "sqlite+aiosqlite:///chat_history.db"
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("sqlite:///"):
        return raw_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return raw_url

_LANGGRAPH_TABLES = [
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "checkpoints",
]


def enable_row_level_security(tables: list[str] | None = None) -> None:
    """
    Lock the given tables' PostgREST/Supabase API access shut. Defaults to
    every table in our ORM metadata. Safe to call repeatedly (idempotent)
    and a no-op on SQLite, which has no such concept. Uses IF EXISTS so it
    tolerates being called before a table has been created yet. No policies
    are added on purpose — this only affects access through Supabase's
    REST/client API; the app's direct psycopg/SQLAlchemy connection uses
    the DB owner role and is unaffected either way.
    """
    if IS_SQLITE:
        return
    if tables is None:
        tables = list(Base.metadata.tables.keys())
    with engine.connect() as conn:
        for table in tables:
            conn.execute(text(f'alter table if exists "{table}" enable row level security'))
        conn.commit()


def enable_langgraph_row_level_security() -> None:
    """
    Lock RLS on LangGraph's checkpoint tables. These are created by
    PostgresSaver.setup() in app.py, not by this module, so call this
    only after that setup() call has run.
    """
    enable_row_level_security(_LANGGRAPH_TABLES)


def init_db() -> None:
    """Create every table (app + Chainlit) from the ORM metadata, non-destructively."""
    Base.metadata.create_all(bind=engine)
    enable_row_level_security()

_SUPABASE_ROLES = ["postgres", "anon", "authenticated", "service_role"]


def reset_db() -> None:
    """
    DESTRUCTIVE: wipe every table in this database's `public` schema —
    including any stray/leftover tables the ORM doesn't know about (old
    experiments, manual test tables, previous LangGraph runs, etc.) — and
    recreate the app/Chainlit schema from scratch.

    On Postgres/Supabase this drops and recreates the whole `public` schema
    rather than dropping tables one by one, specifically so it also catches
    anything not currently tracked in Base.metadata or _LANGGRAPH_TABLES.
    Supabase's own schemas (auth, storage, realtime, extensions, ...) are
    never touched — only `public`, which is the only schema this app writes
    to. The standard Supabase roles are re-granted access afterward so the
    Supabase API keeps working.

    On SQLite (local dev fallback) there's no schema concept to wipe, so
    this falls back to dropping just the tables the ORM knows about.

    LangGraph's checkpoint tables are recreated automatically the next time
    the app starts and PostgresSaver.setup() runs; their RLS is (re-)enabled
    there too. Meant to be run once, deliberately — not on every startup.
    Run with: `python database.py reset`
    """
    if IS_SQLITE:
        Base.metadata.drop_all(bind=engine)
        init_db()
        print("[reset_db] Dropped and recreated all known tables in the "
              "local SQLite database.")
        return

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text('GRANT ALL ON SCHEMA public TO "postgres"'))
        for role in _SUPABASE_ROLES:
            conn.execute(text(f'GRANT USAGE, CREATE ON SCHEMA public TO "{role}"'))
        conn.commit()
    print("[reset_db] Dropped and recreated the entire 'public' schema "
          "(Supabase's own schemas were left untouched).")

    init_db()
    print("[reset_db] Recreated app + Chainlit tables and enabled row level "
          "security. Start the app once to let LangGraph recreate its "
          "checkpoint tables (and re-enable their RLS).")


def link_chat_user(email: str) -> None:
    """
    Best-effort sync: Chainlit creates its own `users` row lazily (the first
    time a chat session starts for that identifier), so it can't be linked
    to `app_users` at OAuth-callback time. Call this once a chat session is
    underway (e.g. in on_chat_start) to backfill `users.app_user_id`.
    Safe to call repeatedly / when either side doesn't exist yet.
    """
    with SessionLocal() as db:
        chat_user = db.query(ChatUser).filter(ChatUser.identifier == email).first()
        app_user = db.query(DBUser).filter(DBUser.email == email).first()
        if chat_user and app_user and chat_user.app_user_id != app_user.id:
            chat_user.app_user_id = app_user.id
            db.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        target = "the local SQLite file" if IS_SQLITE else f"the 'public' schema of {db_url.split('@')[-1]}"
        confirm = input(
            f"This will PERMANENTLY DELETE every table in {target} and "
            "recreate the app/Chainlit schema empty. Type 'yes' to continue: "
        )
        if confirm.strip().lower() == "yes":
            reset_db()
        else:
            print("Aborted.")
    else:
        print("Usage: python database.py reset")