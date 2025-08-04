from flask import Flask, request, Response
from flask_cors import CORS
from sqlalchemy import text
from db import engine
import json
import random

app = Flask(__name__)
CORS(app)

@app.route("/recommend", methods=["GET"])
def recommend():
    filters = {
        "бюджет": request.args.get("budget"),
        "тип заведения": request.args.get("type"),
        "кухня": request.args.get("cuisine"),
        "атмосфера": request.args.get("atmosphere"),
        "повод": request.args.get("reason")
    }

    query = "SELECT * FROM restaurants_v2 WHERE TRUE"
    params = {}

    for key, value in filters.items():
        if value:
            query += f" AND \"{key}\" ILIKE :{key}"
            params[key] = f"%{value.strip()}%"

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
            "name": item_clean.get("название", "Ресторан без названия"),
            "description": item_clean.get("описание"),
            "address": item_clean.get("адрес"),
            "metro": item_clean.get("метро"),
            "photo": item_clean.get("фото"),
            "link": item_clean.get("ссылка") or item_clean.get("сайт"),
            "ai_reason": explanation
        }

        data.append(formatted_item)

    return Response(json.dumps(data, ensure_ascii=False), content_type="application/json")

def generate_ai_reason(item, filters):
    parts = []

    if filters.get("кухня") and filters["кухня"].lower() in (item.get("кухня") or "").lower():
        parts.append(f"здесь готовят отличную {filters['кухня'].lower()} кухню")
    if filters.get("атмосфера") and filters["атмосфера"].lower() in (item.get("атмосфера") or "").lower():
        parts.append(f"атмосфера — {filters['атмосфера'].lower()}")
    if filters.get("повод") and filters["повод"].lower() in (item.get("повод") or "").lower():
        parts.append(f"идеально подойдёт для: {filters['повод'].lower()}")
    if filters.get("тип заведения") and filters["тип заведения"].lower() in (item.get("тип заведения") or "").lower():
        parts.append(f"формат: {filters['тип заведения'].lower()}")
    if filters.get("бюджет"):
        parts.append(f"в пределах бюджета: {filters['бюджет'].lower()}")

    if parts:
        return "Это место выбрано, потому что " + ", ".join(parts) + "."
    return "Это заведение точно стоит посетить — оно выделяется среди других."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)

