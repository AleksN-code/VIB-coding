"""Мінімальний Telegram-бот на aiogram 3: відповідає на /start і /help."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

# Читає змінні з файлу .env (якщо він є) у змінні середовища.
# У Docker файлу .env немає — там BOT_TOKEN передає docker-compose.
load_dotenv()

dp = Dispatcher()

# Список команд — спільний для /start і /help.
COMMANDS_TEXT = (
    "Доступні команди:\n"
    "/start — привітання і список команд\n"
    "/help — що вміє бот і які команди доступні"
)


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(f"Привіт! Я твій перший бот на aiogram.\n\n{COMMANDS_TEXT}")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        f"Я навчальний Telegram-бот, створений на aiogram 3.\n\n{COMMANDS_TEXT}"
    )


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задано BOT_TOKEN. Додайте його у файл .env (див. .env.example).")

    bot = Bot(token=token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
