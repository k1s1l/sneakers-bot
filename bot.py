"""
Telegram-бот "Каталог кросівок" з інтеграцією Claude API.

Claude використовується для:
  - розпізнавання моделі/розміру у довільному тексті клієнта (без вибору з меню);
  - генерації короткої відповіді на вільні питання клієнта (💬 Задати питання).

Запуск:
    1. pip install -r requirements.txt
    2. Встав свій токен бота у BOT_TOKEN нижче (або задай змінну оточення BOT_TOKEN)
    3. Встав свій Telegram chat_id у OWNER_CHAT_ID (щоб отримувати заявки)
    4. Задай змінну оточення ANTHROPIC_API_KEY зі своїм ключем Claude API
    5. Поклади фото товарів у папку photos/ з такими іменами:
         photos/adidas_handball_spezial.jpg
         photos/nike_vomero_5.jpg
         photos/new_balance_530.jpg
         photos/asics_gel_kayano_14.jpg
         photos/salomon_xt6_gtx.jpg
    6. python bot.py
"""

import asyncio
import os
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from ai import analyze_message, build_system_prompt

# ---------------------------------------------------------------------------
# НАЛАШТУВАННЯ
# ---------------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВ_СЮДИ_СВІЙ_ТОКЕН")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))  # твій Telegram chat_id

MIN_SIZE = 36
MAX_SIZE = 47

NO_SIZE_TEXT = "На жаль, такого розміру зараз немає 😔"
NO_MODEL_TEXT = "На жаль, такої моделі зараз немає в наявності."

# ---------------------------------------------------------------------------
# КАТАЛОГ ТОВАРІВ
# ---------------------------------------------------------------------------

PRODUCTS = {
    "adidas_spezial": {
        "name": "adidas Handball Spezial",
        "price": "4200 грн",
        "photo": "photos/adidas_handball_spezial.jpg",
    },
    "nike_vomero5": {
        "name": "Nike Vomero 5",
        "price": "5800 грн",
        "photo": "photos/nike_vomero_5.jpg",
    },
    "nb_530": {
        "name": "New Balance 530",
        "price": "3600 грн",
        "photo": "photos/new_balance_530.jpg",
    },
    "asics_kayano14": {
        "name": "ASICS GEL-Kayano 14",
        "price": "4900 грн",
        "photo": "photos/asics_gel_kayano_14.jpg",
    },
    "salomon_xt6": {
        "name": "Salomon XT-6 GTX",
        "price": "7200 грн",
        "photo": "photos/salomon_xt6_gtx.jpg",
    },
}

# ---------------------------------------------------------------------------
# КЛАВІАТУРИ
# ---------------------------------------------------------------------------

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="📏 Розміри")],
        [KeyboardButton(text="💬 Задати питання"), KeyboardButton(text="📝 Замовити")],
    ],
    resize_keyboard=True,
)


def catalog_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """Інлайн-список моделей. prefix розрізняє звичайний перегляд і замовлення."""
    rows = [
        [InlineKeyboardButton(text=item["name"], callback_data=f"{prefix}:{key}")]
        for key, item in PRODUCTS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# СТАНИ (FSM)
# ---------------------------------------------------------------------------

class SizeCheck(StatesGroup):
    waiting_size = State()


class Question(StatesGroup):
    waiting_question = State()


class Order(StatesGroup):
    choosing_model = State()
    choosing_size = State()
    entering_name = State()
    entering_contact = State()


# ---------------------------------------------------------------------------
# ДОПОМІЖНІ ФУНКЦІЇ
# ---------------------------------------------------------------------------

def find_product_by_text(text: str) -> str | None:
    """Шукає модель у каталозі за довільним текстом клієнта. Повертає ключ або None."""
    text_low = text.lower()
    for key, item in PRODUCTS.items():
        if item["name"].lower() in text_low or text_low in item["name"].lower():
            return key
    return None


def extract_size(text: str) -> int | None:
    """Дістає число-розмір з тексту, якщо воно є (проста регулярка, без AI)."""
    match = re.search(r"\b\d{2}\b", text)
    return int(match.group()) if match else None


SYSTEM_PROMPT = build_system_prompt(PRODUCTS, MIN_SIZE, MAX_SIZE)


async def send_product_card(message: Message, key: str) -> None:
    item = PRODUCTS[key]
    caption = (
        f"<b>{item['name']}</b>\n"
        f"Ціна: {item['price']}\n"
        f"Доступні розміри: {MIN_SIZE}–{MAX_SIZE}"
    )
    photo_path = item["photo"]
    if os.path.exists(photo_path):
        await message.answer_photo(FSInputFile(photo_path), caption=caption)
    else:
        # Якщо фото ще не додане у папку photos/ — надсилаємо просто текст
        await message.answer(caption)


# ---------------------------------------------------------------------------
# РОУТЕР
# ---------------------------------------------------------------------------

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привіт! Це каталог кросівок 👟\nОбери пункт меню нижче:",
        reply_markup=main_menu,
    )


