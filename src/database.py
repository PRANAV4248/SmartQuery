import os
import sys
from dotenv import load_dotenv
from psycopg import Connection

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import AuthUser

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_async_db_url() -> str:
    """Return an asyncpg connection string for Chainlit's data layer."""
    return DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

def init_db() -> None:
    """Create the users and daily usage tables if they do not already exist."""
    with Connection.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(320) UNIQUE NOT NULL,
                username VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT NOW());

            CREATE TABLE IF NOT EXISTS user_daily_usage (
                identifier VARCHAR(320) NOT NULL,
                usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
                query_count INT NOT NULL DEFAULT 0,
                PRIMARY KEY (identifier, usage_date));
        """)

def check_and_increment_daily_usage(identifier: str, limit: int = 20) -> tuple[bool, int]:
    """
    Check if the user has reached their daily limit (20 questions/day).
    Returns (True, updated_count) if allowed, or (False, current_count) if quota is exhausted.
    """
    with Connection.connect(DATABASE_URL, autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT query_count FROM user_daily_usage
            WHERE identifier = %s AND usage_date = CURRENT_DATE;
            """,
            (identifier,),
        ).fetchone()

        current_count = row[0] if row else 0
        if current_count >= limit:
            return False, current_count

        updated = conn.execute(
            """
            INSERT INTO user_daily_usage (identifier, usage_date, query_count)
            VALUES (%s, CURRENT_DATE, 1)
            ON CONFLICT (identifier, usage_date)
            DO UPDATE SET query_count = user_daily_usage.query_count + 1
            RETURNING query_count;
            """,
            (identifier,),
        ).fetchone()
        return True, updated[0]

def get_or_create_user(user_id: str, email: str, name: str | None) -> AuthUser:
    """Retrieve existing user or create a new user record atomically."""
    with Connection.connect(DATABASE_URL, autocommit=True) as conn:
        row = conn.execute(
            """
            INSERT INTO app_users (id, email, username)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET username = EXCLUDED.username
            RETURNING id, email, username;
            """,
            (user_id, email, name),
        ).fetchone()
        return AuthUser(id=row[0], email=row[1], name=row[2])