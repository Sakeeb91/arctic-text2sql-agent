"""End-to-end test of the Text2SQL agent."""

import asyncio
import os

# Set env vars before importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test.db")


async def test_agent():
    from dotenv import load_dotenv

    load_dotenv(override=True)

    from app.agent import get_agent_engine

    print("Initializing agent...")
    engine = await get_agent_engine()
    print("Agent ready!")

    query = "Show me all active users with their total order amounts"
    print(f"\nQuery: {query}")
    print("Generating SQL...")

    result = await engine.generate_sql(
        natural_query=query,
        database_id="default",
        execute=True,
        show_reasoning=True,
    )

    print("\n" + "=" * 50)
    print("FINAL RESULT")
    print("=" * 50)
    print(f"SQL: {result.sql}")
    print(f"Confidence: {result.confidence}")
    if result.execution_results:
        print(f"Rows returned: {len(result.execution_results)}")
        for row in result.execution_results:
            print(f"  {row}")


if __name__ == "__main__":
    asyncio.run(test_agent())
