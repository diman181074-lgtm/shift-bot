import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from app.bot import router
from app.config import settings
from app.db import Base, engine
from app.telegram_link import TelegramLinkMiddleware
import app.models  # noqa: F401 - register SQLAlchemy models


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Shift Handover Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def run_bot() -> None:
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(TelegramLinkMiddleware())
    dispatcher.callback_query.outer_middleware(TelegramLinkMiddleware())
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
