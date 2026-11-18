"""Telegram-бот на aiogram 3: облік витрат на авто."""

import asyncio
import logging
import os
import re
from datetime import date
from decimal import Decimal

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, Message, User as TgUser
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError

from app import crud, db
from app.models import Car

# Читає змінні з файлу .env (якщо він є) у змінні середовища.
# У Docker файлу .env немає — там змінні передає docker-compose.
load_dotenv()

logger = logging.getLogger(__name__)

dp = Dispatcher()

# Кнопки головного меню (внизу екрана замість клавіатури)
BTN_ADD_CAR = "🚗 Додати авто"
BTN_CARS = "📋 Мої авто"
BTN_EXPENSE = "💸 Додати витрату"
BTN_HELP = "❓ Допомога"
MENU_BUTTONS = [BTN_ADD_CAR, BTN_CARS, BTN_EXPENSE, BTN_HELP]


def main_menu():
    keyboard = ReplyKeyboardBuilder()
    for text in MENU_BUTTONS:
        keyboard.button(text=text)
    keyboard.adjust(2)  # дві кнопки в ряду
    return keyboard.as_markup(
        resize_keyboard=True,  # компактні кнопки, а не на пів екрана
        is_persistent=True,  # меню не ховається після натискання
        input_field_placeholder="Оберіть дію в меню",
    )


# Команди для кнопки «Меню» в Telegram (біля поля вводу)
BOT_COMMANDS = [
    BotCommand(command="start", description="Головне меню"),
    BotCommand(command="addcar", description="Додати авто"),
    BotCommand(command="cars", description="Мої авто"),
    BotCommand(command="expense", description="Додати витрату"),
    BotCommand(command="cancel", description="Скасувати поточну дію"),
    BotCommand(command="help", description="Допомога"),
]

# Список команд — спільний для /start і /help.
COMMANDS_TEXT = (
    "Користуйтеся кнопками внизу екрана або командами:\n"
    "/addcar — додати авто\n"
    "/cars — мої авто\n"
    "/expense — записати витрату на авто\n"
    "/cancel — скасувати поточну дію\n"
    "/help — допомога"
)

AMOUNT_HELP = (
    "Не вдалося розпізнати суму. Напишіть число без пробілів, "
    "за потреби — з копійками, і опис через пробіл:\n"
    "450 заміна фар\n"
    "1250,50 доставка з Польщі\n\n"
    "Скасувати — /cancel"
)

ADDCAR_HELP = (
    "Напишіть марку, модель, рік і за бажанням VIN, наприклад:\n"
    "BMW X5 2018\n"
    "Audi A6 Avant 2019 WAUZZZ4G0KN012345\n\n"
    "Марка — одне слово (якщо з двох — через дефіс: Land-Rover).\n"
    "Скасувати — /cancel"
)

# VIN: 17 символів, латиниця й цифри, без I, O, Q
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
# Сума: ціле число або з 1–2 знаками після крапки чи коми, до 10 цифр перед ними
AMOUNT_RE = re.compile(r"^\d{1,10}([.,]\d{1,2})?$")


class AddCarForm(StatesGroup):
    """Додавання авто: бот чекає повідомлення з даними авто."""

    entering_car = State()


class ExpenseForm(StatesGroup):
    """Кроки запису витрати: авто → категорія → сума й опис."""

    choosing_car = State()
    choosing_category = State()
    entering_amount = State()


def format_money(amount: Decimal) -> str:
    """1234.5 → '1 234.50'"""
    return f"{amount:,.2f}".replace(",", " ")


def car_title(car: Car) -> str:
    return f"{car.brand} {car.model} {car.year}"


def parse_car(args: str | None) -> tuple[str, str, int, str | None] | str:
    """Розбирає 'BMW X5 2018 [VIN]'. Повертає дані авто або текст помилки."""
    parts = (args or "").split()
    # Рік — перше чотиризначне число після марки й хоча б одного слова моделі
    year_index = next(
        (i for i, part in enumerate(parts) if i >= 2 and part.isdigit() and len(part) == 4),
        None,
    )
    if year_index is None or len(parts) > year_index + 2:
        return ADDCAR_HELP

    brand = parts[0]
    model = " ".join(parts[1:year_index])
    year = int(parts[year_index])
    vin = parts[year_index + 1].upper() if len(parts) > year_index + 1 else None

    if len(brand) > 50 or len(model) > 50:
        return "Марка й модель — до 50 символів кожна."
    if not 1950 <= year <= date.today().year + 1:
        return f"Рік {year} виглядає неправильно. Вкажіть рік випуску, напр. 2018."
    if vin is not None and not VIN_RE.match(vin):
        return "VIN має містити 17 символів: латинські літери (без I, O, Q) і цифри."
    return brand, model, year, vin


