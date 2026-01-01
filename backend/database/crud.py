# database/crud.py
"""数据库CRUD操作（统一UTC tz-aware）"""
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import desc, func, update
from sqlalchemy.exc import IntegrityError

from .models import Project, ProjectFile, Analysis, Defect, AgentLog, SystemConfig
from utils.logger import log_info, log_error


# ---------- UTC 工具 ----------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return (
        dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None
        else dt.astimezone(timezone.utc)
    )


# =========================
# 项目相关操作
# =========================
def create_project(
    db: Session, project_id: str, name: str, description: str = None
) -> Project:
    """创建项目（时间字段在 SQLAlchemy 模型中默认使用 UTC）"""
    try:
        project = Project(id=project_id, name=name, description=description)
        db.add(project)
        db.commit()
        db.refresh(project)

        log_info(f"创建项目成功: {project_id}")
        return project

    except Exception as e:
        db.rollback()
        log_error(f"创建项目失败: {str(e)}")
        raise


def get_project(db: Session, project_id: str) -> Optional[Project]:
    """获取项目"""
    return db.query(Project).filter(Project.id == project_id).first()


def get_projects(db: Session, skip: int = 0, limit: int = 100) -> List[Project]:
    """获取项目列表"""
    return (
        db.query(Project)
        .order_by(desc(Project.created_time))
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_project_status(db: Session, project_id: str, status: str) -> bool:
    """更新项目状态（UTC）"""
    try:
        project = get_project(db, project_id)
        if project:
            project.status = status
            project.updated_time = utc_now()
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        log_error(f"更新项目状态失败: {str(e)}")
        return False


def delete_project(db: Session, project_id: str) -> bool:
    """删除项目"""
    try:
        project = get_project(db, project_id)
        if project:
            db.delete(project)
            db.commit()
            log_info(f"删除项目成功: {project_id}")
            return True
        return False
    except Exception as e:
        db.rollback()
        log_error(f"删除项目失败: {str(e)}")
        return False


# =========================
# 文件相关操作
# =========================
def create_project_file(
    db: Session,
    project_id: str,
    filename: str,
    original_name: str,
    file_path: str,
    size: int,
    extension: str,
    file_hash: Optional[str] = None,
    file_type: Optional[str] = None,
    is_archive: bool = False,
    is_extracted: bool = False,
    parent_archive: Optional[str] = None,
    parent_file_id: Optional[int] = None,  # 关系字段
    upload_time: Optional[datetime] = None,  # ✅ 新增：允许上层传入UTC时间
) -> ProjectFile:
    """创建项目文件记录（UTC 版）"""
    try:
        # 统一 UTC
        upload_time = to_utc_aware(upload_time) or utc_now()

        # 自动设置 extracted_path（如果是解压文件）
        extracted_path = os.path.dirname(file_path) if is_extracted else None

        file_record = ProjectFile(
            project_id=project_id,
            filename=filename,
            original_name=original_name,
            file_path=file_path,
            size=size,
            extension=extension,
            file_hash=file_hash,
            file_type=file_type or ("archive" if is_archive else "source_code"),
            is_archive=is_archive,
            is_extracted=is_extracted,
            parent_archive=parent_archive,
            parent_file_id=parent_file_id,
            extracted_path=extracted_path,
            upload_time=upload_time,  # ✅ 关键：写入 tz-aware UTC
            status="uploaded",
        )

        # 原子更新项目文件计数
        db.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(file_count=Project.file_count + 1)
        )

        db.add(file_record)
        db.commit()
        db.refresh(file_record)

        log_info(f"创建文件记录成功: {filename} (ID: {file_record.id})")
        return file_record

    except Exception as e:
        db.rollback()
        log_error(
            f"创建文件记录失败: {str(e)}",
            extra={
                "filename": filename,
                "project_id": project_id,
                "error_details": str(e),
            },
        )
        raise


def get_project_files(db: Session, project_id: str) -> List[ProjectFile]:
    """获取项目文件列表"""
    return db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()


# =========================
# 分析相关操作
# =========================
def create_analysis(
    db: Session,
    project_id: str,
    analysis_type: str = "static",
    status: str = "running",
    analysis_id: Optional[str] = None,
    start_time: Optional[datetime] = None,  # ✅ 新增：允许透传开始时间
) -> Analysis:
    """
    创建分析任务（支持外部传入 analysis_id；不传则自动生成唯一 ID）
    - 避免唯一键冲突：若撞唯一键，自动重新生成 ID 并重试
    """
    tries = 0
    while True:
        try:
            if not analysis_id:
                analysis_id = f"analysis_{project_id}_{uuid4().hex[:8]}"

            st = to_utc_aware(start_time) or utc_now()

            analysis = Analysis(
                id=analysis_id,
                project_id=project_id,
                analysis_type=analysis_type,
                status=status,  # 覆盖 DB 默认
                start_time=st,  # ✅ 统一为UTC
            )
            db.add(analysis)
            db.commit()
            db.refresh(analysis)

            log_info(f"创建分析任务成功: {analysis_id}")
            return analysis

        except IntegrityError as ie:
            db.rollback()
            tries += 1
            if tries >= 3:
                log_error(f"创建分析任务失败（多次 ID 冲突）: {str(ie)}")
                raise
            analysis_id = None
        except Exception as e:
            db.rollback()
            log_error(f"创建分析任务失败: {str(e)}")
            raise


