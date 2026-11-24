"""Telegram-бот на aiogram 3: облік витрат і продажу авто."""

import asyncio
import logging
import os
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, Message, User as TgUser
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

from app import crud, db, rules, services
from app.crud import CarSummary
from app.errors import AppError, ConflictError, RateUnavailableError, ValidationError
from app.models import EXPENSE, INCOME, SALE_CATEGORY, Car, Category, Transaction
# Дати операцій — за київським часом; правила перевірки — спільні з web-адмінкою
from app.rules import kyiv_today

# Читає змінні з файлу .env (якщо він є) у змінні середовища.
# У Docker файлу .env немає — там змінні передає docker-compose.
load_dotenv()

logger = logging.getLogger(__name__)

dp = Dispatcher()


# ---------- Меню й тексти ----------

# Кнопки головного меню (внизу екрана замість клавіатури)
BTN_ADD_CAR = "🚗 Додати авто"
BTN_CARS = "📋 Мої авто"
BTN_EXPENSE = "💸 Додати витрату"
BTN_SALE = "💰 Продаж авто"
BTN_HELP = "❓ Допомога"
MENU_BUTTONS = [BTN_ADD_CAR, BTN_CARS, BTN_EXPENSE, BTN_SALE, BTN_HELP]


def main_menu():
    keyboard = ReplyKeyboardBuilder()
    for text in MENU_BUTTONS:
        keyboard.button(text=text)
    keyboard.adjust(2, 2, 1)
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
    BotCommand(command="sell", description="Продаж авто"),
    BotCommand(command="cancel", description="Скасувати поточну дію"),
    BotCommand(command="help", description="Допомога"),
]

COMMANDS_TEXT = (
    "Користуйтеся кнопками внизу екрана:\n"
    f"{BTN_ADD_CAR} — нове авто\n"
    f"{BTN_EXPENSE} — витрата на авто\n"
    f"{BTN_SALE} — дохід від продажу\n"
    f"{BTN_CARS} — витрати, продаж і прибуток по кожному авто; "
    "там же можна змінити чи видалити авто та його операції\n"
    f"{BTN_HELP}\n\n"
    "Скасувати будь-яку дію — /cancel"
)

AMOUNT_HELP = (
    "Не вдалося розпізнати суму. Напишіть число без пробілів, "
    "за потреби — з копійками, і опис через пробіл:\n"
    "450 заміна фар\n"
    "1250,50 доставка з Польщі"
)

ADDCAR_HELP = (
    "🚗 Напишіть марку, модель, рік і за бажанням VIN, наприклад:\n"
    "BMW X5 2018\n"
    "Audi A6 Avant 2019 WAUZZZ4G0KN012345\n\n"
    "Марка — одне слово (якщо з двох — через дефіс: Land-Rover).\n"
    "Скасувати — /cancel"
)

DATE_HELP = "✏️ Напишіть дату у форматі ДД.ММ.РРРР, наприклад 18.11.2026"

CATEGORY_ICONS = {
    "Купівля авто": "🛒",
    "Доставка": "🚚",
    "Розмитнення": "🛃",
    "Ремонт": "🔧",
    "Запчастини": "⚙️",
    "Інше": "📦",
    SALE_CATEGORY: "💰",
}

CURRENCY_BUTTONS = {"UAH": "₴ Гривня", "USD": "$ Долар"}
CURRENCY_IN = {"UAH": "у гривнях", "USD": "у доларах"}

# Вид операції в одному спільному сценарії
KIND_EXPENSE = "expense"
KIND_SALE = "sale"

# Формат тексту в чаті. Самі правила (сума > 0, дата не в майбутньому, VIN тощо) — в app/rules.py.
# Сума: ціле число або з 1–2 знаками після крапки чи коми, до 10 цифр перед ними
AMOUNT_RE = re.compile(r"^\d{1,10}([.,]\d{1,2})?$")
# Дата: 25.11.2026 (також 25-11-2026, 25/11/2026)
DATE_RE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")


class AddCarForm(StatesGroup):
    """Додавання авто: бот чекає повідомлення з даними авто."""

    entering_car = State()


class OperationForm(StatesGroup):
    """Кроки запису операції.

    Витрата: авто → категорія → дата → валюта → сума.
    Продаж:  авто → дата → валюта → сума.
    """

    choosing_car = State()
    choosing_category = State()
    choosing_date = State()
    entering_date = State()
    choosing_currency = State()
    entering_amount = State()


# ---------- Форматування ----------


def format_money(amount: Decimal) -> str:
    """Сума для показу — до цілого числа: 1234.5 → '1 235'.

    У базі суми зберігаються з копійками; округлюємо лише те, що бачить користувач.
    """
    whole = amount.quantize(Decimal("1"), ROUND_HALF_UP)
    return f"{whole:,}".replace(",", " ")


def format_rate(rate: Decimal) -> str:
    """Курс для показу — 2 знаки після коми: 45.0811 → '45.08'. У базі — 4 знаки, як у НБУ."""
    return str(rate.quantize(Decimal("0.01"), ROUND_HALF_UP))


def uah_usd(uah: Decimal, usd: Decimal) -> str:
    return f"{format_money(uah)} грн (${format_money(usd)})"


def signed_uah_usd(uah: Decimal, usd: Decimal) -> str:
    """Прибуток зі знаком: +351 000 грн (+$7 934)."""

    def sign(value: Decimal) -> str:
        return "+" if value > 0 else "−" if value < 0 else ""

    return f"{sign(uah)}{format_money(abs(uah))} грн ({sign(usd)}${format_money(abs(usd))})"


def car_title(car: Car) -> str:
    return f"{car.brand} {car.model} {car.year}"


def category_label(name: str) -> str:
    return f"{CATEGORY_ICONS.get(name, '•')} {name}"


def car_card(car: Car, summary: CarSummary) -> str:
    """Картка авто для «Мої авто»."""
    lines = [f"🚗 {car_title(car)}"]
    if car.vin:
        lines.append(f"🔖 VIN: {car.vin}")
    if summary.sold:
        lines.append(f"✅ Продано {summary.sale_date:%d.%m.%Y}")
    else:
        lines.append("🛠 В роботі")
    lines.append(f"💸 Витрати: {uah_usd(summary.expenses_uah, summary.expenses_usd)}")
    if summary.sold:
        lines.append(f"💰 Продаж: {uah_usd(summary.income_uah, summary.income_usd)}")
        icon, word = ("📈", "Прибуток") if summary.profit_uah >= 0 else ("📉", "Збиток")
        lines.append(f"{icon} {word}: {signed_uah_usd(summary.profit_uah, summary.profit_usd)}")
    return "\n".join(lines)


# ---------- Розбір введеного тексту ----------


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
    vin = parts[year_index + 1] if len(parts) > year_index + 1 else None
    try:
        return rules.check_car(brand, model, year, vin)
    except ValidationError as error:
        return error.message


