import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CallbackContext, CommandHandler, CallbackQueryHandler
import requests

from options import budget_options, type_options, cuisine_options, atmosphere_options, reason_options

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:5001/recommend"
user_state = {}

# Карта опций для кнопок
category_options_map = {
    "budget": budget_options,
    "type": type_options,
    "cuisine": cuisine_options,
    "atmosphere": atmosphere_options,
    "reason": reason_options
}

# /start или кнопка Restart
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_state[user_id] = {}
    await update.message.reply_text(
        "Привет! Давай подберём тебе ресторан. Сначала выбери бюджет:",
        reply_markup=build_keyboard(budget_options, 'budget')
    )

# Построение клавиатуры с пагинацией
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

    # Добавляем кнопку перезапуска
    keyboard.append([InlineKeyboardButton("🔁 Начать заново", callback_data="restart")])

    return InlineKeyboardMarkup(keyboard)

# Обработка всех кнопок
async def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Перезапуск
    if data == "restart":
        user_state[user_id] = {}
        await query.edit_message_text("Окей! Сначала выбери бюджет:",
                                      reply_markup=build_keyboard(budget_options, 'budget'))
        return

    # Пагинация
    if '_page:' in data:
        prefix, page = data.split('_page:')
        page = int(page)
        await query.edit_message_text(
            f"Выбери {prefix}:",
            reply_markup=build_keyboard(category_options_map[prefix], prefix, page)
        )
        return

    # Сохраняем выбранный параметр
    category, value = data.split(":", 1)
    user_state[user_id][category] = value

    # Переход к следующему шагу
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

# Показ подборки ресторанов
async def show_recommendations(query, filters):
    params = {
        "budget": filters.get("budget"),
        "type": filters.get("type"),
        "cuisine": filters.get("cuisine"),
        "atmosphere": filters.get("atmosphere"),
        "reason": filters.get("reason")
    }

    try:
        response = requests.get(API_URL, params=params)
        data = response.json()
    except Exception as e:
        await query.edit_message_text("Ошибка при получении данных. Попробуйте позже.")
        return

    if not data or "message" in data:
        await query.edit_message_text("Ничего не нашлось по твоим критериям. Попробуй снова с другими настройками.")
        return

    messages = []
    for place in data[:3]:
        text = f"<b>{place.get('Название', 'Без названия')}</b>\n"
        if place.get("Описание"):
            text += f"{place['Описание']}\n"
        if place.get("Адрес"):
            text += f"📍 {place['Адрес']}\n"
        if place.get("Метро"):
            text += f"🚇 {place['Метро']}\n"
        if place.get("Ссылка"):
            text += f"<a href=\"{place['Ссылка']}\">Подробнее</a>\n"

        reason = place.get("ai_reason") or "Подходит по выбранным параметрам."
        text += f"\n🤖 {reason}"

        photo = place.get("Фото") or "https://via.placeholder.com/640x360.png?text=No+Image"
        messages.append((photo, text))

    media = [InputMediaPhoto(media=photo, caption=txt, parse_mode="HTML") for photo, txt in messages]
    await query.message.reply_media_group(media)
    await query.message.reply_text("Хочешь попробовать другой подбор? Нажми /start или кнопку ниже 👇",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Начать заново", callback_data="restart")]]))

# Запуск бота
if __name__ == "__main__":
    from telegram.ext import filters

    app = ApplicationBuilder().token("8240440485:AAEPlsFOpm1aYRl9WWMmfx9Ltb2wI529BRQ").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Бот запущен...")
    app.run_polling()