def update_analysis_status(
    db: Session, analysis_id: str, status: str, error_message: Optional[str] = None
) -> bool:
    """更新分析状态（完成时写入 UTC 结束时间与时长）"""
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = status
            if status == "completed":
                analysis.end_time = utc_now()
                if analysis.start_time:
                    duration = (
                        analysis.end_time - to_utc_aware(analysis.start_time)
                    ).total_seconds()
                    analysis.duration = duration
            if error_message:
                analysis.error_message = error_message
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        log_error(f"更新分析状态失败: {str(e)}")
        return False


# =========================
# 缺陷相关操作
# =========================
def create_defect(
    db: Session, defect_id: str, analysis_id: str, defect_data: Dict[str, Any]
) -> Defect:
    """创建缺陷记录"""
    try:
        defect = Defect(id=defect_id, analysis_id=analysis_id, **defect_data)
        db.add(defect)
        db.commit()
        db.refresh(defect)

        # 更新分析统计信息
        update_analysis_statistics(db, analysis_id)

        return defect

    except Exception as e:
        db.rollback()
        log_error(f"创建缺陷记录失败: {str(e)}")
        raise


def update_analysis_statistics(db: Session, analysis_id: str):
    """更新分析统计信息"""
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            # 统计各级别缺陷数量
            defect_counts = (
                db.query(Defect.severity, func.count(Defect.id).label("count"))
                .filter(Defect.analysis_id == analysis_id)
                .group_by(Defect.severity)
                .all()
            )

            # 重置计数
            analysis.total_defects = 0
            analysis.critical_defects = 0
            analysis.high_defects = 0
            analysis.medium_defects = 0
            analysis.low_defects = 0

            # 更新计数
            for severity, count in defect_counts:
                analysis.total_defects += count
                if severity == "critical":
                    analysis.critical_defects = count
                elif severity == "high":
                    analysis.high_defects = count
                elif severity == "medium":
                    analysis.medium_defects = count
                elif severity == "low":
                    analysis.low_defects = count

            db.commit()

    except Exception as e:
        db.rollback()
        log_error(f"更新分析统计失败: {str(e)}")


# =========================
# Agent日志相关操作
# =========================
def create_agent_log(
    db: Session,
    agent_name: str,
    log_level: str,
    message: str,
    project_id: str = None,
    analysis_id: str = None,
    details: str = None,
    duration: float = None,
    status: str = None,
) -> AgentLog:
    """创建Agent日志（时间字段在模型中默认UTC）"""
    try:
        log_entry = AgentLog(
            agent_name=agent_name,
            log_level=log_level,
            message=message,
            project_id=project_id,
            analysis_id=analysis_id,
            details=details,
            duration=duration,
            status=status,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)

        return log_entry

    except Exception as e:
        db.rollback()
        log_error(f"创建Agent日志失败: {str(e)}")
        raise


# =========================
# 系统配置相关操作
# =========================
def get_config(db: Session, key: str) -> Optional[str]:
    """获取配置值"""
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return config.value if config else None


def set_config(db: Session, key: str, value: str, description: str = None):
    """设置配置值（UTC 更新时间）"""
    try:
        config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if config:
            config.value = value
            config.updated_time = utc_now()
            if description is not None:
                config.description = description
        else:
            config = SystemConfig(
                key=key,
                value=value,
                description=description,
                created_time=utc_now(),
                updated_time=utc_now(),
            )
            db.add(config)

        db.commit()

    except Exception as e:
        db.rollback()
        log_error(f"设置配置失败: {str(e)}")
        raise


def init_default_config(db: Session):
    """初始化默认配置"""
    default_configs = [
        ("system.version", "1.0.0", "系统版本"),
        ("analysis.timeout", "300", "分析超时时间（秒）"),
        ("file.max_size", "52428800", "最大文件大小（字节）"),
        ("agent.max_concurrent", "3", "最大并发Agent数量"),
    ]

    for key, value, description in default_configs:
        existing = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if not existing:
            set_config(db, key, value, description)


# =========================
# 删除功能
# =========================


