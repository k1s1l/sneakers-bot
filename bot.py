"""
Telegram-бот "Каталог кросівок" — діалоговий режим на Claude API.

Claude веде живу розмову з клієнтом: відповідає на будь-які повідомлення,
сам розпитує деталі замовлення по черзі (модель → розмір → ім'я → контакт)
і сам вирішує, коли всі дані зібрані — тоді бот автоматично надсилає
готову заявку власнику в Telegram.

Запуск:
    1. pip install -r requirements.txt
    2. Задай змінні оточення: BOT_TOKEN, OWNER_CHAT_ID, ANTHROPIC_API_KEY
    3. Поклади фото товарів у папку photos/ з такими іменами:
         photos/adidas_handball_spezial.jpg
         photos/nike_vomero_5.jpg
         photos/new_balance_530.jpg
         photos/asics_gel_kayano_14.jpg
         photos/salomon_xt6_gtx.jpg
    4. python bot.py
"""

import asyncio
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from ai import get_response

# ---------------------------------------------------------------------------
# НАЛАШТУВАННЯ
# ---------------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВ_СЮДИ_СВІЙ_ТОКЕН")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))

MIN_SIZE = 36
MAX_SIZE = 47
MAX_HISTORY = 20  # скільки останніх реплік пам'ятає бот в одному чаті

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

# Історія діалогу по кожному чату (in-memory; обнуляється при перезапуску бота)
histories: dict[int, list[dict]] = {}

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


def catalog_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=item["name"], callback_data=f"view:{key}")]
        for key, item in PRODUCTS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# ДОПОМІЖНІ ФУНКЦІЇ
# ---------------------------------------------------------------------------

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
        await message.answer(caption)


async def process_user_text(message: Message, bot: Bot, text: str | None = None) -> None:
    """Пропускає повідомлення через Claude і, якщо зібрано замовлення, шле його власнику."""
    chat_id = message.chat.id
    user_text = text if text is not None else (message.text or "")

    history = histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    reply_text, order = await get_response(history, PRODUCTS, MIN_SIZE, MAX_SIZE)
    await message.answer(reply_text)

    if len(history) > MAX_HISTORY:
        del history[: len(history) - MAX_HISTORY]

    if order:
        await notify_owner_about_order(bot, message, order)


async def notify_owner_about_order(bot: Bot, message: Message, order: dict) -> None:
    model_key = order.get("model_key")
    size = order.get("size")
    name = order.get("name")
    contact = order.get("contact")

    product = PRODUCTS.get(model_key)
    model_name = product["name"] if product else str(model_key)
    price = product["price"] if product else "—"

    order_text = (
        "📝 Нове замовлення!\n"
        f"Модель: {model_name}\n"
        f"Ціна: {price}\n"
        f"Розмір: {size}\n"
        f"Ім'я: {name}\n"
        f"Контакт: {contact}\n"
        f"Клієнт: @{message.from_user.username or message.from_user.id}"
    )
    if OWNER_CHAT_ID:
        await bot.send_message(OWNER_CHAT_ID, order_text)


# ---------------------------------------------------------------------------
# РОУТЕР
# ---------------------------------------------------------------------------

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    histories[message.chat.id] = []
    await message.answer(
        "Привіт! Це каталог кросівок 👟 Питай про що завгодно — модель, розмір, "
        "чи просто напиши, що шукаєш, і я допоможу оформити замовлення.",
        reply_markup=main_menu,
    )


@router.message(F.text == "🛍 Каталог")
async def show_catalog(message: Message) -> None:
    await message.answer("Ось наші моделі:", reply_markup=catalog_keyboard())


@router.callback_query(F.data.startswith("view:"))
async def view_product(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 1)[1]
    if key in PRODUCTS:
        await send_product_card(callback.message, key)
    await callback.answer()


@router.message(F.text == "📏 Розміри")
async def show_sizes(message: Message) -> None:
    await message.answer(f"Розміри {MIN_SIZE}–{MAX_SIZE} доступні для всіх моделей 👟")


@router.message(F.text == "💬 Задати питання")
async def ask_hint(message: Message) -> None:
    await message.answer("Просто напиши своє питання прямо тут — відповім одразу 🙂")


@router.message(F.text == "📝 Замовити")
async def order_button(message: Message, bot: Bot) -> None:
    await process_user_text(message, bot, text="Я хочу оформити замовлення")


@router.message(F.text)
async def free_text(message: Message, bot: Bot) -> None:
    await process_user_text(message, bot)


# ---------------------------------------------------------------------------
# ЗАПУСК
# ---------------------------------------------------------------------------

async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
