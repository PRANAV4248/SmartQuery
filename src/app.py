import asyncio
import os
import sys
import time
import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain.rate_limiters import InMemoryRateLimiter
from langchain.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain.agents.middleware import SummarizationMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DATABASE_URL, get_async_db_url, check_and_increment_daily_usage

@cl.data_layer
def get_data_layer():
    return SQLAlchemyDataLayer(conninfo=get_async_db_url())

chinook_db = SQLDatabase.from_uri("sqlite:///analysis/resources/Chinook.db")

@tool
def execute_sql(query: str) -> str:
    """Use this tool to execute a read-only SQL query on the Chinook database."""
    clean = query.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip().rstrip(";")
    if not clean.lower().startswith(("select", "with")) or ";" in clean:
        return "Error: Only single read-only SELECT queries are permitted."
    try:
        return chinook_db.run(clean)
    except Exception as e:
        return f"Error: {e}"

SYSTEM = """You are a careful SQLite analyst of chinook database. Your name is SmartQuery. You are created by Pranav Choubey. Answer your creator name only if it is explicitly asked.

Rules:
- Think step-by-step.
- When you need data, call the tool `execute_sql` with ONE SELECT query.
- Read-only; no INSERT/UPDATE/DELETE/ALTER/DROP/CREATE/REPLACE/TRUNCATE.
- Limit to 5 rows of output unless the user explicitly asks otherwise.
- If the tool returns 'Error:', revise the SQL and try again.
- Prefer explicit column lists; avoid SELECT *.
- Do not include internal tool calls or code blocks in the final answer.
- Always provide a polite, natural language response.
"""

# LLM Rate Limiter (0.5 req/sec = max 30 RPM to protect against Groq 429 errors)
rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.5,
    check_every_n_seconds=0.1,
    max_bucket_size=5,
)

model = init_chat_model(
    model="openai/gpt-oss-120b",
    model_provider="groq",
    temperature=0.2,
    rate_limiter=rate_limiter
)

summarization_model = init_chat_model(
    model="openai/gpt-oss-20b",
    model_provider="groq",
    temperature=0.2,
    rate_limiter=rate_limiter
)

agent = None
pool = None
init_lock = asyncio.Lock()

async def get_agent():
    global agent, pool
    if agent is not None:
        return agent
    async with init_lock:
        if agent is not None:
            return agent
        pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        agent = create_agent(
            model=model,
            tools=[execute_sql],
            system_prompt=SYSTEM,
            checkpointer=checkpointer,
            middleware=[
                SummarizationMiddleware(
                    model=summarization_model,
                    trigger=("tokens", 500),
                    keep=("messages", 1)
                )
            ],
        )
    return agent

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(label="🔍 Tell me about database", message="Tell me about the database."),
        cl.Starter(label="📋 List Tables", message="List all the tables along with a brief detail of each table."),
        cl.Starter(label="💸 Total revenue", message="What is the total revenue of the store."),
        cl.Starter(label="🛒 Top customer", message="Which customer has the maximum amount of purchases?"),
    ]

@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("config", {"configurable": {"thread_id": cl.context.session.thread_id}})

@cl.on_chat_resume
async def on_chat_resume(thread: cl.types.ThreadDict):
    cl.user_session.set("config", {"configurable": {"thread_id": thread["id"]}})

@cl.on_message
async def on_message(message: cl.Message):
    # Tier 1: Per-user UI message rate limit check (burst spam protection)
    now = time.time()
    history = [t for t in cl.user_session.get("msg_timestamps", []) if now - t < 60]

    if len(history) >= 6:
        await cl.Message(
            content="⏳ **Please slow down!** You've reached the message limit. Please wait a few seconds before asking another question."
        ).send()
        return

    # Check 20 questions/day limit per user in database
    user = cl.user_session.get("user")
    identifier = user.identifier if user else (cl.context.session.id or "anonymous")
    allowed, count = check_and_increment_daily_usage(identifier, limit=20)
    if not allowed:
        await cl.Message(
            content=f"🚫 **Daily Limit Reached**: You have used all {count}/20 questions for today. Your quota will reset tomorrow."
        ).send()
        return

    history.append(now)
    cl.user_session.set("msg_timestamps", history)

    config = cl.user_session.get("config")
    try:
        resolved_agent = await get_agent()
        response = await resolved_agent.ainvoke(
            {"messages": [("user", message.content)]},
            config=config,
        )
        answer = response["messages"][-1].content if response.get("messages") else "Sorry, I couldn't generate a response."
    except Exception as e:
        answer = f"Sorry, something went wrong while processing your request: {e}"
    await cl.Message(content=answer).send()