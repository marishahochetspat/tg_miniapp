from sqlalchemy import text
from db import engine

with engine.connect() as conn:
    result = conn.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
    )
    print("Список таблиц в базе данных:")
    for row in result:
        print("—", row[0])

