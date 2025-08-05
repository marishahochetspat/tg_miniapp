import os
import logging
import ast
import asyncio
import functools
import requests

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
)

from options import (
    budget_options, type_options, cuisine_options,
    atmosphere_options, reason_options
)

# ----------------- ЛОГИ -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [BOT] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ----------------- КОНФИГ -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Задай в Railway → Variables
API_URL = f"http://127.0.0.1:{os.environ.get('PORT', 5000)}/recommend"  # локально внутри сервиса

user_state = {}

category_options_map = {
    "budget": budget_options,
    "type": type_options,
    "cuisine": cuisine_options,
    "atmosphere": atmosphere_options,
    "reason": reason_options
}

# ----------------- УТИЛИТЫ -----------------
def normalize(value, options_list):
    if not value:
        return value
    for opt in options_list:
        if value.strip().lower() == opt.strip().lower():
            return opt
    return value

def build_keyboard(options, prefix, page=0, page_size=10):
    start = page * page_size
    end = start + page_size
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"{prefix}:{opt}")] for opt in options[start:end]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"{prefix}_page:{page - 1}"))
    if end < len(options):
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"{prefix}_page:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔁 Начать заново", callback_data="restart")])
    return InlineKeyboardMarkup(keyboard)

async def fetch_api(url, params):
    """Неблокирующий requests.get + timeout."""
    loop = asyncio.get_running_loop()
    fn = functools.partial(requests.get, url, params=params, timeout=15)
    return await loop.run_in_executor(None, fn)

# ----------------- ХЕНДЛЕРЫ -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_state[user_id] = {}
    await update.message.reply_text(
        "Привет! Давай подберём тебе ресторан. Сначала выбери бюджет:",
        reply_markup=build_keyboard(budget_options, 'budget')
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "restart":
        user_state[user_id] = {}
        await query.edit_message_text(
            "Окей! Сначала выбери бюджет:",
            reply_markup=build_keyboard(budget_options, 'budget')
        )
        return

    if "_page:" in data:
        prefix, page = data.split("_page:")
        page = int(page)
        await query.edit_message_text(
            f"Выбери {prefix}:",
            reply_markup=build_keyboard(category_options_map[prefix], prefix, page)
        )
        return

    category, value = data.split(":", 1)
    user_state[user_id][category] = value

    next_step = {
        "budget": ("Выбери тип заведения:", type_options, 'type'),
        "type": ("Выбери кухню:", cuisine_options, 'cuisine'),
        "cuisine": ("Выбери атмосферу:", atmosphere_options, 'atmosphere'),
        "atmosphere": ("Выбери повод:", reason_options, 'reason'),
        "reason": ("Отлично! Вот подборка для тебя:", None, None)
    }

    if category == "reason":
        await show_recommendations(query, user_state[user_id])
        return

    msg, options, next_key = next_step[category]
    await query.edit_message_text(msg, reply_markup=build_keyboard(options, next_key))

MAX_CAPTION_LENGTH = 1024

async def show_recommendations(query, filters):
    params = {
        "budget": normalize(filters.get("budget"), budget_options),
        "type": normalize(filters.get("type"), type_options),
        "cuisine": normalize(filters.get("cuisine"), cuisine_options),
        "atmosphere": normalize(filters.get("atmosphere"), atmosphere_options),
        "reason": normalize(filters.get("reason"), reason_options)
    }

    # 3 попытки на случай «сонного» контейнера/сети
    for attempt in range(3):
        try:
            response = await fetch_api(API_URL, params)
            logger.info(f"➡️ Запрос к API (попытка {attempt+1}/3): {params}")
            logger.info(f"📥 Ответ от API: {response.status_code} {response.text[:500]}")
            data = response.json()
            break
        except Exception as e:
            logger.warning(f"Проблема с API (попытка {attempt+1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                await query.edit_message_text("Ошибка при получении данных. Попробуйте позже.")
                return

    if not data or (isinstance(data, dict) and data.get("message")):
        await query.edit_message_text("Ничего не нашлось по твоим критериям. Попробуй снова с другими настройками.")
        return

    for place in data[:3]:
        text = f"<b>{place.get('name', 'Без названия')}</b>\n"
        if place.get("description"):
            text += f"{place['description']}\n"
        if place.get("address"):
            text += f"📍 {place['address']}\n"

        metro_raw = place.get("metro", "")
        try:
            metro_list = ast.literal_eval(metro_raw)
            metro_str = ", ".join(metro_list) if isinstance(metro_list, list) else str(metro_list)
        except Exception:
            metro_str = str(metro_raw) if metro_raw else "—"
        if metro_str:
            text += f"🚇 {metro_str}\n"

        if place.get("link"):
            text += f"<a href=\"{place['link']}\">Подробнее</a>\n"

        reason = place.get("ai_reason") or "Подходит по выбранным параметрам."
        text += f"\n🤖 {reason}"

        if len(text) > MAX_CAPTION_LENGTH:
            text = text[:MAX_CAPTION_LENGTH - 3] + "..."

        photo = place.get("photo") or "https://via.placeholder.com/640x360.png?text=No+Image"

        try:
            await query.message.reply_photo(photo=photo, caption=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            await query.message.reply_text(text, parse_mode="HTML")

    await query.message.reply_text(
        "Хочешь попробовать другой подбор? Нажми /start или кнопку ниже 👇",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Начать заново", callback_data="restart")]])
    )

# ----------------- СТАРТ ПРИЛОЖЕНИЯ -----------------
async def on_startup(app):
    # Снять webhook, чтобы polling не ловил 409/Conflict
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook удалён, запускаю polling…")

def build_application():
    if not BOT_TOKEN:
        raise RuntimeError("Переменная окружения BOT_TOKEN не задана в Railway")
    return (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_startup)   # корректная регистрация хука инициализации
        .build()
    )

def main():
    app = build_application()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Бот запущен…")
    # drop_pending_updates — на всякий случай чистим бэклог
    app.run_polling(allowed_updates=list(), drop_pending_updates=True)

if __name__ == "__main__":
    main()
