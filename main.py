import logging
import ast
import requests
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, CallbackContext, CommandHandler, CallbackQueryHandler
)
from options import (
    budget_options, type_options, cuisine_options,
    atmosphere_options, reason_options
)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://tg-miniapp-togj.onrender.com/recommend"
user_state = {}

# Карта опций
category_options_map = {
    "budget": budget_options,
    "type": type_options,
    "cuisine": cuisine_options,
    "atmosphere": atmosphere_options,
    "reason": reason_options
}

# Нормализация значений
def normalize(value, options_list):
    if not value:
        return value
    for opt in options_list:
        if value.strip().lower() == opt.strip().lower():
            return opt
    return value

# /start
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_state[user_id] = {}
    await update.message.reply_text(
        "Привет! Давай подберём тебе ресторан. Сначала выбери бюджет:",
        reply_markup=build_keyboard(budget_options, 'budget')
    )

# Пагинация клавиатуры
def build_keyboard(options, prefix, page=0, page_size=10):
    start = page * page_size
    end = start + page_size
    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"{prefix}:{opt}")]
        for opt in options[start:end]
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"{prefix}_page:{page - 1}"))
    if end < len(options):
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"{prefix}_page:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔁 Начать заново", callback_data="restart")])
    return InlineKeyboardMarkup(keyboard)

# Обработка кнопок
async def handle_callback(update: Update, context: CallbackContext):
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

    if '_page:' in data:
        prefix, page = data.split('_page:')
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

# Рекомендации
MAX_CAPTION_LENGTH = 1024  # лимит Telegram

async def show_recommendations(query, filters):
    params = {
        "budget": normalize(filters.get("budget"), budget_options),
        "type": normalize(filters.get("type"), type_options),
        "cuisine": normalize(filters.get("cuisine"), cuisine_options),
        "atmosphere": normalize(filters.get("atmosphere"), atmosphere_options),
        "reason": normalize(filters.get("reason"), reason_options)
    }

    try:
        response = requests.get(API_URL, params=params)
        logger.info(f"➡️ Параметры запроса: {params}")
        logger.info(f"📥 Ответ от API: {response.status_code} {response.text}")
        data = response.json()
    except Exception as e:
        logger.error(f"Ошибка при запросе к API: {e}")
        await query.edit_message_text("Ошибка при получении данных. Попробуйте позже.")
        return

    if not data or "message" in data:
        await query.edit_message_text("Ничего не нашлось по твоим критериям. Попробуй снова с другими настройками.")
        return

    for place in data[:3]:
        text = f"<b>{place.get('name', 'Без названия')}</b>\n"
        if place.get("description"):
            text += f"{place['description']}\n"
        if place.get("address"):
            text += f"📍 {place['address']}\n"

        # Обработка метро — убрать квадратные скобки
        metro_raw = place.get("metro", "")
        try:
            metro_list = ast.literal_eval(metro_raw)
            if isinstance(metro_list, list):
                metro_str = ", ".join(metro_list)
            else:
                metro_str = str(metro_list)
        except Exception:
            metro_str = metro_raw

        text += f"🚇 {metro_str}\n"

        if place.get("link"):
            text += f"<a href=\"{place['link']}\">Подробнее</a>\n"

        reason = place.get("ai_reason") or "Подходит по выбранным параметрам."
        text += f"\n🤖 {reason}"

        # Обрезаем подпись по длине, чтобы не было ошибки
        if len(text) > MAX_CAPTION_LENGTH:
            text = text[:MAX_CAPTION_LENGTH - 3] + "..."

        photo = place.get("photo") or "https://via.placeholder.com/640x360.png?text=No+Image"

        try:
            await query.message.reply_photo(photo=photo, caption=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            # Если ошибка — отправим просто текст без фото
            await query.message.reply_text(text, parse_mode="HTML")

    await query.message.reply_text(
        "Хочешь попробовать другой подбор? Нажми /start или кнопку ниже 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Начать заново", callback_data="restart")]
        ])
    )
# Запуск
if __name__ == "__main__":
    app = ApplicationBuilder().token("8240440485:AAEPlsFOpm1aYRl9WWMmfx9Ltb2wI529BRQ").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Бот запущен...")
    app.run_polling()