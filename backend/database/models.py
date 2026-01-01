# database/models.py
"""SQLAlchemy 数据模型定义（SQLite 兼容；统一为 UTC-aware datetime）"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Float, Boolean, ForeignKey, Enum as SqlEnum, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# ---- UTC 默认值（应用层保证，不依赖DB时区） ----
def utc_now():
    return datetime.now(timezone.utc)

# ---------- 枚举 ----------
file_type_enum = SqlEnum(
    'source_code', 'archive', 'extracted',
    name='file_type_enum',
)

# ---------- 项目 ----------
class Project(Base):
    __tablename__ = "projects"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # 改为 timezone=True，并用应用层UTC默认
    created_time = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_time = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    status = Column(String(20), default="pending", nullable=False)
    file_count = Column(Integer, default=0)
    archive_count = Column(Integer, default=0)

    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="project", cascade="all, delete-orphan")

# ---------- 项目文件 ----------
class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(50), ForeignKey("projects.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    size = Column(Integer, nullable=False)
    extension = Column(String(10), nullable=False)

    # 关键：统一为 UTC-aware
    upload_time = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    status = Column(String(20), default="uploaded", nullable=False)
    file_hash = Column(String(32), nullable=True)

    file_type = Column(file_type_enum, default='source_code', nullable=False)
    is_archive = Column(Boolean, default=False)
    is_extracted = Column(Boolean, default=False)
    parent_archive = Column(String(255), nullable=True)
    extracted_path = Column(String(500), nullable=True)

    project = relationship("Project", back_populates="files")

    parent_file_id = Column(Integer, ForeignKey('project_files.id'), nullable=True)

    extracted_files = relationship(
        "ProjectFile",
        back_populates="parent_file",
        remote_side=[parent_file_id],
        cascade="all, delete-orphan",
        single_parent=True
    )
    parent_file = relationship(
        "ProjectFile", 
        back_populates="extracted_files",
        remote_side=[id]
    )
    
    __table_args__ = (
        Index('idx_parent_archive', 'parent_archive'),
        Index('idx_file_type', 'file_type'),
    )

# ---------- 分析任务 ----------
class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(String(50), primary_key=True)
    project_id = Column(String(50), ForeignKey("projects.id"), nullable=False)
    analysis_type = Column(String(20), nullable=False)
    status = Column(String(20), default="pending", nullable=False)

    start_time = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration = Column(Float, nullable=True)

    total_defects = Column(Integer, default=0)
    critical_defects = Column(Integer, default=0)
    high_defects = Column(Integer, default=0)
    medium_defects = Column(Integer, default=0)
    low_defects = Column(Integer, default=0)

    error_message = Column(Text, nullable=True)

    project = relationship("Project", back_populates="analyses")
    defects = relationship("Defect", back_populates="analysis", cascade="all, delete-orphan")

# ---------- 缺陷 ----------
class Defect(Base):
    __tablename__ = "defects"

    id = Column(String(50), primary_key=True)
    analysis_id = Column(String(50), ForeignKey("analyses.id"), nullable=False)

    type = Column(String(50), nullable=False)
    severity = Column(String(10), nullable=False)
    category = Column(String(30), nullable=False)

    file_path = Column(String(500), nullable=False)
    line_number = Column(Integer, nullable=False)
    column_number = Column(Integer, nullable=True)
    function_name = Column(String(100), nullable=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    code_snippet = Column(Text, nullable=True)

    suggestion = Column(Text, nullable=True)
    repair_confidence = Column(Float, nullable=True)

    tool_name = Column(String(50), nullable=False)
    rule_id = Column(String(50), nullable=True)

    status = Column(String(20), default="open", nullable=False)
    created_time = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    analysis = relationship("Analysis", back_populates="defects")

# ---------- Agent 日志 ----------
class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(50), nullable=False)
    project_id = Column(String(50), nullable=True)
    analysis_id = Column(String(50), nullable=True)

    log_level = Column(String(10), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)

    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    duration = Column(Float, nullable=True)
    status = Column(String(20), nullable=True)

# ---------- 系统配置 ----------
class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    created_time = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_time = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

# ---------- 工具函数 ----------
def create_tables(engine):
    """创建所有数据库表（SQLite / MySQL / PostgreSQL 通用）"""
    Base.metadata.create_all(engine)
