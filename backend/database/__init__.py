"""数据库模块"""

from .connection import engine, SessionLocal, get_db, init_database, check_database_health
from .models import Base, Project, ProjectFile, Analysis, Defect, AgentLog, SystemConfig
from .crud import (
    create_project, get_project, get_projects, update_project_status, delete_project,
    create_project_file, get_project_files,
    create_analysis, update_analysis_status,
    create_defect, update_analysis_statistics,
    create_agent_log,
    get_config, set_config
)

__all__ = [
    # 连接管理
    "engine",
    "SessionLocal", 
    "get_db",
    "init_database",
    "check_database_health",
    
    # 数据模型
    "Base",
    "Project",
    "ProjectFile", 
    "Analysis",
    "Defect",
    "AgentLog",
    "SystemConfig",
    
    # CRUD操作
    "create_project",
    "get_project",
    "get_projects",
    "update_project_status",
    "delete_project",
    "create_project_file",
    "get_project_files",
    "create_analysis",
    "update_analysis_status",
    "create_defect",
    "update_analysis_statistics",
    "create_agent_log",
    "get_config",
    "set_config",
]
