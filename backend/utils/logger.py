import logging
import sys
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from config import settings

def setup_logger():
    """设置结构化日志配置"""
    
    # 创建根日志器
    logger = logging.getLogger("ai_bug_detector")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # 清除现有处理器
    logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（轮转日志）
    if settings.LOG_FILE:
        # 确保日志目录存在
        log_dir = os.path.dirname(settings.LOG_FILE)
        os.makedirs(log_dir, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

# 创建全局日志器
logger = setup_logger()

# 便捷日志函数
def log_info(message: str, **kwargs):
    """记录信息日志"""
    logger.info(message)

def log_error(message: str, **kwargs):
    """记录错误日志"""
    logger.error(message)

def log_warning(message: str, **kwargs):
    """记录警告日志"""
    logger.warning(message, extra=kwargs)

def log_debug(message: str, **kwargs):
    """记录调试日志"""
    logger.debug(message, extra=kwargs)

def log_analysis_start(project_id: str, file_count: int):
    """记录分析开始"""
    log_info(f"开始分析项目 {project_id}，文件数量: {file_count}")

def log_analysis_complete(project_id: str, duration: float, defects_count: int):
    """记录分析完成"""
    log_info(f"项目 {project_id} 分析完成，耗时: {duration:.2f}s，发现缺陷: {defects_count}")

def log_file_upload(filename: str, size: int, client_ip: str = ""):
    """记录文件上传"""
    log_info(f"文件上传成功: {filename}，大小: {size} bytes，客户端IP: {client_ip}")