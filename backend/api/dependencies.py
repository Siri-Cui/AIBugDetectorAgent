"""FastAPI依赖注入"""

from typing import Generator
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from database.connection import get_db, check_database_health
from utils.logger import log_error
from config import settings

def get_database() -> Generator[Session, None, None]:
    """
    数据库会话依赖注入
    
    Yields:
        Session: SQLAlchemy数据库会话
        
    Raises:
        HTTPException: 数据库连接失败时抛出503错误
    """
    try:
        db = next(get_db())
        yield db
    except Exception as e:
        log_error(f"数据库连接失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库服务不可用"
        )
    finally:
        if 'db' in locals():
            db.close()

def verify_api_health():
    """
    API健康检查依赖
    
    Raises:
        HTTPException: 系统不健康时抛出503错误
    """
    if not check_database_health():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="系统服务不可用"
        )

def get_current_settings():
    """
    获取当前配置依赖
    
    Returns:
        Settings: 应用配置对象
    """
    return settings

def validate_file_upload():
    """
    文件上传验证依赖
    
    Returns:
        dict: 上传限制配置
    """
    return {
        "max_file_size": settings.MAX_FILE_SIZE,
        "allowed_extensions": settings.ALLOWED_EXTENSIONS,
        "upload_dir": settings.UPLOAD_DIR
    }

class DatabaseDependency:
    """数据库依赖类"""
    
    def __init__(self):
        self.db = None
    
    def __call__(self) -> Session:
        """获取数据库会话"""
        return next(get_database())

class ConfigDependency:
    """配置依赖类"""
    
    def __call__(self):
        """获取应用配置"""
        return get_current_settings()

# 创建依赖实例
db_dependency = DatabaseDependency()
config_dependency = ConfigDependency()

# 常用依赖别名
DatabaseSession = Depends(get_database)
AppConfig = Depends(get_current_settings)
HealthCheck = Depends(verify_api_health)
FileUploadConfig = Depends(validate_file_upload)
