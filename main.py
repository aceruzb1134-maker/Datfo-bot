import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from utils.db import init_db
from handlers import admin, pharmacy

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env файле")
    if not ADMIN_IDS:
        raise ValueError("ADMIN_IDS не задан в .env файле")

    await init_db()
    print("✅ База данных инициализирована")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Pass admin_ids to all handlers via middleware data
    dp["admin_ids"] = ADMIN_IDS

    # Register routers — admin first so /start is handled correctly
    dp.include_router(pharmacy.router)
    dp.include_router(admin.router)
    

    print(f"🤖 Бот запущен. Администраторы: {ADMIN_IDS}")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