def delete_analysis_with_files(db: Session, analysis_id: str) -> bool:
    """删除分析记录（数据库 + 结果文件）"""
    import shutil
    from config import settings

    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            log_error(f"分析记录不存在: {analysis_id}")
            return False

        # 1. 删除数据库记录（级联删除defects）
        db.delete(analysis)
        db.commit()

        # 2. 删除结果文件
        result_file = os.path.join(settings.RESULTS_DIR, f"{analysis_id}.json")
        if os.path.exists(result_file):
            os.remove(result_file)
            log_info(f"删除结果文件: {result_file}")

        log_info(f"删除分析记录成功: {analysis_id}")
        return True

    except Exception as e:
        db.rollback()
        log_error(f"删除分析记录失败: {str(e)}")
        return False


def delete_project_with_files(db: Session, project_id: str) -> bool:
    """删除项目及其所有文件（数据库 + 物理文件）"""
    import shutil
    import glob
    from config import settings

    try:
        project = get_project(db, project_id)
        if not project:
            log_error(f"项目不存在: {project_id}")
            return False

        # 1. 删除数据库记录（级联删除files、analyses、defects）
        db.delete(project)
        db.commit()

        # 2. 删除项目上传目录
        project_dir = os.path.join(settings.UPLOAD_DIR, project_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            log_info(f"删除项目目录: {project_dir}")

        # 3. 删除所有分析结果文件
        result_pattern = os.path.join(
            settings.RESULTS_DIR, f"analysis_{project_id}_*.json"
        )
        for result_file in glob.glob(result_pattern):
            os.remove(result_file)
            log_info(f"删除结果文件: {result_file}")

        log_info(f"删除项目成功: {project_id}")
        return True

    except Exception as e:
        db.rollback()
        log_error(f"删除项目失败: {str(e)}")
        return False


# =========================
# 封装类
# =========================
class ProjectCRUD:
    """项目CRUD操作封装类"""

    def __init__(self, db: Session):
        self.db = db

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目"""
        return get_project(self.db, project_id)

    def create_project(
        self, project_id: str, name: str, description: str = None
    ) -> Project:
        """创建项目"""
        return create_project(self.db, project_id, name, description)

    def update_project_status(self, project_id: str, status: str) -> bool:
        """更新项目状态"""
        return update_project_status(self.db, project_id, status)

    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        return delete_project_with_files(self.db, project_id)


class AnalysisCRUD:
    """分析CRUD操作封装类"""

    def __init__(self, db: Session):
        self.db = db

    def create_analysis(
        self,
        project_id: str,
        analysis_type: str = "static",
        status: str = "running",
        analysis_id: Optional[str] = None,
        start_time: Optional[datetime] = None,  # ✅ 透传UTC开始时间
    ) -> Analysis:
        """创建分析记录（支持外部传入 analysis_id 与 start_time）"""
        return create_analysis(
            self.db,
            project_id=project_id,
            analysis_type=analysis_type,
            status=status,
            analysis_id=analysis_id,
            start_time=start_time,
        )

    def get_analysis(self, analysis_id: str) -> Optional[Analysis]:
        """获取分析记录"""
        return self.db.query(Analysis).filter(Analysis.id == analysis_id).first()

    def get_latest_analysis_by_project(self, project_id: str) -> Optional[Analysis]:
        """获取项目最新分析"""
        return (
            self.db.query(Analysis)
            .filter(Analysis.project_id == project_id)
            .order_by(desc(Analysis.start_time))
            .first()
        )

    def update_analysis_status(
        self, analysis_id: str, status: str, error_message: str = None
    ) -> bool:
        """更新分析状态"""
        return update_analysis_status(self.db, analysis_id, status, error_message)

    def delete_analysis(self, analysis_id: str) -> bool:
        """删除分析记录"""
        return delete_analysis_with_files(self.db, analysis_id)


# =========================
# 迭代8新增：指标相关查询
# =========================


def get_analysis(db: Session, analysis_id: str) -> Optional[Analysis]:
    """
    获取单个分析记录

    用于：
    - metrics.py 中获取分析结果计算指标
    - 报告生成时获取完整数据
    """
    return db.query(Analysis).filter(Analysis.id == analysis_id).first()


def get_project_analyses(
    db: Session, project_id: str, skip: int = 0, limit: int = 100
) -> List[Analysis]:
    """
    获取项目的所有分析记录（按时间倒序）

    用于：
    - 趋势分析（同一项目多次分析的质量分数变化）
    - 对比报告生成

    参数:
        project_id: 项目ID
        skip: 跳过记录数（分页）
        limit: 返回记录数上限

    返回:
        Analysis列表（最新的在前）
    """
    return (
        db.query(Analysis)
        .filter(Analysis.project_id == project_id)
        .order_by(desc(Analysis.start_time))
        .offset(skip)
        .limit(limit)
        .all()
    )