@router.message(F.text == "🛍 Каталог")
async def show_catalog(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ось наші моделі:", reply_markup=catalog_keyboard("view"))


@router.callback_query(F.data.startswith("view:"))
async def view_product(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in PRODUCTS:
        await callback.message.answer(NO_MODEL_TEXT)
    else:
        await send_product_card(callback.message, key)
    await callback.answer()


@router.message(F.text == "📏 Розміри")
async def ask_size(message: Message, state: FSMContext) -> None:
    await state.set_state(SizeCheck.waiting_size)
    await message.answer(f"Який розмір тебе цікавить? (діапазон {MIN_SIZE}–{MAX_SIZE})")


@router.message(SizeCheck.waiting_size)
async def check_size(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    size = extract_size(text)
    if size is None:
        # Якщо цифрами не вдалось (наприклад "сорок другий") — пробуємо через Claude
        result = await analyze_message(text, SYSTEM_PROMPT)
        size = result.get("size")
    await state.clear()
    if size is None:
        await message.answer("Напиши, будь ласка, розмір цифрами, наприклад 42.")
        return
    if MIN_SIZE <= size <= MAX_SIZE:
        await message.answer(f"Так, розмір {size} доступний для всіх моделей у каталозі 👍")
    else:
        await message.answer(NO_SIZE_TEXT)


@router.message(F.text == "💬 Задати питання")
async def ask_question_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Question.waiting_question)
    await message.answer("Напиши своє питання, і ми відповімо найближчим часом.")


@router.message(Question.waiting_question)
async def forward_question(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    result = await analyze_message(message.text or "", SYSTEM_PROMPT)
    answer = result.get("answer") or "Дякую за питання! Уточню це особисто і скоро відповім."
    await message.answer(answer, reply_markup=main_menu)
    if OWNER_CHAT_ID:
        await bot.send_message(
            OWNER_CHAT_ID,
            f"💬 Питання від @{message.from_user.username or message.from_user.id}:\n"
            f"{message.text}\n\nВідповідь бота (Claude): {answer}",
        )


# ---------------------- ОФОРМЛЕННЯ ЗАМОВЛЕННЯ ----------------------

@router.message(F.text == "📝 Замовити")
async def order_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Order.choosing_model)
    await message.answer("Обери модель для замовлення:", reply_markup=catalog_keyboard("order"))


@router.callback_query(Order.choosing_model, F.data.startswith("order:"))
async def order_choose_model(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in PRODUCTS:
        await callback.message.answer(NO_MODEL_TEXT)
        await callback.answer()
        return
    await state.update_data(model_key=key)
    await state.set_state(Order.choosing_size)
    await callback.message.answer(f"Який розмір потрібен? ({MIN_SIZE}–{MAX_SIZE})")
    await callback.answer()


@router.message(Order.choosing_size)
async def order_choose_size(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    size = extract_size(text)
    if size is None:
        result = await analyze_message(text, SYSTEM_PROMPT)
        size = result.get("size")
    if size is None:
        await message.answer("Напиши розмір цифрами, наприклад 42.")
        return
    if not (MIN_SIZE <= size <= MAX_SIZE):
        await message.answer(NO_SIZE_TEXT)
        return
    await state.update_data(size=size)
    await state.set_state(Order.entering_name)
    await message.answer("Як тебе звати?")


@router.message(Order.entering_name)
async def order_enter_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(Order.entering_contact)
    await message.answer("Залиш номер телефону або Telegram для зв'язку:")


@router.message(Order.entering_contact)
async def order_enter_contact(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    model_name = PRODUCTS[data["model_key"]]["name"]
    price = PRODUCTS[data["model_key"]]["price"]
    size = data["size"]
    name = data["name"]
    contact = message.text
    await state.clear()

    order_text = (
        "📝 Нове замовлення!\n"
        f"Модель: {model_name}\n"
        f"Ціна: {price}\n"
        f"Розмір: {size}\n"
        f"Ім'я: {name}\n"
        f"Контакт: {contact}"
    )
    if OWNER_CHAT_ID:
        await bot.send_message(OWNER_CHAT_ID, order_text)

    await message.answer(
        "Дякуємо за замовлення! Ми зв'яжемося з тобою найближчим часом 🙌",
        reply_markup=main_menu,
    )


# ---------------------- ВІЛЬНІ ЗАПИТИ (без меню, через Claude) ----------------------

@router.message(F.text)
async def free_text(message: Message, bot: Bot) -> None:
    text = message.text or ""

    # Спершу проста перевірка регуляркою (швидко, без звернення до API)
    quick_size = extract_size(text)
    quick_model = find_product_by_text(text)

    if quick_size is not None and quick_model is None:
        if MIN_SIZE <= quick_size <= MAX_SIZE:
            await message.answer(f"Так, розмір {quick_size} є в наявності для всіх моделей 👍")
        else:
            await message.answer(NO_SIZE_TEXT)
        return

    if quick_model is not None:
        await send_product_card(message, quick_model)
        return

    # Якщо просте зіставлення не спрацювало — просимо Claude розпізнати запит
    result = await analyze_message(text, SYSTEM_PROMPT)
    intent = result.get("intent")

    if intent == "size_query" and result.get("size") is not None:
        size = result["size"]
        if MIN_SIZE <= size <= MAX_SIZE:
            await message.answer(f"Так, розмір {size} є в наявності для всіх моделей 👍")
        else:
            await message.answer(NO_SIZE_TEXT)
        return

    if intent == "model_query":
        key = result.get("model_key")
        if key in PRODUCTS:
            await send_product_card(message, key)
        else:
            await message.answer(NO_MODEL_TEXT)
        return

    if intent == "question":
        answer = result.get("answer") or "Дякую за питання! Уточню це особисто і скоро відповім."
        await message.answer(answer)
        if OWNER_CHAT_ID:
            await bot.send_message(
                OWNER_CHAT_ID,
                f"💬 Питання від @{message.from_user.username or message.from_user.id}:\n"
                f"{text}\n\nВідповідь бота (Claude): {answer}",
            )
        return

    await message.answer("Не зовсім зрозумів запит 🙂 Скористайся меню нижче.", reply_markup=main_menu)


# ---------------------------------------------------------------------------
# ЗАПУСК
# ---------------------------------------------------------------------------

async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
