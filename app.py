import os
import json
import ast
import random
import logging
from typing import Dict, Any, List, Optional

from flask import Flask, request, Response
from flask_cors import CORS
from sqlalchemy import text
from db import engine

# ----------------- ЛОГИ -----------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [APP] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ----------------- КОНФИГ -----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret")
PORT = int(os.getenv("PORT", "8080"))

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")

# Telegram API (используем requests, библиотека PTB не нужна)
import requests as rq
TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ----------------- ОПЦИИ (если есть файл options.py — используем его) -----------------
try:
    from options import (
        budget_options, type_options, cuisine_options,
        atmosphere_options, reason_options
    )
except Exception:
    budget_options = ["дешево", "средний", "дорого"]
    type_options = ["кафе", "ресторан", "бар", "кофейня"]
    cuisine_options = ["европейская", "итальянская", "кавказская", "японская", "грузинская"]
    atmosphere_options = ["романтика", "тихо", "весело", "семейная"]
    reason_options = ["свидание", "день рождения", "ужин", "деловая встреча"]

category_order = ["budget", "type", "cuisine", "atmosphere", "reason"]
category_prompt = {
    "budget": "Выбери бюджет:",
    "type": "Выбери тип заведения:",
    "cuisine": "Выбери кухню:",
    "atmosphere": "Выбери атмосферу:",
    "reason": "Выбери повод:",
}
category_options_map = {
    "budget": budget_options,
    "type": type_options,
    "cuisine": cuisine_options,
    "atmosphere": atmosphere_options,
    "reason": reason_options,
}

# Маппинг в названия колонок БД
column_map = {
    "Бюджет": "Бюджет",
    "Тип заведения": "Тип заведения",
    "Кухня": "Кухня",
    "Атмосфера": "атмосфера",  # в БД с маленькой
    "Повод": "повод",          # в БД с маленькой
}
# ключ из кнопок -> «человеческое» имя для колонок
key2human = {
    "budget": "Бюджет",
    "type": "Тип заведения",
    "cuisine": "Кухня",
    "atmosphere": "Атмосфера",
    "reason": "Повод",
}

# ----------------- СОСТОЯНИЕ (в памяти процесса) -----------------
# ВАЖНО: на Railway запускай gunicorn с ОДНИМ воркером, чтобы состояние не терялось.
user_state: Dict[int, Dict[str, Any]] = {}   # {user_id: {"budget": ..., "type": ..., "page_map": {"budget": 0, ...}}}

# ----------------- ВСПОМОГАТЕЛЬНОЕ -----------------
def normalize(value: Optional[str], options_list: List[str]) -> Optional[str]:
    if not value:
        return value
    for opt in options_list:
        if value.strip().lower() == opt.strip().lower():
            return opt
    return value

def build_keyboard(options: List[str], prefix: str, page: int = 0, page_size: int = 10) -> Dict[str, Any]:
    start = page * page_size
    end = start + page_size
    keyboard = [[{"text": opt, "callback_data": f"{prefix}:{opt}"}] for opt in options[start:end]]

    nav_row = []
    if page > 0:
        nav_row.append({"text": "⬅️ Назад", "callback_data": f"{prefix}_page:{page - 1}"})
    if end < len(options):
        nav_row.append({"text": "➡️ Далее", "callback_data": f"{prefix}_page:{page + 1}"})
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([{"text": "🔁 Начать заново", "callback_data": "restart"}])
    return {"inline_keyboard": keyboard}

