import os
import sys
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL не задан. Укажи переменную окружения или .env")
    sys.exit(1)

print("🔌 Подключаюсь к БД…")
try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        # 1) кто мы и куда подключены
        who = conn.execute(text("select current_database(), current_user")).one()
        print(f"✅ Ок. База: {who[0]} | Пользователь: {who[1]}")

        # 2) список таблиц в public
        print("\n📚 Таблицы в схеме public:")
        tables = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
            ORDER BY table_name
        """)).fetchall()
        for t in tables:
            print("  •", t[0])

        # 3) структура restaurants_v2 (если есть)
        has_rv2 = any(t[0] == "restaurants_v2" for t in tables)
        if has_rv2:
            print("\n🧱 Колонки в restaurants_v2:")
            cols = conn.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='restaurants_v2'
                ORDER BY ordinal_position
            """)).fetchall()
            for c in cols:
                print(f"  - {c[0]} :: {c[1]}")

            # 4) количество строк
            cnt = conn.execute(text("SELECT COUNT(*) FROM restaurants_v2")).scalar()
            print(f"\n📈 Строк в restaurants_v2: {cnt}")

            # 5) пример 5 записей (важные поля)
            print("\n🔎 Примеры (5 строк):")
            sample = conn.execute(text("""
                SELECT "Название","Адрес","Метро","Кухня","Тип заведения","Бюджет","Фото","Ссылка"
                FROM restaurants_v2
                LIMIT 5
            """)).mappings().all()
            for row in sample:
                print("—", json.dumps(dict(row), ensure_ascii=False))
        else:
            print("\n⚠️ Таблица restaurants_v2 не найдена в public.")
except Exception as e:
    print("❌ Ошибка подключения/запроса:", e)
    sys.exit(2)
