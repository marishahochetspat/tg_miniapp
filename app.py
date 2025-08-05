import os
import json
import random
from flask import Flask, request, Response
from flask_cors import CORS
from sqlalchemy import text
from db import engine

app = Flask(__name__)
CORS(app)

# Маппинг API-параметра -> точное имя колонки в БД
column_map = {
    "Бюджет": "Бюджет",
    "Тип заведения": "Тип заведения",
    "Кухня": "Кухня",
    "Атмосфера": "атмосфера",  # в БД с маленькой
    "Повод": "повод"           # в БД с маленькой
}

@app.route("/")
def index():
    return "Сервис tg_miniapp работает! 🔥 Используйте /recommend для рекомендаций."

@app.route("/recommend", methods=["GET"])
def recommend():
    # Принимаем фильтры из запроса
    filters = {
        "Бюджет": request.args.get("budget"),
        "Тип заведения": request.args.get("type"),
        "Кухня": request.args.get("cuisine"),
        "Атмосфера": request.args.get("atmosphere"),
        "Повод": request.args.get("reason")
    }

    query = "SELECT * FROM restaurants_v2 WHERE TRUE"
    params = {}

    for key, value in filters.items():
        if value:
            col_name = column_map[key]  # точное имя колонки в БД
            placeholder = key.replace(" ", "_")
            query += f' AND LOWER("{col_name}") LIKE :{placeholder}'
            params[placeholder] = f"%{value.strip().lower()}%"

    # Логируем, чтобы видеть на Railway
    print(f"[API] SQL: {query}", flush=True)
    print(f"[API] params: {params}", flush=True)

    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.mappings().all()
    except Exception as e:
        print(f"[API] ERROR executing query: {e}", flush=True)
        return Response(json.dumps({"message": "Ошибка запроса к БД"}), content_type="application/json", status=500)

    if not rows:
        return Response(json.dumps({"message": "Ничего не нашлось"}), content_type="application/json")

    selected = rows if len(rows) <= 3 else random.sample(rows, 3)

    data = []
    for row in selected:
        item = dict(row)
        # Убираем пустые и nan
        item_clean = {k: v for k, v in item.items() if v and str(v).strip().lower() != "nan"}

        explanation = generate_ai_reason(item_clean, filters)

        formatted_item = {
            "name": item_clean.get("Название", "Ресторан без названия"),
            "description": item_clean.get("Описание"),
            "address": item_clean.get("Адрес"),
            "metro": item_clean.get("Метро"),
            "photo": item_clean.get("Фото"),
            "link": item_clean.get("Ссылка") or item_clean.get("Сайт"),
            "ai_reason": explanation
        }
        data.append(formatted_item)

    return Response(json.dumps(data, ensure_ascii=False), content_type="application/json")

def generate_ai_reason(item, filters):
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