def tg_send_message(chat_id: int, text: str, reply_markup: Dict[str, Any] | None = None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = rq.post(f"{TG_API}/sendMessage", json=payload, timeout=15)
    if resp.status_code != 200:
        logger.error("sendMessage %s | %s", resp.status_code, resp.text)

def tg_edit_message(chat_id: int, message_id: int, text: str, reply_markup: Dict[str, Any] | None = None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = rq.post(f"{TG_API}/editMessageText", json=payload, timeout=15)
    if resp.status_code != 200:
        logger.error("editMessageText %s | %s", resp.status_code, resp.text)

def tg_answer_callback(cb_id: str):
    rq.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=15)

def tg_send_photo(chat_id: int, photo_url: str, caption: str):
    payload = {
        "chat_id": chat_id,
        "photo": photo_url or "https://via.placeholder.com/640x360.png?text=No+Image",
        "caption": caption[:1021] + "..." if len(caption) > 1024 else caption,
        "parse_mode": "HTML",
    }
    resp = rq.post(f"{TG_API}/sendPhoto", json=payload, timeout=20)
    if resp.status_code != 200:
        logger.error("sendPhoto %s | %s", resp.status_code, resp.text)
        tg_send_message(chat_id, caption)

# ----------------- РАБОТА С БД -----------------
def run_query(filters: Dict[str, Optional[str]]):
    query = "SELECT * FROM restaurants_v2 WHERE TRUE"
    params: Dict[str, Any] = {}
    for key, value in filters.items():
        if value:
            col_name = column_map[key]  # точное имя колонки в БД
            placeholder = key.replace(" ", "_")
            query += f' AND LOWER("{col_name}") LIKE :{placeholder}'
            params[placeholder] = f"%{value.strip().lower()}%"

    logger.info("[API] SQL: %s", query)
    logger.info("[API] params: %s", params)

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        return result.mappings().all()

def clean_item(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row_dict.items() if v and str(v).strip().lower() != "nan"}

def generate_ai_reason(item: Dict[str, Any], filters: Dict[str, Optional[str]]) -> str:
    parts = []
    if filters.get("Кухня") and filters["Кухня"].lower() in (item.get("Кухня") or "").lower():
        parts.append(f"здесь готовят отличную {filters['Кухня'].lower()} кухню")
    if filters.get("Атмосфера") and filters["Атмосфера"].lower() in (item.get("атмосфера") or "").lower():
        parts.append(f"атмосфера — {filters['Атмосфера'].lower()}")
    if filters.get("Повод") and filters["Повод"].lower() in (item.get("повод") or "").lower():
        parts.append(f"идеально подойдёт для: {filters['Повод'].lower()}")
    if filters.get("Тип заведения") and filters["Тип заведения"].lower() in (item.get("Тип заведения") or "").lower():
        parts.append(f"формат: {filters['Тип заведения'].lower()}")
    if filters.get("Бюджет"):
        parts.append(f"в пределах бюджета: {filters['Бюджет'].lower()}")
    if parts:
        return "Это место выбрано, потому что " + ", ".join(parts) + "."
    return "Это заведение точно стоит посетить — оно выделяется среди других."

def format_card(item: Dict[str, Any], filters: Dict[str, Optional[str]]) -> str:
    name = item.get("Название", "Ресторан без названия")
    desc = item.get("Описание")
    address = item.get("Адрес")
    metro = item.get("Метро")
    link = item.get("Ссылка") or item.get("Сайт")
    reason = generate_ai_reason(item, filters)

    lines = [f"<b>{name}</b>"]
    if desc:    lines.append(desc)
    if address: lines.append(f"📍 {address}")
    # метро может быть строкой или списком-строкой
    if metro:
        try:
            metro_list = ast.literal_eval(metro) if isinstance(metro, str) else metro
            if isinstance(metro_list, list):
                lines.append(f"🚇 {', '.join(metro_list)}")
            else:
                lines.append(f"🚇 {str(metro)}")
        except Exception:
            lines.append(f"🚇 {str(metro)}")
    if link:    lines.append(f"🔗 {link}")
    lines.append("")
    lines.append(f"🤖 {reason}")
    return "\n".join(lines)

# ----------------- FLASK -----------------
app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return "Сервис tg_miniapp работает! 🔥 Используйте /recommend или Telegram-бота."

@app.route("/recommend", methods=["GET"])
def recommend():
    filters = {
        "Бюджет": request.args.get("budget"),
        "Тип заведения": request.args.get("type"),
        "Кухня": request.args.get("cuisine"),
        "Атмосфера": request.args.get("atmosphere"),
        "Повод": request.args.get("reason"),
    }

    try:
        rows = run_query(filters)
    except Exception:
        logger.exception("[API] ERROR executing query")
        return Response(json.dumps({"message": "Ошибка запроса к БД"}, ensure_ascii=False),
                        content_type="application/json", status=500)

    if not rows:
        return Response(json.dumps({"message": "Ничего не нашлось"}, ensure_ascii=False),
                        content_type="application/json")

    selected = rows if len(rows) <= 3 else random.sample(rows, 3)
    data = []
    for row in selected:
        item = clean_item(dict(row))
        data.append({
            "name": item.get("Название", "Ресторан без названия"),
            "description": item.get("Описание"),
            "address": item.get("Адрес"),
            "metro": item.get("Метро"),
            "photo": item.get("Фото"),
            "link": item.get("Ссылка") or item.get("Сайт"),
            "ai_reason": generate_ai_reason(item, filters),
        })

    return Response(json.dumps(data, ensure_ascii=False), content_type="application/json")

# ----------------- TELEGRAM WEBHOOK -----------------
@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def telegram_webhook():
    # Проверка секрета из заголовка
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_hdr != WEBHOOK_SECRET:
        logger.warning("Wrong secret header")
        return Response("forbidden", status=403)

    update = request.get_json(silent=True) or {}
    logger.info("[TG] update: %s", json.dumps(update, ensure_ascii=False))

    # callback_query (кнопки)
    if "callback_query" in update:
        return handle_callback(update["callback_query"])

    # обычные сообщения
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return Response("ok")

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    # /start — сброс состояния и показ первой клавиатуры
    if text.startswith("/start"):
        user_state[chat_id] = {"page_map": {k: 0 for k in category_order}}
        tg_send_message(chat_id, "Привет! Давай подберём тебе ресторан.\n" + category_prompt["budget"],
                        reply_markup=build_keyboard(budget_options, "budget", 0))
        return Response("ok")

    # если текст, а не кнопки — трактуем как быстрый поиск по «кухне»
    user_state.setdefault(chat_id, {"page_map": {k: 0 for k in category_order}})
    filters = {"Бюджет": None, "Тип заведения": None, "Кухня": text, "Атмосфера": None, "Повод": None}
    return send_recommendations(chat_id, filters)

def handle_callback(cb: Dict[str, Any]):
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    data = cb.get("data") or ""
    tg_answer_callback(cb.get("id"))

    state = user_state.setdefault(chat_id, {"page_map": {k: 0 for k in category_order}})
    page_map: Dict[str, int] = state.get("page_map", {})

    # restart
    if data == "restart":
        user_state[chat_id] = {"page_map": {k: 0 for k in category_order}}
        tg_edit_message(chat_id, message_id, category_prompt["budget"],
                        reply_markup=build_keyboard(budget_options, "budget", 0))
        return Response("ok")

    # пагинация
    if "_page:" in data:
        prefix, page_str = data.split("_page:")
        page = max(0, int(page_str))
        page_map[prefix] = page
        tg_edit_message(chat_id, message_id, category_prompt[prefix],
                        reply_markup=build_keyboard(category_options_map[prefix], prefix, page))
        return Response("ok")

    # выбор значения
    if ":" in data:
        prefix, value = data.split(":", 1)
        # сохраняем выбор
        state[prefix] = value

        # какая следующая категория?
        try:
            idx = category_order.index(prefix)
            next_key = category_order[idx + 1] if idx + 1 < len(category_order) else None
        except ValueError:
            next_key = None

        if next_key:
            page = page_map.get(next_key, 0)
            tg_edit_message(chat_id, message_id, category_prompt[next_key],
                            reply_markup=build_keyboard(category_options_map[next_key], next_key, page))
            return Response("ok")

        # если это был последний выбор — собираем фильтры и шоуим рекомендации
        filters = {
            "Бюджет": normalize(state.get("budget"), budget_options),
            "Тип заведения": normalize(state.get("type"), type_options),
            "Кухня": normalize(state.get("cuisine"), cuisine_options),
            "Атмосфера": normalize(state.get("atmosphere"), atmosphere_options),
            "Повод": normalize(state.get("reason"), reason_options),
        }
        return send_recommendations(chat_id, filters)

    return Response("ok")

def send_recommendations(chat_id: int, filters: Dict[str, Optional[str]]):
    try:
        rows = run_query(filters)
    except Exception:
        logger.exception("[TG] DB error")
        tg_send_message(chat_id, "Упс, не получилось сходить в базу. Попробуй ещё раз позже 🙏")
        return Response("ok")

    if not rows:
        tg_send_message(chat_id, "Ничего не нашлось, попробуй иначе сформулировать запрос 🍽️")
        return Response("ok")

    selected = rows if len(rows) <= 3 else random.sample(rows, 3)
    for row in selected:
        item = clean_item(dict(row))
        caption = format_card(item, filters)
        tg_send_photo(chat_id, item.get("Фото"), caption)

    tg_send_message(chat_id, "Хочешь попробовать другую подборку? Нажми /start или «🔁 Начать заново».")
    return Response("ok")

# ----------------- RUN -----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
