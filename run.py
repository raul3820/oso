import logfire

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio

from db.func import DBFunctions
from models import agent
from interfaces import reddit

logfire.configure(send_to_logfire='never',scrubbing=False)
logfire.instrument_asyncpg()

app = FastAPI()
db = None
agent_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    logfire.info("Starting application...")
    global db, agent_manager
    db = DBFunctions()
    await db.connect()
    await db.create_schema()
    agent_service = await agent.run_agent_pipeline_service(db)
    reddit_service = await reddit.run_service(db)

    yield

    logfire.info("Shutting down application...")
    await db.close()

app = FastAPI(lifespan=lifespan)

if __name__ == '__main__':
    async def main():
        async with lifespan(app):
            logfire.info("Application services are running in the background. Press Ctrl+C to stop.")
            await asyncio.Future()

    asyncio.run(main())