from flask import Flask, request, Response
from flask_cors import CORS
from sqlalchemy import text
from db import engine
import json
import random

app = Flask(__name__)
CORS(app)

@app.route("/")  
def index():
    return "Сервис tg_miniapp работает! 🔥 Используйте /recommend для рекомендаций."

@app.route("/recommend", methods=["GET"])
def recommend():
    filters = {
        "Бюджет": request.args.get("budget"),
        "Тип заведения": request.args.get("type"),
        "Кухня": request.args.get("cuisine"),
        "атмосфера": request.args.get("atmosphere"),
        "повод": request.args.get("reason")
    }

    query = "SELECT * FROM restaurants_v2 WHERE TRUE"
    params = {}

    for key, value in filters.items():
        if value:
            query += f' AND "{key}" ILIKE :{key.replace(" ", "_")}'
            params[key.replace(" ", "_")] = f"%{value.strip()}%"

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        rows = result.mappings().all()

    if not rows:
        return Response(json.dumps({"message": "Ничего не нашлось"}), content_type="application/json")

    selected = random.sample(rows, min(len(rows), 3))

    data = []
    for row in selected:
        item = dict(row)

        # Clean missing fields
        item_clean = {k: v for k, v in item.items() if v and v != "nan"}

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
    if filters.get("атмосфера") and filters["атмосфера"].lower() in (item.get("атмосфера") or "").lower():
        parts.append(f"атмосфера — {filters['атмосфера'].lower()}")
    if filters.get("повод") and filters["повод"].lower() in (item.get("повод") or "").lower():
        parts.append(f"идеально подойдёт для: {filters['повод'].lower()}")
    if filters.get("Тип заведения") and filters["Тип заведения"].lower() in (item.get("Тип заведения") or "").lower():
        parts.append(f"формат: {filters['Тип заведения'].lower()}")
    if filters.get("Бюджет"):
        parts.append(f"в пределах бюджета: {filters['Бюджет'].lower()}")

    if parts:
        return "Это место выбрано, потому что " + ", ".join(parts) + "."
    return "Это заведение точно стоит посетить — оно выделяется среди других."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
