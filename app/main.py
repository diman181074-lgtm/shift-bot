import asyncio
import os
from urllib.parse import urlsplit

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from app.bot import router
from app.config import settings
from app.db import Base, engine
from app.telegram_link import TelegramLinkMiddleware
from seed_data import seed
import app.models  # noqa: F401 - register SQLAlchemy models


app = FastAPI(title="Shift Handover Bot")


@app.on_event("startup")
async def startup() -> None:
    parsed = urlsplit(settings.database_url)
    print(
        f"Database preflight: host={parsed.hostname!r}, "
        f"port={parsed.port!r}, database={parsed.path.lstrip('/')!r}"
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await seed()
    except Exception as exc:
        print(f"Database startup failed: {type(exc).__name__}: {exc}")
        raise


@app.on_event("shutdown")
async def shutdown() -> None:
    await engine.dispose()


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


async def run_web() -> None:
    # Render provides PORT for web services (default 10000).
    port = int(os.getenv("PORT", str(settings.port)))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    bot_task = asyncio.create_task(run_bot())
    web_task = asyncio.create_task(run_web())
    try:
        await asyncio.gather(bot_task, web_task)
    finally:
        for task in (bot_task, web_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(bot_task, web_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
