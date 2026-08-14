# This is a test file to build and run the agent in python terminal

from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from dataclasses import dataclass
from langchain_core.tools import tool
from langgraph.runtime import get_runtime
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.middleware import SummarizationMiddleware

load_dotenv()

db = SQLDatabase.from_uri("sqlite:///../analysis/resources/Chinook.db")

@dataclass
class RuntimeContext:
    db: SQLDatabase

@tool
def execute_sql(query: str) -> str:
    """Execute a SQLite command and return results."""
    runtime = get_runtime(RuntimeContext)
    db = runtime.context.db
    try:
        return db.run(query)
    except Exception as e:
        return f"Error: {e}"

SYSTEM = f"""You are a careful SQLite analyst of chinook database. Your name is cooper. You are created by Pranav Choubey. Answer your creater name only if it is explicitly asked.

Rules:
- Think step-by-step.
- When you need data, call the tool `execute_sql` with ONE SELECT query.
- Read-only only; no INSERT/UPDATE/DELETE/ALTER/DROP/CREATE/REPLACE/TRUNCATE.
- Be aware of any kind of sql injection attacks which might cause any harm to the database.
- Limit to 5 rows of output unless the user explicitly asks otherwise.
- If the tool returns 'Error:', revise the SQL and try again.
- Prefer explicit column lists; avoid SELECT *.
- Do not include any kind of internal information or tool call in the final answer.
- Always give the final answer to user query. Never stop your reponse ending with and sql query saying 'let me run this query'."""

model = init_chat_model(
    model="openai/gpt-oss-120b",
    model_provider="groq",
    temperature=1
)

agent = create_agent(
    model=model,
    tools=[execute_sql],
    system_prompt=SYSTEM,
    context_schema=RuntimeContext,
    checkpointer=InMemorySaver(),
    middleware=[
        SummarizationMiddleware(
            model=model,
            trigger=("tokens", 100),
            keep=("messages", 1)
        )
    ],
)

config = {"configurable": {"thread_id": "1"}}


while True:
    question = input("Ask your database query: (Enter 'q' to quit)\n")
    
    if (question == "q"):
        print("Thanks for using this agent!")
        break

    response = agent.invoke(
        {"messages": question},
        context=RuntimeContext(db=db),
        config=config
    )
    print(response["messages"][-1].content, "\n")
