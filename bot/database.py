# bot/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from bot.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True) # pool_pre_ping помогает избежать ошибок соединения
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from bot import models
    Base.metadata.create_all(bind=engine)
