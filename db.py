import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")  # читаем из .env
engine = create_engine(DATABASE_URL)
