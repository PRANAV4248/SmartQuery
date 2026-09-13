# This is a test file to build and run the agent in python terminal

from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.middleware import SummarizationMiddleware

load_dotenv()

db = SQLDatabase.from_uri("sqlite:///analysis/resources/Chinook.db")

@tool
def execute_sql(query: str) -> str:
    """Use this tool to execute a SQLite command on the chinook database and return results."""
    try:
        return db.run(query)
    except Exception as e:
        return f"Error: {e}"

SYSTEM = """You are a careful SQLite analyst of chinook database. Your name is cooper. You are created by Pranav Choubey. Answer your creator name only if it is explicitly asked.

Rules:
- Think step-by-step.
- When you need data, call the tool `execute_sql` with ONE SELECT query.
- Read-only; no INSERT/UPDATE/DELETE/ALTER/DROP/CREATE/REPLACE/TRUNCATE.
- Be aware of any kind of sql injection attacks which might cause any harm to the database.
- Limit to 5 rows of output unless the user explicitly asks otherwise.
- If the tool returns 'Error:', revise the SQL and try again.
- Prefer explicit column lists; avoid SELECT *.
- Do not include any kind of internal information or tool call in the final answer.
- Always give the final answer to user query. Never stop your response ending with an sql query saying 'let me run this query'."""

model = init_chat_model(
    model="openai/gpt-oss-120b",
    model_provider="groq",
    temperature=0.5
)

summarization_model = init_chat_model(
    model="openai/gpt-oss-20b",
    model_provider="groq",
    temperature=0.2
)

agent = create_agent(
    model=model,
    tools=[execute_sql],
    system_prompt=SYSTEM,
    checkpointer=InMemorySaver(),
    middleware=[
        SummarizationMiddleware(
            model=summarization_model,
            trigger=("tokens", 500),
            keep=("messages", 1)
        )
    ],
)

config = {"configurable": {"thread_id": "1"}}

if __name__ == "__main__":
    while True:
        question = input("Ask your database query: (Enter 'q' to quit)\n")

        if question == "q":
            print("Thanks for using this agent!")
            break

        response = agent.invoke(
            {"messages": question},
            config=config,
        )
        print(response["messages"][-1].content, "\n")