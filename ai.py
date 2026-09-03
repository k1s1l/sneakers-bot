"""
Інтеграція з Claude API.

Потребує змінну оточення ANTHROPIC_API_KEY (ключ береться автоматично
з оточення офіційним SDK, окремо передавати нікуди не треба).

Функція analyze_message() надсилає повідомлення клієнта в Claude і отримує
назад структурований JSON: що хотів клієнт (модель / розмір / питання),
яку саме модель/розмір мав на увазі, і готову відповідь для intent="question".
"""

import json
from typing import Any

from anthropic import AsyncAnthropic

MODEL = "claude-haiku-4-5-20251001"  # швидка й дешева модель — саме для такої задачі

client = AsyncAnthropic()


def build_system_prompt(products: dict, min_size: int, max_size: int) -> str:
    catalog_lines = "\n".join(
        f"- {key}: {item['name']} ({item['price']})" for key, item in products.items()
    )
    valid_keys = ", ".join(f'"{k}"' for k in products)
    return f"""Ти — асистент інтернет-магазину кросівок. Каталог (ключ: назва, ціна):
{catalog_lines}

Розміри {min_size}-{max_size} доступні для УСІХ моделей однаково.

Проаналізуй повідомлення клієнта і поверни ЛИШЕ JSON, без жодного тексту навколо, без markdown-огорожі:
{{
  "intent": "model_query" | "size_query" | "question" | "unclear",
  "model_key": одне значення з [{valid_keys}] або null,
  "size": ціле число (розмір взуття) або null,
  "answer": коротка (1-3 речення) відповідь українською для intent="question", інакше null
}}

Правила:
- "model_query" — клієнт цікавиться конкретною моделлю кросівок (навіть з друкарськими помилками, скороченнями чи описом на кшталт "адідас спешл").
- "size_query" — клієнт запитує саме про розмір взуття.
- "question" — будь-яке інше питання про магазин, доставку, оплату, матеріали тощо. У полі "answer" дай коротку ввічливу відповідь на основі каталогу вище; якщо точної інформації немає — чесно скажи, що уточниш це особисто.
- "unclear" — геть незрозуміло, про що йдеться.
- Якщо повідомлення містить і модель, і розмір — це "model_query", а розмір також вкажи в полі "size"."""


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return raw.strip()


async def analyze_message(text: str, system_prompt: str) -> dict[str, Any]:
    """Повертає dict із ключами intent/model_key/size/answer.
    У разі будь-якої помилки (немає ключа, збій мережі тощо) — безпечний fallback."""
    fallback = {"intent": "unclear", "model_key": None, "size": None, "answer": None}
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = _strip_code_fence(response.content[0].text)
        data = json.loads(raw)
        return {
            "intent": data.get("intent", "unclear"),
            "model_key": data.get("model_key"),
            "size": data.get("size"),
            "answer": data.get("answer"),
        }
    except Exception:
        return fallback