def parse_amount(text: str) -> tuple[Decimal, str | None] | str:
    """Розбирає '450 заміна фар' або '1250,50'. Повертає (сума, опис) або текст помилки."""
    parts = text.strip().split(maxsplit=1)
    if not parts or not AMOUNT_RE.match(parts[0]):
        return AMOUNT_HELP
    description = parts[1].strip() if len(parts) > 1 else None

    # '1 200 ремонт' — схоже на суму з пробілом між тисячами, а не 1 і опис '200 ремонт'
    if description and re.match(r"^\d{3}\b", description):
        return "Схоже, сума написана з пробілом. Напишіть її разом: 1200 ремонт"

    amount = Decimal(parts[0].replace(",", "."))
    if amount <= 0:
        return "Сума має бути більшою за 0."
    return amount, description


async def get_db_user(session, tg_user: TgUser):
    return await crud.get_or_create_user(
        session, tg_user.id, tg_user.username, tg_user.first_name
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info("Команда /start від user_id=%s", message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(
        f"Привіт! Я бот для обліку витрат на авто.\n\n{COMMANDS_TEXT}",
        reply_markup=main_menu(),
    )


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(message: Message, state: FSMContext) -> None:
    logger.info("Команда /help від user_id=%s", message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(
        "Я рахую, скільки грошей вкладено в кожне авто: купівля, доставка, "
        "розмитнення, ремонт, запчастини.\n\n"
        f"Спершу додайте авто ({BTN_ADD_CAR}), потім записуйте витрати ({BTN_EXPENSE}).\n\n"
        f"{COMMANDS_TEXT}",
        reply_markup=main_menu(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нічого скасовувати.")
        return
    await state.clear()
    await message.answer("Скасовано.")


@dp.message(Command("addcar"))
@dp.message(F.text == BTN_ADD_CAR)
async def cmd_addcar(
    message: Message, state: FSMContext, command: CommandObject | None = None
) -> None:
    await state.clear()
    if command is None or not command.args:
        # Кнопка або команда без даних — дані авто чекаємо наступним повідомленням
        await state.set_state(AddCarForm.entering_car)
        await message.answer(ADDCAR_HELP)
        return
    await save_car(message, command.args, state)


# Текст із кнопок меню — не дані авто: його обробляють обробники кнопок нижче
@dp.message(AddCarForm.entering_car, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def addcar_enter_data(message: Message, state: FSMContext) -> None:
    await save_car(message, message.text, state)


async def save_car(message: Message, text: str, state: FSMContext) -> None:
    """Розбирає дані авто й зберігає його. При помилці лишає користувача на цьому кроці."""
    parsed = parse_car(text)
    if isinstance(parsed, str):
        await state.set_state(AddCarForm.entering_car)
        await message.answer(parsed if parsed != ADDCAR_HELP else "Не вдалося розібрати.\n\n" + ADDCAR_HELP)
        return
    brand, model, year, vin = parsed

    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        try:
            car = await crud.add_car(session, user.id, brand, model, year, vin)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await state.set_state(AddCarForm.entering_car)
            await message.answer(f"Авто з VIN {vin} уже є в базі. Перевірте VIN або /cancel")
            return

    await state.clear()
    logger.info("Додано авто car_id=%s від user_id=%s", car.id, message.from_user.id)
    await message.answer(
        f"✅ Авто додано: {car_title(car)}"
        + (f"\nVIN: {car.vin}" if car.vin else "")
        + f"\n\nТепер можна записувати витрати: {BTN_EXPENSE}"
    )


@dp.message(Command("cars"))
@dp.message(F.text == BTN_CARS)
async def cmd_cars(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        cars = await crud.list_cars(session, user.id)
        totals = [await crud.car_total(session, car.id) for car in cars]
        await session.commit()

    if not cars:
        await message.answer(f"У вас ще немає авто. Додати — {BTN_ADD_CAR}")
        return

    lines = [
        f"{i}. {car_title(car)}" + (f" (VIN {car.vin})" if car.vin else "")
        + f" — витрачено {format_money(total)}"
        for i, (car, total) in enumerate(zip(cars, totals), start=1)
    ]
    await message.answer("Ваші авто:\n\n" + "\n".join(lines))


@dp.message(Command("expense"))
@dp.message(F.text == BTN_EXPENSE)
async def cmd_expense(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        cars = await crud.list_cars(session, user.id)
        await session.commit()

    if not cars:
        await state.set_state(AddCarForm.entering_car)
        await message.answer(f"Спершу додайте авто, до якого запишемо витрату.\n\n{ADDCAR_HELP}")
        return

    keyboard = InlineKeyboardBuilder()
    for car in cars:
        keyboard.button(text=car_title(car), callback_data=f"exp_car:{car.id}")
    keyboard.button(text="✖ Скасувати", callback_data="exp_cancel")
    keyboard.adjust(1)

    await state.set_state(ExpenseForm.choosing_car)
    await message.answer("До якого авто записати витрату?", reply_markup=keyboard.as_markup())


@dp.callback_query(F.data == "exp_cancel")
async def expense_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Запис витрати скасовано.")
    await callback.answer()


@dp.callback_query(ExpenseForm.choosing_car, F.data.startswith("exp_car:"))
async def expense_choose_car(callback: CallbackQuery, state: FSMContext) -> None:
    car_id = int(callback.data.split(":", 1)[1])

    async with db.session_factory() as session:
        user = await get_db_user(session, callback.from_user)
        # Перевіряємо, що авто належить саме цьому користувачу
        car = await crud.get_user_car(session, user.id, car_id)
        categories = await crud.list_categories(session)
        await session.commit()

    if car is None:
        await state.clear()
        await callback.message.edit_text("Авто не знайдено. Почніть заново: /expense")
        await callback.answer()
        return

    await state.update_data(car_id=car.id, car_title=car_title(car))
    await state.set_state(ExpenseForm.choosing_category)

    keyboard = InlineKeyboardBuilder()
    for category in categories:
        keyboard.button(text=category.name, callback_data=f"exp_cat:{category.id}")
    keyboard.button(text="✖ Скасувати", callback_data="exp_cancel")
    keyboard.adjust(2)

    await callback.message.edit_text(
        f"Авто: {car_title(car)}\n\nОберіть категорію:", reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@dp.callback_query(ExpenseForm.choosing_category, F.data.startswith("exp_cat:"))
async def expense_choose_category(callback: CallbackQuery, state: FSMContext) -> None:
    category_id = int(callback.data.split(":", 1)[1])

    async with db.session_factory() as session:
        category = await crud.get_category(session, category_id)

    if category is None:
        await callback.answer("Категорію не знайдено", show_alert=True)
        return

    await state.update_data(category_id=category.id, category_name=category.name)
    await state.set_state(ExpenseForm.entering_amount)
    data = await state.get_data()

    await callback.message.edit_text(
        f"Авто: {data['car_title']}\n"
        f"Категорія: {category.name}\n\n"
        "Надішліть суму й опис, наприклад:\n"
        "450 заміна фар\n\n"
        "Скасувати — /cancel"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("exp_"))
async def expense_outdated_button(callback: CallbackQuery) -> None:
    """Натиснута кнопка зі старого повідомлення (наприклад, після перезапуску бота)."""
    await callback.answer("Ця кнопка вже не діє. Почніть заново: /expense", show_alert=True)


@dp.message(ExpenseForm.entering_amount, F.text, ~F.text.in_(MENU_BUTTONS))
async def expense_enter_amount(message: Message, state: FSMContext) -> None:
    parsed = parse_amount(message.text)
    if isinstance(parsed, str):
        await message.answer(parsed)
        return
    amount, description = parsed
    data = await state.get_data()

    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        car = await crud.get_user_car(session, user.id, data["car_id"])
        if car is None:
            await state.clear()
            await message.answer("Авто не знайдено. Почніть заново: /expense")
            return
        transaction = await crud.add_transaction(
            session, user.id, car.id, data["category_id"], amount, description
        )
        total = await crud.car_total(session, car.id)
        await session.commit()

    await state.clear()
    logger.info(
        "Записано витрату transaction_id=%s car_id=%s від user_id=%s",
        transaction.id, car.id, message.from_user.id,
    )
    await message.answer(
        "✅ Витрату записано\n\n"
        f"Авто: {car_title(car)}\n"
        f"Категорія: {data['category_name']}\n"
        f"Сума: {format_money(amount)}"
        + (f"\nОпис: {description}" if description else "")
        + f"\n\nУсього витрачено на це авто: {format_money(total)}"
    )


@dp.message()
async def unknown_message(message: Message) -> None:
    """Усе, що не підійшло жодному обробнику вище: бот не мовчить, а підказує."""
    await message.answer(f"Не зрозумів повідомлення.\n\n{COMMANDS_TEXT}", reply_markup=main_menu())


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("Не задано BOT_TOKEN — бот не може запуститися")
        raise SystemExit("Не задано BOT_TOKEN. Додайте його у файл .env (див. .env.example).")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("Не задано DATABASE_URL — бот не може підключитися до бази")
        raise SystemExit("Не задано DATABASE_URL. Додайте його у файл .env (див. .env.example).")

    db.setup_engine(database_url)
    await db.init_db()

    bot = Bot(token=token)
    # Список команд для кнопки «Меню» біля поля вводу в Telegram
    await bot.set_my_commands(BOT_COMMANDS)
    logger.info("Бот запускається")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close_db()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
