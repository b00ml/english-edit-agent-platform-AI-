# app/database.py —— 数据库连接与会话管理
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# 创建数据库引擎（连接参数取自全局配置）
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# 会话工厂
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """FastAPI 依赖注入：为每个请求提供独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
