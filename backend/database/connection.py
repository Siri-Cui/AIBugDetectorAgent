"""数据库连接管理"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from typing import Generator

from config import settings
from utils.logger import logger, log_info, log_error
from .models import Base, create_tables

# 创建数据库引擎
def create_database_engine():
    """创建数据库引擎"""
    database_url = settings.DATABASE_URL
    
    # 确保数据库目录存在
    if database_url.startswith("sqlite"):
        db_path = database_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
    # SQLite配置
    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            poolclass=StaticPool,
            connect_args={
                "check_same_thread": False,
                "timeout": 20
            },
            echo=settings.DEBUG  # 开发模式下打印SQL
        )
        
        # SQLite优化设置
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            # 启用外键约束
            cursor.execute("PRAGMA foreign_keys=ON")
            # 设置WAL模式提高并发性能
            cursor.execute("PRAGMA journal_mode=WAL")
            # 设置同步模式
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    else:
        # 其他数据库配置
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            echo=settings.DEBUG
        )
    
    return engine

# 创建引擎和会话工厂
engine = create_database_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 初始化数据库
def init_database():
    """初始化数据库"""
    try:
        log_info("开始初始化数据库...")
        
        # 创建所有表
        create_tables(engine)
        
        # 插入默认配置
        with get_db_session() as db:
            from .crud import init_default_config
            init_default_config(db)
        
        log_info("数据库初始化完成")
        
    except Exception as e:
        log_error(f"数据库初始化失败: {str(e)}")
        raise

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """获取数据库会话上下文管理器"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"数据库操作异常: {str(e)}")
        raise
    finally:
        session.close()

def get_db() -> Generator[Session, None, None]:
    """FastAPI依赖注入使用的数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 数据库健康检查
def check_database_health() -> bool:
    """检查数据库连接健康状态"""
    try:
        with get_db_session() as db:
            # 执行简单查询测试连接
            db.execute("SELECT 1")
            return True
    except Exception as e:
        log_error(f"数据库健康检查失败: {str(e)}")
        return False

# 启动时初始化数据库
if __name__ != "__main__":  # 避免在测试时重复初始化
    try:
        init_database()
    except Exception as e:
        log_error(f"数据库启动初始化失败: {str(e)}")
