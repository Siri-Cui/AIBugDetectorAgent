# services/file_service.py
"""文件管理服务（支持压缩包上传）——统一UTC时间与序列化"""

import os
import shutil
import uuid
import zipfile
import tarfile
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session

from config import settings
from database.models import Project, ProjectFile
from database.crud import create_project, create_project_file, get_project
from utils.logger import log_info, log_error, log_file_upload
from utils.exceptions import FileUploadError, FileValidationError
from utils.file_handler import get_file_hash

# ---------------- UTC 工具 ----------------

def utc_now() -> datetime:
    """返回UTC tz-aware datetime"""
    return datetime.now(timezone.utc)

def utc_str(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """按UTC生成字符串时间戳（用于ID/文件名）"""
    return utc_now().strftime(fmt)

def to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """naive -> 视为UTC；aware -> 规整为UTC"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

# -----------------------------------------

class FileService:
    """文件管理服务类"""
    
    # 文件类型常量（与数据库枚举值保持一致）
    FILE_TYPE_SOURCE = "source_code"
    FILE_TYPE_ARCHIVE = "archive"
    FILE_TYPE_EXTRACTED = "extracted"
    
    def __init__(self):
        self.upload_dir = settings.UPLOAD_DIR
        self.max_file_size = settings.MAX_FILE_SIZE
        self.allowed_extensions = settings.ALLOWED_EXTENSIONS + ['.zip', '.tar.gz']  # 添加压缩包支持
        self.max_archive_size = getattr(settings, 'MAX_ARCHIVE_SIZE', 100 * 1024 * 1024)  # 100MB
        self.max_extracted_files = getattr(settings, 'MAX_EXTRACTED_FILES', 1000)
    
    def generate_project_id(self) -> str:
        """生成唯一项目ID（使用UTC时间，避免跨区误解）"""
        timestamp = utc_str()  # e.g. 20250928_041103
        unique_id = uuid.uuid4().hex[:8]
        return f"project_{timestamp}_{unique_id}"
    
    def validate_file(self, filename: str, file_size: int) -> None:
        """
        验证上传文件（支持压缩包）
        """
        file_extension = os.path.splitext(filename.lower())[1]
        if file_extension not in [ext.lower() for ext in self.allowed_extensions]:
            raise FileValidationError(
                f"不支持的文件类型: {file_extension}。支持类型: {', '.join(self.allowed_extensions)}"
            )
        
        # 压缩包特殊大小限制
        if file_extension in ('.zip', '.tar.gz') and file_size > self.max_archive_size:
            max_size = self.max_archive_size / (1024 * 1024)
            raise FileValidationError(f"压缩包大小超过{max_size}MB限制")
            
        # 普通文件大小限制
        elif file_size > self.max_file_size:
            max_size = self.max_file_size / (1024 * 1024)
            raise FileValidationError(f"文件大小超过{max_size}MB限制")
        
        if not filename or len(filename) > 255:
            raise FileValidationError("文件名无效")
    
    def save_uploaded_file(
        self, 
        file_content: bytes, 
        original_filename: str,
        project_id: str
    ) -> Tuple[str, str, int]:
        """
        保存上传的文件（文件名用UTC前缀）
        Returns: (文件路径, 安全文件名, 文件大小)
        """
        try:
            file_size = len(file_content)
            self.validate_file(original_filename, file_size)
            
            # 创建项目专属目录
            project_dir = os.path.join(self.upload_dir, project_id)
            os.makedirs(project_dir, exist_ok=True)
            
            # 生成安全文件名（UTC）
            timestamp = utc_str()
            file_ext = os.path.splitext(original_filename)[1]
            safe_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = os.path.join(project_dir, safe_filename)
            
            # 保存文件
            with open(file_path, "wb") as f:
                f.write(file_content)
            
            log_file_upload(original_filename, file_size)
            return file_path, safe_filename, file_size
            
        except Exception as e:
            log_error(f"文件保存失败: {str(e)}")
            raise FileUploadError(f"文件保存失败: {str(e)}")

    def handle_archive_upload(
        self,
        db: Session,
        archive_path: str,
        project_id: str,
        original_filename: str
    ) -> List[ProjectFile]:
        """
        处理压缩包上传（解压 + 入库记录，时间统一UTC）
        """
        extracted_files: List[ProjectFile] = []
        extract_dir = os.path.join(self.upload_dir, project_id, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        try:
            # 解压文件
            if archive_path.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    if len(file_list) > self.max_extracted_files:
                        raise FileUploadError(f"压缩包内文件数超过{self.max_extracted_files}限制")
                    zip_ref.extractall(extract_dir)
            else:  # .tar.gz / .tgz
                with tarfile.open(archive_path, 'r:*') as tar_ref:
                    file_list = tar_ref.getnames()
                    if len(file_list) > self.max_extracted_files:
                        raise FileUploadError(f"压缩包内文件数超过{self.max_extracted_files}限制")
                    tar_ref.extractall(extract_dir)

            now = utc_now()

            # 创建解压文件记录（只对允许后缀入库）
            for filename in file_list:
                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in [ext.lower() for ext in settings.ALLOWED_EXTENSIONS]:
                    file_path = os.path.join(extract_dir, filename)
                    if os.path.isfile(file_path):
                        with open(file_path, 'rb') as f:
                            file_content = f.read()
                        
                        pf = create_project_file(
                            db=db,
                            project_id=project_id,
                            filename=f"ext_{uuid.uuid4().hex[:8]}_{filename}",
                            original_name=filename,
                            file_path=file_path,
                            size=len(file_content),
                            extension=file_ext,
                            file_hash=get_file_hash(file_path),
                            file_type=self.FILE_TYPE_EXTRACTED,
                            is_extracted=True,
                            parent_archive=original_filename,
                            upload_time=now,  # 关键：UTC-aware
                        )
                        extracted_files.append(pf)

            return extracted_files

        except Exception as e:
            # 清理失败的解压文件
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            raise FileUploadError(f"压缩包处理失败: {str(e)}")

    def create_project_with_file(
        self,
        db: Session,
        file_content: bytes,
        original_filename: str,
        project_name: Optional[str] = None,
        description: Optional[str] = None,
        extracted_files: Optional[List[str]] = None
    ) -> Tuple[Project, ProjectFile, List[ProjectFile]]:
        """
        创建项目并保存文件（支持压缩包；统一UTC时间）
        """
        try:
            now = utc_now()

            # 创建项目（项目名也使用UTC时间，避免地域歧义）
            project_id = self.generate_project_id()
            project = create_project(
                db, 
                project_id, 
                project_name or f"Project_{utc_str()}",
                description
                # 如果你的 CRUD 支持 created_time 字段透传，可加 created_time=now
            )

            # 保存主文件
            file_path, safe_filename, file_size = self.save_uploaded_file(
                file_content, original_filename, project_id
            )
            
            # 判断是否为压缩包
            is_archive = original_filename.lower().endswith(('.zip', '.tar.gz'))
            file_type = self.FILE_TYPE_ARCHIVE if is_archive else self.FILE_TYPE_SOURCE
            
            main_file = create_project_file(
                db=db,
                project_id=project_id,
                filename=safe_filename,
                original_name=original_filename,
                file_path=file_path,
                size=file_size,
                extension=os.path.splitext(original_filename)[1],
                file_hash=get_file_hash(file_path),
                file_type=file_type,
                is_archive=is_archive,
                is_extracted=False,
                parent_archive=None,
                upload_time=now,  # 关键：UTC-aware
            )

            # 处理压缩包
            extracted_pf_list: List[ProjectFile] = []
            if is_archive:
                extracted_pf_list = self.handle_archive_upload(
                    db, file_path, project_id, original_filename
                )
                log_info(f"解压完成，共 {len(extracted_pf_list)} 个文件")

            return project, main_file, extracted_pf_list

        except Exception as e:
            log_error(f"创建项目失败: {str(e)}")
            if 'file_path' in locals() and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            raise

    def get_project_file_info(self, db: Session, project_id: str) -> Dict[str, Any]:
        """
        获取项目文件信息（时间统一为UTC ISO；对历史naive时间兜底转UTC）
        """
        try:
            project = get_project(db, project_id)
            if not project:
                return {"error": "项目不存在"}
            
            files = []
            for file in project.files:
                ut = getattr(file, "upload_time", None)
                ut = to_utc_aware(ut) if isinstance(ut, datetime) else None
                upload_time_iso = ut.isoformat().replace("+00:00", "Z") if ut else None
                upload_epoch_ms = int(ut.timestamp() * 1000) if ut else None

                files.append({
                    "filename": file.filename,
                    "original_name": file.original_name,
                    "size": file.size,
                    "extension": file.extension,
                    "upload_time": upload_time_iso,      # e.g. 2025-09-28T04:11:03.263Z
                    "upload_epoch_ms": upload_epoch_ms,  # 方便前端稳健解析
                    "status": file.status,
                    "is_archive": file.is_archive,
                    "is_extracted": file.is_extracted,
                    "parent_archive": file.parent_archive
                })
            
            return {
                "project_id": project.id,
                "project_name": project.name,
                "files": files,
                "file_count": len(files)
            }
            
        except Exception as e:
            log_error(f"获取项目文件信息失败: {str(e)}")
            return {"error": str(e)}

    def delete_project_files(self, db: Session, project_id: str) -> bool:
        """
        删除项目文件（包含解压文件）
        """
        try:
            project = get_project(db, project_id)
            if not project:
                return False
            
            # 删除物理文件
            for file in project.files:
                if os.path.exists(file.file_path):
                    os.remove(file.file_path)
                    log_info(f"删除文件: {file.file_path}")
            
            # 删除项目目录
            project_dir = os.path.join(self.upload_dir, project_id)
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
            
            return True
            
        except Exception as e:
            log_error(f"删除项目文件失败: {str(e)}")
            return False

    def clean_orphaned_files(self, db: Session) -> int:
        """
        清理孤立文件
        """
        cleaned = 0
        try:
            if not os.path.exists(self.upload_dir):
                return 0
            
            # 获取数据库记录的文件路径
            db_files = {f.file_path for f in db.query(ProjectFile).all()}
            
            # 检查物理文件
            for root, _, files in os.walk(self.upload_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    if file_path not in db_files:
                        try:
                            os.remove(file_path)
                            cleaned += 1
                            log_info(f"清理孤立文件: {file_path}")
                        except:
                            pass
            
            return cleaned
            
        except Exception as e:
            log_error(f"清理孤立文件失败: {str(e)}")
            return 0

    def get_storage_statistics(self) -> Dict[str, Any]:
        """
        获取存储统计信息
        """
        stats = {
            "upload_dir": self.upload_dir,
            "total_files": 0,
            "total_size": 0,
            "file_types": {},
            "projects": {},
            "disk_usage": {}
        }
        
        try:
            if os.path.exists(self.upload_dir):
                # 统计文件
                for root, dirs, files in os.walk(self.upload_dir):
                    # 项目统计
                    if root.count(os.sep) == self.upload_dir.count(os.sep) + 1:
                        project_id = os.path.basename(root)
                        stats["projects"][project_id] = {
                            "files": 0,
                            "size": 0
                        }
                    
                    for file in files:
                        file_path = os.path.join(root, file)
                        if os.path.isfile(file_path):
                            size = os.path.getsize(file_path)
                            stats["total_files"] += 1
                            stats["total_size"] += size
                            
                            # 文件类型统计
                            ext = os.path.splitext(file)[1].lower()
                            stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
                            
                            # 项目统计
                            if root in stats["projects"]:
                                stats["projects"][os.path.basename(root)]["files"] += 1
                                stats["projects"][os.path.basename(root)]["size"] += size
                
                # 磁盘使用情况
                if hasattr(shutil, 'disk_usage'):
                    usage = shutil.disk_usage(self.upload_dir)
                    stats["disk_usage"] = {
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free
                    }
            
            return stats
            
        except Exception as e:
            log_error(f"获取存储统计失败: {str(e)}")
            return {"error": str(e)}

# 全局服务实例
file_service = FileService()