def parse_amount(text: str) -> tuple[Decimal, str | None] | str:
    """Розбирає '450 заміна фар' або '1250,50'. Повертає (сума, опис) або текст помилки."""
    parts = text.strip().split(maxsplit=1)
    if not parts or not AMOUNT_RE.match(parts[0]):
        return AMOUNT_HELP
    description = parts[1].strip() if len(parts) > 1 else None

    # '1 200 ремонт' — схоже на суму з пробілом між тисячами, а не 1 і опис '200 ремонт'
    if description and re.match(r"^\d{3}\b", description):
        return "Схоже, сума написана з пробілом. Напишіть її разом: 1200 ремонт"

    try:
        amount = rules.check_amount(Decimal(parts[0].replace(",", ".")))
        description = rules.check_description(description)
    except ValidationError as error:
        return error.message
    return amount, description


def parse_date(text: str) -> date | str:
    """Розбирає '25.11.2026'. Повертає дату або текст помилки."""
    match = DATE_RE.match(text.strip())
    if not match:
        return DATE_HELP
    try:
        day = date(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        return f"Такої дати не існує. {DATE_HELP}"
    try:
        return rules.check_operation_date(day)
    except ValidationError as error:
        return error.message


# ---------- Клавіатури кроків ----------


def cancel_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    return keyboard


def date_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📅 Сьогодні", callback_data="op_date:today")
    keyboard.button(text="📅 Вчора", callback_data="op_date:yesterday")
    keyboard.button(text="✏️ Інша дата", callback_data="op_date:other")
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    keyboard.adjust(2, 1, 1)
    return keyboard.as_markup()


def currency_keyboard():
    keyboard = InlineKeyboardBuilder()
    for code, text in CURRENCY_BUTTONS.items():
        keyboard.button(text=text, callback_data=f"op_cur:{code}")
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    keyboard.adjust(2, 1)
    return keyboard.as_markup()


def operation_header(data: dict) -> str:
    """Що вже обрано на попередніх кроках — показуємо над кожним наступним кроком."""
    title = "💸 Нова витрата" if data["kind"] == KIND_EXPENSE else "💰 Продаж авто"
    lines = [title, ""]
    if "car_title" in data:
        lines.append(f"🚗 {data['car_title']}")
    if "category_name" in data:
        lines.append(category_label(data["category_name"]))
    if "op_date" in data:
        lines.append(f"📅 {date.fromisoformat(data['op_date']):%d.%m.%Y}")
    if "currency" in data:
        lines.append(CURRENCY_BUTTONS[data["currency"]])
    return "\n".join(lines)


async def get_db_user(session, tg_user: TgUser):
    return await crud.get_or_create_user(
        session, tg_user.id, tg_user.username, tg_user.first_name
    )


# ---------- Загальні команди ----------


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info("Команда /start від user_id=%s", message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(
        f"👋 Привіт! Я рахую витрати, продаж і прибуток по кожному авто.\n\n{COMMANDS_TEXT}",
        reply_markup=main_menu(),
    )


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(message: Message, state: FSMContext) -> None:
    logger.info("Команда /help від user_id=%s", message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(
        "❓ Як користуватися\n\n"
        f"1. {BTN_ADD_CAR} — марка, модель, рік.\n"
        f"2. {BTN_EXPENSE} — авто → категорія → дата → валюта → сума й опис.\n"
        f"3. {BTN_SALE} — авто → дата продажу → валюта → сума.\n"
        f"4. {BTN_CARS} — витрати, продаж і прибуток по кожному авто.\n"
        f"5. Змінити чи видалити операцію: {BTN_CARS} → авто → «📄 Операції» → операція → "
        "«✏️ Змінити» або «🗑 Видалити».\n"
        f"6. Змінити чи видалити авто: {BTN_CARS} → авто → «✏️ Змінити авто» або «🗑 Видалити авто».\n\n"
        "Суму можна вводити в гривнях або доларах — друга валюта рахується "
        "за офіційним курсом НБУ на дату операції.\n\n"
        "Скасувати будь-яку дію — /cancel",
        reply_markup=main_menu(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нічого скасовувати.")
        return
    await state.clear()
    await message.answer("✖ Скасовано.")


# ---------- Авто ----------


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


# Текст із кнопок меню — не дані авто: його обробляють обробники кнопок
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
            car = await services.create_car(session, user.id, brand, model, year, vin)
        except AppError as error:
            await state.set_state(AddCarForm.entering_car)
            await message.answer(f"{error.message} Перевірте дані або /cancel")
            return
        await session.commit()

    await state.clear()
    logger.info("Додано авто car_id=%s від user_id=%s", car.id, message.from_user.id)
    await message.answer(
        f"✅ Авто додано\n\n🚗 {car_title(car)}"
        + (f"\n🔖 VIN: {car.vin}" if car.vin else "")
        + f"\n\nТепер можна записувати витрати: {BTN_EXPENSE}"
    )


@dp.message(Command("cars"))
@dp.message(F.text == BTN_CARS)
async def cmd_cars(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = await cars_overview(message.from_user)
    await message.answer(text, reply_markup=markup)


# ---------- Запис операції: витрата або продаж ----------


@dp.message(Command("expense"))
@dp.message(F.text == BTN_EXPENSE)
async def cmd_expense(message: Message, state: FSMContext) -> None:
    await start_operation(message, state, KIND_EXPENSE)


@dp.message(Command("sell"))
@dp.message(F.text == BTN_SALE)
async def cmd_sell(message: Message, state: FSMContext) -> None:
    await start_operation(message, state, KIND_SALE)


async def start_operation(message: Message, state: FSMContext, kind: str) -> None:
    """Крок 1: вибір авто."""
    await state.clear()
    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        cars = await crud.list_cars(session, user.id)
        summaries = [await crud.car_summary(session, car.id) for car in cars]
        await session.commit()

    if not cars:
        await state.set_state(AddCarForm.entering_car)
        await message.answer(f"Спершу додайте авто.\n\n{ADDCAR_HELP}")
        return

    keyboard = InlineKeyboardBuilder()
    for car, summary in zip(cars, summaries):
        if kind == KIND_SALE and summary.sold:
            continue  # продане авто вдруге не продаємо
        label = f"🚗 {car_title(car)}" + (" · ✅ продано" if summary.sold else "")
        keyboard.button(text=label, callback_data=f"op_car:{car.id}")
    if kind == KIND_SALE and all(summary.sold for summary in summaries):
        await message.answer(f"✅ Усі ваші авто вже продані. Нове авто — {BTN_ADD_CAR}")
        return
    keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
    keyboard.adjust(1)

    await state.set_state(OperationForm.choosing_car)
    await state.update_data(kind=kind)
    question = "Оберіть авто:" if kind == KIND_EXPENSE else "Яке авто продано?"
    await message.answer(
        f"{operation_header({'kind': kind})}\n\n{question}", reply_markup=keyboard.as_markup()
    )


@dp.callback_query(F.data == "op_cancel")
async def operation_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("✖ Скасовано.")
    await callback.answer()


@dp.callback_query(OperationForm.choosing_car, F.data.startswith("op_car:"))
async def operation_choose_car(callback: CallbackQuery, state: FSMContext) -> None:
    """Крок 2: категорія (для витрати) або одразу дата (для продажу)."""
    car_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()

    async with db.session_factory() as session:
        user = await get_db_user(session, callback.from_user)
        # Перевіряємо, що авто належить саме цьому користувачу
        car = await crud.get_car(session, car_id, owner_id=user.id)
        summary = await crud.car_summary(session, car_id) if car else None
        categories = await crud.list_categories(session, EXPENSE)
        await session.commit()

    if car is None:
        await state.clear()
        await callback.message.edit_text("Авто не знайдено. Почніть заново.")
        await callback.answer()
        return
    if data["kind"] == KIND_SALE and summary.sold:
        await callback.answer("Це авто вже продано", show_alert=True)
        return

    await state.update_data(car_id=car.id, car_title=car_title(car))
    data = await state.get_data()

    if data["kind"] == KIND_EXPENSE:
        keyboard = InlineKeyboardBuilder()
        for category in categories:
            keyboard.button(text=category_label(category.name), callback_data=f"op_cat:{category.id}")
        keyboard.button(text="✖ Скасувати", callback_data="op_cancel")
        keyboard.adjust(2)
        await state.set_state(OperationForm.choosing_category)
        await callback.message.edit_text(
            f"{operation_header(data)}\n\nОберіть категорію:", reply_markup=keyboard.as_markup()
        )
    else:
        await state.set_state(OperationForm.choosing_date)
        await callback.message.edit_text(
            f"{operation_header(data)}\n\nДата продажу:", reply_markup=date_keyboard()
        )
    await callback.answer()


@dp.callback_query(OperationForm.choosing_category, F.data.startswith("op_cat:"))
async def operation_choose_category(callback: CallbackQuery, state: FSMContext) -> None:
    """Крок 3 (витрата): дата."""
    category_id = int(callback.data.split(":", 1)[1])
    async with db.session_factory() as session:
        category = await crud.get_category(session, category_id)

    if category is None or category.type != EXPENSE:
        await callback.answer("Категорію не знайдено", show_alert=True)
        return

    await state.update_data(category_id=category.id, category_name=category.name)
    await state.set_state(OperationForm.choosing_date)
    data = await state.get_data()
    await callback.message.edit_text(
        f"{operation_header(data)}\n\nДата витрати:", reply_markup=date_keyboard()
    )
    await callback.answer()


@dp.callback_query(OperationForm.choosing_date, F.data.startswith("op_date:"))
async def operation_choose_date(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":", 1)[1]
    if choice == "other":
        await state.set_state(OperationForm.entering_date)
        data = await state.get_data()
        await callback.message.edit_text(
            f"{operation_header(data)}\n\n{DATE_HELP}", reply_markup=cancel_keyboard().as_markup()
        )
        await callback.answer()
        return

    day = kyiv_today() if choice == "today" else kyiv_today() - timedelta(days=1)
    await state.update_data(op_date=day.isoformat())
    await state.set_state(OperationForm.choosing_currency)
    data = await state.get_data()
    await callback.message.edit_text(
        f"{operation_header(data)}\n\nУ якій валюті сума?", reply_markup=currency_keyboard()
    )
    await callback.answer()


@dp.message(OperationForm.entering_date, F.text, ~F.text.in_(MENU_BUTTONS))
async def operation_enter_date(message: Message, state: FSMContext) -> None:
    parsed = parse_date(message.text)
    if isinstance(parsed, str):
        await message.answer(parsed, reply_markup=cancel_keyboard().as_markup())
        return

    await state.update_data(op_date=parsed.isoformat())
    await state.set_state(OperationForm.choosing_currency)
    data = await state.get_data()
    await message.answer(
        f"{operation_header(data)}\n\nУ якій валюті сума?", reply_markup=currency_keyboard()
    )


@dp.callback_query(OperationForm.choosing_currency, F.data.startswith("op_cur:"))
async def operation_choose_currency(callback: CallbackQuery, state: FSMContext) -> None:
    currency = callback.data.split(":", 1)[1]
    if currency not in CURRENCY_BUTTONS:
        await callback.answer("Невідома валюта", show_alert=True)
        return

    await state.update_data(currency=currency)
    await state.set_state(OperationForm.entering_amount)
    data = await state.get_data()
    example = "450 заміна фар" if data["kind"] == KIND_EXPENSE else "1500000 продаж через OLX"
    if currency == "USD":
        example = "300 заміна фар" if data["kind"] == KIND_EXPENSE else "35000 продаж через OLX"
    await callback.message.edit_text(
        f"{operation_header(data)}\n\n"
        f"💵 Надішліть суму {CURRENCY_IN[currency]} і за бажанням опис, наприклад:\n{example}",
        reply_markup=cancel_keyboard().as_markup(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith(("op_", "exp_")))
async def operation_outdated_button(callback: CallbackQuery) -> None:
    """Кнопка зі старого повідомлення (наприклад, після перезапуску бота або іншого кроку)."""
    await callback.answer("Ця кнопка вже не діє. Почніть заново з меню.", show_alert=True)


@dp.message(OperationForm.entering_amount, F.text, ~F.text.in_(MENU_BUTTONS))
async def operation_enter_amount(message: Message, state: FSMContext) -> None:
    """Останній крок: сума й опис → спільна логіка (перевірка, курс НБУ, запис у базу)."""
    parsed = parse_amount(message.text)
    if isinstance(parsed, str):
        await message.answer(parsed, reply_markup=cancel_keyboard().as_markup())
        return
    amount, description = parsed

    data = await state.get_data()
    kind = data["kind"]
    operation_date = date.fromisoformat(data["op_date"])
    currency = data["currency"]

    async with db.session_factory() as session:
        user = await get_db_user(session, message.from_user)
        if kind == KIND_SALE:
            category = await crud.get_category_by_name(session, SALE_CATEGORY)
            category_id, category_name = category.id, category.name
        else:
            category_id, category_name = data["category_id"], data["category_name"]

        try:
            transaction = await services.create_transaction(
                session,
                car_id=data["car_id"],
                category_id=category_id,
                operation_date=operation_date,
                amount=amount,
                currency=currency,
                description=description,
                owner_id=user.id,
            )
        except RateUnavailableError as error:
            # Курс НБУ тимчасово недоступний — лишаємо на цьому кроці, можна надіслати ще раз
            await message.answer(f"⚠️ {error.message}\nНадішліть суму ще раз або скасуйте — /cancel")
            return
        except AppError as error:
            # Авто не знайдено або вже продане — повторна спроба не допоможе
            await state.clear()
            icon = "✅" if isinstance(error, ConflictError) else "⚠️"
            await message.answer(f"{icon} {error.message}")
            return

        car = await crud.get_car(session, transaction.car_id)
        summary = await crud.car_summary(session, car.id)
        usd_rate = transaction.usd_rate
        await session.commit()

    await state.clear()
    logger.info(
        "Записано операцію kind=%s transaction_id=%s car_id=%s від user_id=%s",
        kind, transaction.id, car.id, message.from_user.id,
    )

    # Спершу — у валюті, в якій ввели суму
    if currency == "USD":
        amount_text = f"${format_money(transaction.amount_usd)} ({format_money(transaction.amount_uah)} грн)"
    else:
        amount_text = uah_usd(transaction.amount_uah, transaction.amount_usd)

    lines = [
        "✅ Витрату записано" if kind == KIND_EXPENSE else "✅ Продаж записано",
        "",
        f"🚗 {car_title(car)}",
        category_label(category_name),
        f"📅 {operation_date:%d.%m.%Y}",
        f"💵 {amount_text} · курс НБУ {format_rate(usd_rate)}",
    ]
    if description:
        lines.append(f"📝 {description}")
    lines += ["", "📊 Підсумок по авто", car_card(car, summary).split("\n", 1)[1]]
    # Звідси одразу можна перейти до операцій авто — наприклад, щоб виправити щойно записану
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📄 Операції авто", callback_data=CarCb(action="ops", car_id=car.id))
    await message.answer("\n".join(lines), reply_markup=keyboard.as_markup())


# ---------- Мої авто → операції: перегляд, зміна, видалення ----------
#
# «📋 Мої авто» → авто → «📄 Операції» → операція → «✏️ Змінити» / «🗑 Видалити».
# Кнопки несуть номер авто чи операції (CallbackData), тому працюють і в старих повідомленнях:
# бот щоразу заново читає дані з бази й перевіряє, що авто чи операція — саме цього користувача.
# Зміни й видалення — через спільну логіку (app/services.py), як і на сайті.

OPS_PAGE_SIZE = 10
NOT_FOUND_CAR = "Авто не знайдено — можливо, його вже видалено."
NOT_FOUND_TX = "Операцію не знайдено — можливо, її вже видалено."


class CarCb(CallbackData, prefix="car"):
    """Кнопки авто.

    action: list — усі авто, show — картка авто, ops — операції (offset — сторінка),
    edit / field / cancel — зміна авто (value — поле), del / delok — видалення.
    """

    action: str
    car_id: int = 0
    offset: int = 0
    # Порожнє значення aiogram читає як None, тому тип — «текст або None»
    value: str | None = None


class TxCb(CallbackData, prefix="tx"):
    """Кнопки операції. action: show, edit, field, date, cur, cat, car, cancel, del, delok."""

    action: str
    tx_id: int
    # Порожнє значення aiogram читає як None, тому тип — «текст або None»
    value: str | None = None


class EditTxForm(StatesGroup):
    """Зміна операції: бот чекає нове значення текстом."""

    entering_date = State()
    entering_amount = State()
    entering_description = State()


def tx_amount_text(t: Transaction) -> str:
    """Сума — спершу у валюті, в якій її ввели."""
    if t.currency == "USD":
        return f"${format_money(t.amount_usd)} ({format_money(t.amount_uah)} грн)"
    return uah_usd(t.amount_uah, t.amount_usd)


def tx_card(t: Transaction, category: Category, car: Car) -> str:
    kind = "💰 Продаж" if category.type == INCOME else "💸 Витрата"
    lines = [
        f"{kind} №{t.id}",
        "",
        f"🚗 {car_title(car)}",
        category_label(category.name),
        f"📅 {t.operation_date:%d.%m.%Y}",
        f"💵 {tx_amount_text(t)} · курс НБУ {format_rate(t.usd_rate)}",
    ]
    if t.description:
        lines.append(f"📝 {t.description}")
    return "\n".join(lines)


def tx_button_label(t: Transaction, category: Category) -> str:
    """Операція в списку: '10.11.26 · 🔧 Ремонт · 3 800 грн'."""
    amount = f"${format_money(t.amount_usd)}" if t.currency == "USD" else f"{format_money(t.amount_uah)} грн"
    return f"{t.operation_date:%d.%m.%y} · {category_label(category.name)} · {amount}"


def rows(*sizes: int) -> list[int]:
    """Розміри рядків кнопок без нулів — для InlineKeyboardBuilder.adjust."""
    return [size for size in sizes if size > 0]


async def safe_edit(message: Message, text: str, markup=None) -> None:
    """Змінює повідомлення з кнопками. Якщо нічого не змінилося, Telegram повертає помилку — пропускаємо її."""
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


async def cars_overview(tg_user: TgUser):
    """«📋 Мої авто»: картки всіх авто й кнопка для кожного."""
    async with db.session_factory() as session:
        user = await get_db_user(session, tg_user)
        cars = await crud.list_cars(session, user.id)
        summaries = [await crud.car_summary(session, car.id) for car in cars]
        await session.commit()

    if not cars:
        return f"У вас ще немає авто. Додати — {BTN_ADD_CAR}", None

    keyboard = InlineKeyboardBuilder()
    for car, summary in zip(cars, summaries):
        label = f"🚗 {car_title(car)}" + (" · ✅ продано" if summary.sold else "")
        keyboard.button(text=label, callback_data=CarCb(action="show", car_id=car.id))
    keyboard.adjust(1)
    cards = [car_card(car, summary) for car, summary in zip(cars, summaries)]
    text = (
        "📋 Ваші авто\n\n" + "\n\n".join(cards)
        + "\n\nОберіть авто, щоб переглянути, змінити чи видалити його операції:"
    )
    return text, keyboard.as_markup()


async def car_view(tg_user: TgUser, car_id: int):
    """Картка одного авто з кнопкою «Операції». None — авто немає або воно чуже."""
    async with db.session_factory() as session:
        user = await get_db_user(session, tg_user)
        car = await crud.get_car(session, car_id, owner_id=user.id)
        if car is None:
            return None
        summary = await crud.car_summary(session, car.id)
        count = await crud.count_car_transactions(session, car.id)
        await session.commit()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=f"📄 Операції ({count})", callback_data=CarCb(action="ops", car_id=car.id))
    keyboard.button(text="✏️ Змінити авто", callback_data=CarCb(action="edit", car_id=car.id))
    keyboard.button(text="🗑 Видалити авто", callback_data=CarCb(action="del", car_id=car.id))
    keyboard.button(text="⬅️ Усі авто", callback_data=CarCb(action="list"))
    keyboard.adjust(1, 2, 1)
    return car_card(car, summary), keyboard.as_markup()


async def ops_view(tg_user: TgUser, car_id: int, offset: int):
    """Операції авто сторінками по OPS_PAGE_SIZE, нові зверху. None — авто немає або воно чуже."""
    async with db.session_factory() as session:
        user = await get_db_user(session, tg_user)
        car = await crud.get_car(session, car_id, owner_id=user.id)
        if car is None:
            return None
        total = await crud.count_car_transactions(session, car.id)
        # Сторінка могла зникнути (операції видалили) — показуємо останню наявну
        last_page_offset = (max(total, 1) - 1) // OPS_PAGE_SIZE * OPS_PAGE_SIZE
        offset = max(0, min(offset, last_page_offset))
        page = await crud.list_car_transactions(session, car.id, OPS_PAGE_SIZE, offset)
        await session.commit()

    keyboard = InlineKeyboardBuilder()
    for t, category in page:
        keyboard.button(text=tx_button_label(t, category), callback_data=TxCb(action="show", tx_id=t.id))
    nav = 0
    if offset > 0:
        keyboard.button(
            text="⬅️ Новіші",
            callback_data=CarCb(action="ops", car_id=car.id, offset=max(0, offset - OPS_PAGE_SIZE)),
        )
        nav += 1
    if offset + OPS_PAGE_SIZE < total:
        keyboard.button(
            text="Старіші ➡️", callback_data=CarCb(action="ops", car_id=car.id, offset=offset + OPS_PAGE_SIZE)
        )
        nav += 1
    keyboard.button(text="⬅️ До авто", callback_data=CarCb(action="show", car_id=car.id))
    keyboard.adjust(*rows(*[1] * len(page), nav, 1))

    if total == 0:
        text = f"📄 Операції · {car_title(car)}\n\nОперацій ще немає. Додати — {BTN_EXPENSE} або {BTN_SALE}"
    else:
        text = (
            f"📄 Операції · {car_title(car)}\n"
            f"Показано {offset + 1}–{offset + len(page)} з {total}, нові зверху.\n\n"
            "Оберіть операцію, щоб змінити чи видалити її:"
        )
    return text, keyboard.as_markup()


async def load_tx(session, tg_user: TgUser, tx_id: int):
    """Операція користувача з категорією й авто. None — операції немає або вона чужа."""
    user = await get_db_user(session, tg_user)
    t = await crud.get_transaction(session, tx_id, owner_id=user.id)
    if t is None:
        return None
    category = await crud.get_category(session, t.category_id)
    car = await crud.get_car(session, t.car_id)
    return user, t, category, car


def tx_actions_markup(t: Transaction):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✏️ Змінити", callback_data=TxCb(action="edit", tx_id=t.id))
    keyboard.button(text="🗑 Видалити", callback_data=TxCb(action="del", tx_id=t.id))
    keyboard.button(text="⬅️ До операцій", callback_data=CarCb(action="ops", car_id=t.car_id))
    keyboard.adjust(2, 1)
    return keyboard.as_markup()


def tx_edit_markup(t: Transaction, category: Category):
    """Що можна змінити. Категорію продажу не змінюємо — вона в нього одна."""
    fields = [("📅 Дата", "date"), ("💵 Сума", "amount"), ("💱 Валюта", "currency")]
    if category.type == EXPENSE:
        fields.append(("🏷 Категорія", "category"))
    fields += [("📝 Опис", "description"), ("🚗 Авто", "car")]

    keyboard = InlineKeyboardBuilder()
    for text, field in fields:
        keyboard.button(text=text, callback_data=TxCb(action="field", tx_id=t.id, value=field))
    keyboard.button(text="✅ Готово", callback_data=TxCb(action="show", tx_id=t.id))
    keyboard.adjust(*rows(*[2] * (len(fields) // 2), len(fields) % 2, 1))
    return keyboard.as_markup()


async def tx_view(tg_user: TgUser, tx_id: int, header: str | None = None, edit_menu: bool = False):
    """Картка операції: з кнопками дій або (edit_menu) з вибором, що змінити. None — операції немає."""
    async with db.session_factory() as session:
        loaded = await load_tx(session, tg_user, tx_id)
        await session.commit()
    if loaded is None:
        return None
    _, t, category, car = loaded

    text = tx_card(t, category, car)
    if header:
        text = f"{header}\n\n{text}"
    if edit_menu:
        text += (
            "\n\n✏️ Що змінити?\n"
            "Тип (витрата чи продаж) змінити не можна — для цього видаліть операцію і створіть нову."
        )
        return text, tx_edit_markup(t, category)
    return text, tx_actions_markup(t)


async def update_tx(tg_user: TgUser, tx_id: int, **changes) -> str | None:
    """Зберігає зміну через спільну логіку: решта полів — як були. Повертає текст помилки або None."""
    async with db.session_factory() as session:
        loaded = await load_tx(session, tg_user, tx_id)
        if loaded is None:
            return NOT_FOUND_TX
        user, t, _, _ = loaded
        values = {
            "car_id": t.car_id,
            "category_id": t.category_id,
            "operation_date": t.operation_date,
            "amount": t.amount,
            "currency": t.currency,
            "description": t.description,
        }
        values.update(changes)
        try:
            await services.update_transaction(session, tx_id, owner_id=user.id, **values)
        except AppError as error:
            return error.message
        await session.commit()
    logger.info(
        "Змінено операцію transaction_id=%s (%s) від user_id=%s", tx_id, ", ".join(changes), tg_user.id
    )
    return None


def cancel_edit_markup(tx_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✖ Скасувати", callback_data=TxCb(action="cancel", tx_id=tx_id))
    return keyboard.as_markup()


SAVED_HEADER = {
    "operation_date": "✅ Дату змінено",
    "amount": "✅ Суму змінено",
    "currency": "✅ Валюту змінено",
    "category_id": "✅ Категорію змінено",
    "description": "✅ Опис змінено",
    "car_id": "✅ Операцію перенесено на інше авто",
}


async def save_and_show(callback: CallbackQuery, tx_id: int, **changes) -> None:
    """Зміна з кнопки: зберегти й показати оновлену операцію з меню змін."""
    error = await update_tx(callback.from_user, tx_id, **changes)
    if error:
        await callback.answer(error, show_alert=True)
        return
    view = await tx_view(callback.from_user, tx_id, header=SAVED_HEADER[next(iter(changes))], edit_menu=True)
    if view is None:
        await callback.answer(NOT_FOUND_TX, show_alert=True)
        return
    await safe_edit(callback.message, *view)
    await callback.answer("Збережено")


async def answer_saved(message: Message, tx_id: int, field: str) -> None:
    """Зміна з тексту: нове повідомлення з оновленою операцією й меню змін."""
    view = await tx_view(message.from_user, tx_id, header=SAVED_HEADER[field], edit_menu=True)
    if view is None:
        await message.answer(NOT_FOUND_TX)
        return
    await message.answer(view[0], reply_markup=view[1])


# --- Авто й список операцій ---


@dp.callback_query(CarCb.filter(F.action == "list"))
async def cars_list_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await cars_overview(callback.from_user)
    await safe_edit(callback.message, text, markup)
    await callback.answer()


@dp.callback_query(CarCb.filter(F.action == "show"))
async def car_show_button(callback: CallbackQuery, callback_data: CarCb, state: FSMContext) -> None:
    await state.clear()
    view = await car_view(callback.from_user, callback_data.car_id)
    if view is None:
        await callback.answer(NOT_FOUND_CAR, show_alert=True)
        return
    await safe_edit(callback.message, *view)
    await callback.answer()


@dp.callback_query(CarCb.filter(F.action == "ops"))
async def car_ops_button(callback: CallbackQuery, callback_data: CarCb, state: FSMContext) -> None:
    await state.clear()
    view = await ops_view(callback.from_user, callback_data.car_id, callback_data.offset)
    if view is None:
        await callback.answer(NOT_FOUND_CAR, show_alert=True)
        return
    await safe_edit(callback.message, *view)
    await callback.answer()


# --- Авто: зміна й видалення ---


class EditCarForm(StatesGroup):
    """Зміна авто: бот чекає нове значення текстом."""

    entering_name = State()
    entering_year = State()
    entering_vin = State()


def plural_uk(n: int, one: str, few: str, many: str) -> str:
    """1 операцію, 3 операції, 5 операцій (11–14 — завжди «many»)."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


CAR_SAVED_HEADER = {
    "name": "✅ Марку й модель змінено",
    "year": "✅ Рік змінено",
    "vin": "✅ VIN змінено",
}


async def car_edit_view(tg_user: TgUser, car_id: int, header: str | None = None):
    """Картка авто з вибором, що змінити. None — авто немає або воно чуже."""
    async with db.session_factory() as session:
        user = await get_db_user(session, tg_user)
        car = await crud.get_car(session, car_id, owner_id=user.id)
        if car is None:
            return None
        summary = await crud.car_summary(session, car.id)
        await session.commit()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🏷 Марка й модель", callback_data=CarCb(action="field", car_id=car_id, value="name"))
    keyboard.button(text="📅 Рік", callback_data=CarCb(action="field", car_id=car_id, value="year"))
    keyboard.button(text="🔖 VIN", callback_data=CarCb(action="field", car_id=car_id, value="vin"))
    keyboard.button(text="✅ Готово", callback_data=CarCb(action="show", car_id=car_id))
    keyboard.adjust(1, 2, 1)

    text = f"{car_card(car, summary)}\n\n✏️ Що змінити в авто?\nВласника авто можна змінити на сайті."
    if header:
        text = f"{header}\n\n{text}"
    return text, keyboard.as_markup()


async def update_car_fields(tg_user: TgUser, car_id: int, **changes) -> str | None:
    """Зберігає зміну авто через спільну логіку: решта полів — як були. Повертає текст помилки або None."""
    async with db.session_factory() as session:
        user = await get_db_user(session, tg_user)
        car = await crud.get_car(session, car_id, owner_id=user.id)
        if car is None:
            return NOT_FOUND_CAR
        values = {"brand": car.brand, "model": car.model, "year": car.year, "vin": car.vin}
        values.update(changes)
        try:
            await services.update_car(session, car_id, owner_id=user.id, **values)
        except AppError as error:
            return error.message
        await session.commit()
    logger.info("Змінено авто car_id=%s (%s) від user_id=%s", car_id, ", ".join(changes), tg_user.id)
    return None


def cancel_car_edit_markup(car_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✖ Скасувати", callback_data=CarCb(action="cancel", car_id=car_id))
    return keyboard.as_markup()


async def answer_car_saved(message: Message, car_id: int, field: str) -> None:
    view = await car_edit_view(message.from_user, car_id, header=CAR_SAVED_HEADER[field])
    if view is None:
        await message.answer(NOT_FOUND_CAR)
        return
    await message.answer(view[0], reply_markup=view[1])


@dp.callback_query(CarCb.filter(F.action.in_({"edit", "cancel"})))
async def car_edit_button(callback: CallbackQuery, callback_data: CarCb, state: FSMContext) -> None:
    """Меню «що змінити в авто» (cancel — скасувати введення тексту)."""
    await state.clear()
    view = await car_edit_view(callback.from_user, callback_data.car_id)
    if view is None:
        await callback.answer(NOT_FOUND_CAR, show_alert=True)
        return
    await safe_edit(callback.message, *view)
    await callback.answer()


CAR_FIELD_PROMPTS = {
    "name": (
        EditCarForm.entering_name,
        "🏷 Надішліть марку й модель, без року, наприклад:\nMercedes-Benz G 500\n\n"
        "Марка — перше слово (якщо з двох слів — через дефіс: Land-Rover).",
    ),
    "year": (EditCarForm.entering_year, "📅 Надішліть рік випуску, наприклад 2018"),
    "vin": (
        EditCarForm.entering_vin,
        "🔖 Надішліть VIN — 17 символів: латинські літери (без I, O, Q) і цифри.\n"
        "Щоб прибрати VIN — надішліть «-».",
    ),
}


@dp.callback_query(CarCb.filter(F.action == "field"))
async def car_field_button(callback: CallbackQuery, callback_data: CarCb, state: FSMContext) -> None:
    """Вибрано поле авто — просимо надіслати нове значення текстом."""
    if callback_data.value not in CAR_FIELD_PROMPTS:
        await callback.answer("Це поле змінити не можна.", show_alert=True)
        return
    view = await car_view(callback.from_user, callback_data.car_id)
    if view is None:
        await callback.answer(NOT_FOUND_CAR, show_alert=True)
        return
    form_state, prompt = CAR_FIELD_PROMPTS[callback_data.value]
    await state.set_state(form_state)
    await state.update_data(car_id=callback_data.car_id)
    await safe_edit(callback.message, f"{view[0]}\n\n{prompt}", cancel_car_edit_markup(callback_data.car_id))
    await callback.answer()


async def save_car_field(message: Message, state: FSMContext, field: str, **changes) -> None:
    """Спільне для тексту: зберегти; при помилці — лишитися на кроці, щоб можна було виправити."""
    car_id = (await state.get_data())["car_id"]
    error = await update_car_fields(message.from_user, car_id, **changes)
    if error:
        await message.answer(f"⚠️ {error}", reply_markup=cancel_car_edit_markup(car_id))
        return
    await state.clear()
    await answer_car_saved(message, car_id, field)


@dp.message(EditCarForm.entering_name, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def car_enter_name(message: Message, state: FSMContext) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        car_id = (await state.get_data())["car_id"]
        await message.answer(
            "Напишіть марку й модель через пробіл, наприклад: BMW X5",
            reply_markup=cancel_car_edit_markup(car_id),
        )
        return
    await save_car_field(message, state, "name", brand=parts[0], model=" ".join(parts[1:]))


@dp.message(EditCarForm.entering_year, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def car_enter_year(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not (text.isdigit() and len(text) == 4):
        car_id = (await state.get_data())["car_id"]
        await message.answer("Напишіть рік чотирма цифрами, наприклад 2018", reply_markup=cancel_car_edit_markup(car_id))
        return
    await save_car_field(message, state, "year", year=int(text))


@dp.message(EditCarForm.entering_vin, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def car_enter_vin(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    await save_car_field(message, state, "vin", vin=None if text == "-" else text)


@dp.callback_query(CarCb.filter(F.action == "del"))
async def car_delete_button(callback: CallbackQuery, callback_data: CarCb, state: FSMContext) -> None:
    """Підтвердження видалення авто: показуємо, скільки операцій зникне разом з ним."""
    await state.clear()
    async with db.session_factory() as session:
        user = await get_db_user(session, callback.from_user)
        car = await crud.get_car(session, callback_data.car_id, owner_id=user.id)
        if car is None:
            await callback.answer(NOT_FOUND_CAR, show_alert=True)
            return
        summary = await crud.car_summary(session, car.id)
        count = await crud.count_car_transactions(session, car.id)
        await session.commit()

    lines = ["🗑 Видалити авто?", "", car_card(car, summary), ""]
    if count:
        what = "витрати й продаж" if summary.sold else "усі витрати по ньому"
        lines.append(f"⚠️ Разом з авто буде видалено {plural_uk(count, 'операцію', 'операції', 'операцій')} — {what}.")
        if summary.sold:
            lines.append("Прибуток по цьому авто теж зникне.")
    else:
        lines.append("Операцій по цьому авто немає.")
    lines.append("Авто зникне і з бота, і з сайту. Скасувати це неможливо.")

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🗑 Так, видалити авто", callback_data=CarCb(action="delok", car_id=car.id))
    keyboard.button(text="✖ Скасувати", callback_data=CarCb(action="show", car_id=car.id))
    keyboard.adjust(1)
    await safe_edit(callback.message, "\n".join(lines), keyboard.as_markup())
    await callback.answer()


@dp.callback_query(CarCb.filter(F.action == "delok"))
async def car_delete_confirmed(callback: CallbackQuery, callback_data: CarCb) -> None:
    async with db.session_factory() as session:
        user = await get_db_user(session, callback.from_user)
        car = await crud.get_car(session, callback_data.car_id, owner_id=user.id)
        if car is None:
            await callback.answer(NOT_FOUND_CAR, show_alert=True)
            return
        title = car_title(car)
        try:
            removed = await services.delete_car(session, car.id, owner_id=user.id)
        except AppError as error:
            await callback.answer(error.message, show_alert=True)
            return
        await session.commit()

    logger.info(
        "Видалено авто car_id=%s разом з %s операціями від user_id=%s",
        callback_data.car_id, removed, callback.from_user.id,
    )
    text = f"✅ Авто {title} видалено"
    text += f" разом з {plural_uk(removed, 'операцією', 'операціями', 'операціями')}." if removed else "."
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⬅️ Усі авто", callback_data=CarCb(action="list"))
    await safe_edit(callback.message, text, keyboard.as_markup())
    await callback.answer("Видалено")


# --- Операція: перегляд і меню змін ---


@dp.callback_query(TxCb.filter(F.action.in_({"show", "edit", "cancel"})))
async def tx_show_button(callback: CallbackQuery, callback_data: TxCb, state: FSMContext) -> None:
    """show — картка з діями; edit / cancel — меню «що змінити» (cancel — скасувати введення тексту)."""
    await state.clear()
    view = await tx_view(callback.from_user, callback_data.tx_id, edit_menu=callback_data.action != "show")
    if view is None:
        await callback.answer(NOT_FOUND_TX, show_alert=True)
        return
    await safe_edit(callback.message, *view)
    await callback.answer()


@dp.callback_query(TxCb.filter(F.action == "field"))
async def tx_field_button(callback: CallbackQuery, callback_data: TxCb, state: FSMContext) -> None:
    """Вибрано поле для зміни — показуємо варіанти або просимо надіслати нове значення."""
    tx_id, field = callback_data.tx_id, callback_data.value
    async with db.session_factory() as session:
        loaded = await load_tx(session, callback.from_user, tx_id)
        if loaded is None:
            await callback.answer(NOT_FOUND_TX, show_alert=True)
            return
        user, t, category, car = loaded
        categories = await crud.list_categories(session, EXPENSE) if field == "category" else []
        other_cars = []
        if field == "car":
            for other in await crud.list_cars(session, user.id):
                # Продаж можна перенести лише на непродане авто
                if other.id != t.car_id and not (
                    category.type == INCOME and await crud.car_is_sold(session, other.id)
                ):
                    other_cars.append(other)
        await session.commit()

    card = tx_card(t, category, car)
    back = TxCb(action="edit", tx_id=tx_id)
    keyboard = InlineKeyboardBuilder()

    if field == "date":
        keyboard.button(text="📅 Сьогодні", callback_data=TxCb(action="date", tx_id=tx_id, value="today"))
        keyboard.button(text="📅 Вчора", callback_data=TxCb(action="date", tx_id=tx_id, value="yesterday"))
        keyboard.button(text="✏️ Інша дата", callback_data=TxCb(action="date", tx_id=tx_id, value="other"))
        keyboard.button(text="⬅️ Назад", callback_data=back)
        keyboard.adjust(2, 1, 1)
        prompt = "📅 Нова дата операції (курс НБУ буде взято на нову дату):"
    elif field == "amount":
        await state.set_state(EditTxForm.entering_amount)
        await state.update_data(tx_id=tx_id)
        await safe_edit(
            callback.message,
            f"{card}\n\n💵 Надішліть нову суму {CURRENCY_IN[t.currency]} — лише число, "
            "наприклад 450 або 1250,50",
            cancel_edit_markup(tx_id),
        )
        await callback.answer()
        return
    elif field == "currency":
        for code, text in CURRENCY_BUTTONS.items():
            mark = " ✓" if code == t.currency else ""
            keyboard.button(text=text + mark, callback_data=TxCb(action="cur", tx_id=tx_id, value=code))
        keyboard.button(text="⬅️ Назад", callback_data=back)
        keyboard.adjust(2, 1)
        prompt = (
            f"💱 У якій валюті сума {format_money(t.amount)}? Число лишається, змінюється лише валюта — "
            "друга валюта перерахується за курсом НБУ."
        )
    elif field == "category" and category.type == EXPENSE:
        for c in categories:
            mark = " ✓" if c.id == t.category_id else ""
            keyboard.button(text=category_label(c.name) + mark, callback_data=TxCb(action="cat", tx_id=tx_id, value=str(c.id)))
        keyboard.button(text="⬅️ Назад", callback_data=back)
        keyboard.adjust(*rows(*[2] * (len(categories) // 2), len(categories) % 2, 1))
        prompt = "🏷 Нова категорія:"
    elif field == "description":
        await state.set_state(EditTxForm.entering_description)
        await state.update_data(tx_id=tx_id)
        await safe_edit(
            callback.message,
            f"{card}\n\n📝 Надішліть новий опис. Щоб прибрати опис — надішліть «-».",
            cancel_edit_markup(tx_id),
        )
        await callback.answer()
        return
    elif field == "car":
        if not other_cars:
            note = "непроданого авто" if category.type == INCOME else "авто"
            await callback.answer(f"Немає іншого {note}, на яке можна перенести операцію.", show_alert=True)
            return
        for other in other_cars:
            keyboard.button(text=f"🚗 {car_title(other)}", callback_data=TxCb(action="car", tx_id=tx_id, value=str(other.id)))
        keyboard.button(text="⬅️ Назад", callback_data=back)
        keyboard.adjust(1)
        prompt = "🚗 На яке авто перенести операцію?"
    else:
        await callback.answer("Це поле змінити не можна.", show_alert=True)
        return

    await safe_edit(callback.message, f"{card}\n\n{prompt}", keyboard.as_markup())
    await callback.answer()


# --- Зміна з кнопок: дата, валюта, категорія, авто ---


@dp.callback_query(TxCb.filter(F.action == "date"))
async def tx_date_button(callback: CallbackQuery, callback_data: TxCb, state: FSMContext) -> None:
    tx_id = callback_data.tx_id
    if callback_data.value == "other":
        await state.set_state(EditTxForm.entering_date)
        await state.update_data(tx_id=tx_id)
        await safe_edit(callback.message, f"✏️ Нова дата операції.\n\n{DATE_HELP}", cancel_edit_markup(tx_id))
        await callback.answer()
        return
    day = kyiv_today() if callback_data.value == "today" else kyiv_today() - timedelta(days=1)
    await save_and_show(callback, tx_id, operation_date=day)


@dp.callback_query(TxCb.filter(F.action == "cur"))
async def tx_currency_button(callback: CallbackQuery, callback_data: TxCb) -> None:
    await save_and_show(callback, callback_data.tx_id, currency=callback_data.value)


@dp.callback_query(TxCb.filter(F.action == "cat"))
async def tx_category_button(callback: CallbackQuery, callback_data: TxCb) -> None:
    await save_and_show(callback, callback_data.tx_id, category_id=int(callback_data.value))


@dp.callback_query(TxCb.filter(F.action == "car"))
async def tx_car_button(callback: CallbackQuery, callback_data: TxCb) -> None:
    await save_and_show(callback, callback_data.tx_id, car_id=int(callback_data.value))


# --- Зміна з тексту: дата, сума, опис ---

# Текст із кнопок меню чи команда — не нове значення: їх обробляють інші обробники
EDIT_TEXT = (F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))


@dp.message(EditTxForm.entering_date, *EDIT_TEXT)
async def tx_enter_date(message: Message, state: FSMContext) -> None:
    tx_id = (await state.get_data())["tx_id"]
    parsed = parse_date(message.text)
    if isinstance(parsed, str):
        await message.answer(parsed, reply_markup=cancel_edit_markup(tx_id))
        return
    error = await update_tx(message.from_user, tx_id, operation_date=parsed)
    if error:
        await message.answer(f"⚠️ {error}", reply_markup=cancel_edit_markup(tx_id))
        return
    await state.clear()
    await answer_saved(message, tx_id, "operation_date")


@dp.message(EditTxForm.entering_amount, *EDIT_TEXT)
async def tx_enter_amount(message: Message, state: FSMContext) -> None:
    tx_id = (await state.get_data())["tx_id"]
    text = message.text.strip()
    if not AMOUNT_RE.match(text):
        await message.answer(
            "Напишіть лише число, без пробілів: 450 або 1250,50", reply_markup=cancel_edit_markup(tx_id)
        )
        return
    try:
        amount = rules.check_amount(Decimal(text.replace(",", ".")))
    except ValidationError as error:
        await message.answer(error.message, reply_markup=cancel_edit_markup(tx_id))
        return
    error = await update_tx(message.from_user, tx_id, amount=amount)
    if error:
        await message.answer(f"⚠️ {error}", reply_markup=cancel_edit_markup(tx_id))
        return
    await state.clear()
    await answer_saved(message, tx_id, "amount")


@dp.message(EditTxForm.entering_description, *EDIT_TEXT)
async def tx_enter_description(message: Message, state: FSMContext) -> None:
    tx_id = (await state.get_data())["tx_id"]
    text = message.text.strip()
    try:
        description = None if text == "-" else rules.check_description(text)
    except ValidationError as error:
        await message.answer(error.message, reply_markup=cancel_edit_markup(tx_id))
        return
    error = await update_tx(message.from_user, tx_id, description=description)
    if error:
        await message.answer(f"⚠️ {error}", reply_markup=cancel_edit_markup(tx_id))
        return
    await state.clear()
    await answer_saved(message, tx_id, "description")


# --- Видалення з підтвердженням ---


@dp.callback_query(TxCb.filter(F.action == "del"))
async def tx_delete_button(callback: CallbackQuery, callback_data: TxCb, state: FSMContext) -> None:
    await state.clear()
    async with db.session_factory() as session:
        loaded = await load_tx(session, callback.from_user, callback_data.tx_id)
        await session.commit()
    if loaded is None:
        await callback.answer(NOT_FOUND_TX, show_alert=True)
        return
    _, t, category, car = loaded

    lines = ["🗑 Видалити операцію?", "", tx_card(t, category, car), ""]
    if category.type == INCOME:
        lines.append("⚠️ Це продаж. Після видалення авто стане непроданим, а прибуток зникне.")
    lines.append("Операцію буде видалено з бази назавжди.")
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🗑 Так, видалити", callback_data=TxCb(action="delok", tx_id=t.id))
    keyboard.button(text="✖ Скасувати", callback_data=TxCb(action="show", tx_id=t.id))
    keyboard.adjust(2)
    await safe_edit(callback.message, "\n".join(lines), keyboard.as_markup())
    await callback.answer()


@dp.callback_query(TxCb.filter(F.action == "delok"))
async def tx_delete_confirmed(callback: CallbackQuery, callback_data: TxCb) -> None:
    async with db.session_factory() as session:
        loaded = await load_tx(session, callback.from_user, callback_data.tx_id)
        if loaded is None:
            await callback.answer(NOT_FOUND_TX, show_alert=True)
            return
        user, t, category, car = loaded
        try:
            await services.delete_transaction(session, t.id, owner_id=user.id)
        except AppError as error:
            await callback.answer(error.message, show_alert=True)
            return
        summary = await crud.car_summary(session, car.id)
        await session.commit()

    logger.info("Видалено операцію transaction_id=%s від user_id=%s", t.id, callback.from_user.id)
    done = "✅ Продаж видалено — авто знову в роботі." if category.type == INCOME else "✅ Операцію видалено."
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📄 До операцій авто", callback_data=CarCb(action="ops", car_id=car.id))
    keyboard.button(text="⬅️ Усі авто", callback_data=CarCb(action="list"))
    keyboard.adjust(1)
    await safe_edit(
        callback.message, f"{done}\n\n📊 Підсумок по авто\n{car_card(car, summary)}", keyboard.as_markup()
    )
    await callback.answer("Видалено")


@dp.callback_query()
async def outdated_button(callback: CallbackQuery) -> None:
    """Кнопка, яку не впізнав жоден обробник: наприклад, зі старого повідомлення після оновлення бота."""
    await callback.answer("Ця кнопка вже не діє. Відкрийте «📋 Мої авто» ще раз.", show_alert=True)


@dp.message()
async def unknown_message(message: Message) -> None:
    """Усе, що не підійшло жодному обробнику вище: бот не мовчить, а підказує."""
    await message.answer(f"🤔 Не зрозумів повідомлення.\n\n{COMMANDS_TEXT}", reply_markup=main_menu())


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
    await db.check_db()

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
