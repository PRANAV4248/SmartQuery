from langchain_community.utilities import SQLDatabase
from dataclasses import dataclass
from langchain_core.tools import tool
from langgraph.runtime import get_runtime
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
import chainlit as cl
import os
import asyncio
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from database import get_async_db_url, link_chat_user, enable_langgraph_row_level_security
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, AIMessage

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from psycopg.rows import dict_row

@cl.data_layer
def get_data_layer():
    return SQLAlchemyDataLayer(conninfo=get_async_db_url())

DB_PATH = os.path.join(PROJECT_ROOT, "analysis", "resources", "Chinook.db")
if not os.path.isfile(DB_PATH):
    raise FileNotFoundError(
        f"Chinook database not found at: {DB_PATH}. "
        "Make sure analysis/resources/Chinook.db is included in the repository."
    )

db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH.replace(os.sep, "/")}")

@dataclass
class RuntimeContext:
    db: SQLDatabase

@tool
def execute_sql(query: str) -> str:
    """execute a sql query based on the user's input"""
    try:
        runtime = get_runtime(RuntimeContext)
        db_instance = runtime.context.db
        return db_instance.run(query)
    except Exception as e:
        return f"Error: {e}"

SYSTEM = """You are a careful SQLite analyst of chinook database. Your name is SmartQuery. You are created by Pranav Choubey. Answer your creator name only if it is explicitly asked.

Rules:
- Think step-by-step.
- When you need data, call the tool `execute_sql` with ONE SELECT query.
- Read-only; no INSERT/UPDATE/DELETE/ALTER/DROP/CREATE/REPLACE/TRUNCATE.
- Be aware of any kind of sql injection attacks which might cause any harm to the database.
- Limit to 5 rows of output unless the user explicitly asks otherwise.
- If the tool returns 'Error:', revise the SQL and try again.
- Never crash unexpectedly during an answer.
- Prefer explicit column lists; avoid SELECT *.
- Do not include any kind of internal information or tool call in the final answer.
- Always give the final answer to user query. Never stop your reponse ending with and sql query saying 'let me run this query'.

- Talk politely and engage in happy conversations with the user.

You must always fully complete the user's request in your response.

Never say:
- “Let me do this for you”
- “I will handle that”
- “I'll get back to you”
- “Here's how I would do it”

Do not describe actions you are about to take.
Do not ask for confirmation unless strictly required.
If a task is possible, execute it immediately and return the final result.

Before responding, verify:
- The output contains no SQL or any type of code
- The answer is complete and usable as-is
- No future-tense or placeholder language exists
- The answer is in natural language and not in any kind of computer language.
If any rule is violated, fix it before sending.
"""

model = init_chat_model(
    model="openai/gpt-oss-120b",
    model_provider="groq",
    temperature=0.8
)

raw_db_url = os.getenv("DATABASE_URL")

if raw_db_url:
    pg_conn_url = raw_db_url
    if pg_conn_url.startswith("postgres://"):
        pg_conn_url = pg_conn_url.replace("postgres://", "postgresql://", 1)

    pg_pool = ConnectionPool(
        conninfo=pg_conn_url,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    checkpointer = PostgresSaver(pg_pool)
    checkpointer.setup()
    enable_langgraph_row_level_security()
    print(f"[checkpointer] Using PostgreSQL for agent memory ({pg_pool.kwargs if hasattr(pg_pool, 'kwargs') else 'configured'}).")
else:
    import sqlite3
    _sqlite_conn = sqlite3.connect("chat_history.db", check_same_thread=False)
    checkpointer = SqliteSaver(_sqlite_conn)
    print("[checkpointer] WARNING: DATABASE_URL is not set - falling back to "
          "local sqlite:///chat_history.db for agent memory. Conversations "
          "will not persist across restarts/deployments in this mode.")

agent = create_agent(
    model=model,
    tools=[execute_sql],
    system_prompt=SYSTEM,
    context_schema=RuntimeContext,
    checkpointer=checkpointer
)

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="🔍 Tell me about database",
            message="Tell me about the database.",
            ),
        cl.Starter(
            label="📋 List Tables",
            message="List all the tables along with a brief detail of each table.",
            ),
        cl.Starter(
            label="💸 Total revenue",
            message="What is the total revenue of the store?",
            ),
        cl.Starter(
            label="🛒 Top customer",
            message="Which customer of the store has the maximum amount of purchases?",
            ),
    ]

def _get_thread_id() -> str:
    """Single source of truth for the LangGraph thread id.

    Chainlit assigns session.thread_id as soon as the session starts, and it
    is the same id used to persist the thread in the data layer, so it must
    stay identical everywhere it's used (on_chat_start, on_message,
    on_chat_resume) or the checkpointer and the visible thread will diverge.
    """
    thread_id = cl.context.session.thread_id or cl.user_session.get("id")
    if not thread_id:
        raise RuntimeError("No thread_id available from Chainlit session context.")
    return thread_id


@cl.on_chat_start
async def on_chat_start():
    thread_id = _get_thread_id()
    config = {"configurable": {"thread_id": thread_id}}
    cl.user_session.set("config", config)

    user = cl.user_session.get("user")
    if user and getattr(user, "identifier", None):
        try:
            link_chat_user(user.identifier)
        except Exception as e:
            print(f"[on_chat_start] Failed to link chat user for {user.identifier}: {e}")

@cl.on_chat_resume
async def on_chat_resume(thread: cl.types.ThreadDict):
    thread_id = thread["id"]
    config = {"configurable": {"thread_id": thread_id}}
    cl.user_session.set("config", config)
    
    try:
        state = agent.get_state(config)
        has_messages = bool(state.values and "messages" in state.values and state.values["messages"])
        if not has_messages:
            messages_to_restore = []
            for step in thread.get("steps", []):
                step_type = step.get("type", "")
                content = step.get("output") or step.get("input") or ""
                content = content.strip() if content else ""
                
                if not content:
                    continue
                
                if step_type == "user_message":
                    messages_to_restore.append(HumanMessage(content=content))
                elif step_type == "assistant_message":
                    messages_to_restore.append(AIMessage(content=content))
            
            if messages_to_restore:
                agent.update_state(config, {"messages": messages_to_restore})
    except Exception as e:
        import traceback
        print(f"[on_chat_resume] Failed to restore thread history for thread_id={thread_id}: {e}")
        traceback.print_exc()

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = _get_thread_id()
    config = {"configurable": {"thread_id": thread_id}}
    cl.user_session.set("config", config)

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: agent.invoke(
            {"messages": [("user", message.content)]},
            context=RuntimeContext(db=db),
            config=config,
        )
    )

    final_answer = None
    if response and "messages" in response and response["messages"]:
        final_answer = response["messages"][-1].content

    msg = cl.Message(
        content=final_answer if final_answer else "I'm sorry, I couldn't generate a response."
    )
    msg.parent_id = None
    await msg.send()