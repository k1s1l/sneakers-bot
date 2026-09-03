"""
Інтеграція з Claude API — діалоговий режим.

На відміну від простого класифікатора, тут Claude веде повноцінну розмову
з клієнтом (пам'ятає історію в межах чату) і сам вирішує:
  - коли просто підтримати розмову ("привіт", "як справи");
  - коли розповісти про каталог / ціни / розміри;
  - коли клієнт хоче оформити замовлення — тоді Claude поступово запитує
    потрібні дані (модель, розмір, ім'я, контакт) і, зібравши все,
    викликає інструмент submit_order.

Потребує змінну оточення ANTHROPIC_API_KEY.
"""

from typing import Any

from anthropic import AsyncAnthropic

MODEL = "claude-haiku-4-5-20251001"

client = AsyncAnthropic()

ORDER_TOOL = {
    "name": "submit_order",
    "description": (
        "Виклич цю функцію ЛИШЕ тоді, коли зібрав від клієнта всі чотири дані: "
        "модель кросівок з каталогу, розмір взуття, ім'я клієнта і контакт "
        "(телефон або нікнейм у Telegram). Не викликай, поки хоч одного значення не вистачає."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "model_key": {"type": "string", "description": "Ключ моделі з каталогу"},
            "size": {"type": "integer", "description": "Розмір взуття"},
            "name": {"type": "string", "description": "Ім'я клієнта"},
            "contact": {"type": "string", "description": "Телефон або Telegram клієнта"},
        },
        "required": ["model_key", "size", "name", "contact"],
    },
}


def build_system_prompt(products: dict, min_size: int, max_size: int) -> str:
    catalog_lines = "\n".join(
        f'- ключ "{key}": {item["name"]}, {item["price"]}' for key, item in products.items()
    )
    return f"""Ти — дружній консультант інтернет-магазину кросівок у Telegram. Спілкуєшся українською,
невимушено й тепло, як жива людина-продавець, можеш використовувати емодзі (не забагато).

КАТАЛОГ (єдині товари, які є в наявності):
{catalog_lines}

Розміри {min_size}-{max_size} доступні для УСІХ моделей однаково.

ПРАВИЛА:
1. Якщо клієнт просто спілкується (вітається, питає як справи тощо) — підтримай розмову по-людськи,
   можеш м'яко запропонувати допомогу з вибором взуття.
2. Якщо питає про розмір, якого немає в діапазоні {min_size}-{max_size} — відповідай РІВНО цією фразою:
   "На жаль, такого розміру зараз немає 😔"
3. Якщо питає про модель, якої немає в каталозі вище — відповідай РІВНО цією фразою:
   "На жаль, такої моделі зараз немає в наявності."
4. Ніколи не вигадуй моделі, ціни чи характеристики, яких немає в каталозі.
5. Коли клієнт хоче оформити замовлення — не питай усе одразу. Запитуй по черзі:
   спочатку яка модель, потім розмір, потім ім'я, потім контакт (телефон або Telegram).
   Якщо клієнт вже сам щось із цього назвав раніше в розмові — повторно не питай.
6. Щойно маєш ВСІ чотири дані (модель, розмір, ім'я, контакт) — виклич функцію submit_order.
   Після цього коротко й тепло підтверди клієнту замовлення (модель, розмір, ціна, що з ним зв'яжуться)."""


def _blocks_to_dicts(blocks: list) -> list[dict]:
    result = []
    for block in blocks:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return result


def _extract_text(blocks: list) -> str:
    return "".join(b.text for b in blocks if b.type == "text").strip()


async def get_response(
    history: list[dict],
    products: dict,
    min_size: int,
    max_size: int,
) -> tuple[str, dict[str, Any] | None]:
    """Надсилає всю історію діалогу в Claude, повертає (текст_відповіді, дані_замовлення_або_None).

    history мутується "на місці": в кінець додаються нові репліки асистента,
    щоб наступний виклик мав повний контекст розмови.
    """
    system_prompt = build_system_prompt(products, min_size, max_size)
    fallback_text = "Вибач, зараз невеличкі технічні проблеми 🙈 Спробуй, будь ласка, ще раз трохи пізніше."

    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=system_prompt,
            tools=[ORDER_TOOL],
            messages=history,
        )
    except Exception:
        return fallback_text, None

    if response.stop_reason == "tool_use":
        tool_block = next(b for b in response.content if b.type == "tool_use")
        order_data = dict(tool_block.input)

        history.append({"role": "assistant", "content": _blocks_to_dicts(response.content)})
        history.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": "Замовлення прийнято і передано менеджеру.",
                    }
                ],
            }
        )

        try:
            response2 = await client.messages.create(
                model=MODEL,
                max_tokens=500,
                system=system_prompt,
                tools=[ORDER_TOOL],
                messages=history,
            )
            reply_text = _extract_text(response2.content) or "Дякую! Замовлення оформлено 🙌"
        except Exception:
            reply_text = "Дякую! Замовлення оформлено, менеджер скоро зв'яжеться 🙌"

        history.append({"role": "assistant", "content": reply_text})
        return reply_text, order_data

    reply_text = _extract_text(response.content) or fallback_text
    history.append({"role": "assistant", "content": reply_text})
    return reply_text, None
