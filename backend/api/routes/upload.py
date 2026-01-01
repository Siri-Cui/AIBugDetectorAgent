"""文件上传路由 - 支持压缩包版本（安全解压 + 多后缀识别）"""
import os
import zipfile
import tarfile
import pathlib
import shutil
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from database.crud import ProjectCRUD
from database.connection import get_db
from api.models import ApiResponse


from api.models import (
    FileUploadResponse,
    FileInfo,
    FileStatus,
    FileType,
)
from api.dependencies import get_database, validate_file_upload
from services.file_service import file_service
from utils.logger import log_info, log_error
from utils.exceptions import FileUploadError, FileValidationError

router = APIRouter(prefix="/api", tags=["upload"])

# 允许的文件扩展名（统一用 endswith 判断以兼容多后缀）
ALLOWED_EXTENSIONS: tuple[str, ...] = (
    ".cpp",
    ".h",
    ".hpp",
    ".cc",
    ".cxx",
    ".zip",
    ".tar.gz",
    ".tgz",
)
MAX_EXTRACT_SIZE = 100 * 1024 * 1024  # 100MB 限制


# ---------- UTC 工具 ----------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    dt = to_utc_aware(dt)
    return int(dt.timestamp() * 1000)


def _is_allowed(filename: str) -> bool:
    """判断文件是否允许（支持多后缀）"""
    low = filename.lower()
    return any(low.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def _is_within_directory(base_dir: str, target_path: str) -> bool:
    base = pathlib.Path(base_dir).resolve(strict=True)
    try:
        # 在resolve之前先检查是否为符号链接
        target = pathlib.Path(target_path)
        if target.is_symlink():
            return False  # 拒绝符号链接
        target_resolved = target.resolve(strict=False)
        target_resolved.relative_to(base)
        return True
    except (ValueError, OSError):
        return False


async def handle_compressed_file(file_path: str, extract_dir: str) -> List[str]:
    """
    安全处理压缩文件：大小限制 + 路径穿越校验
    返回：解压得到的文件（包含相对路径）
    """
    total_size = 0
    extracted_files: List[str] = []

    os.makedirs(extract_dir, exist_ok=True)
    low = file_path.lower()

    if low.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            for member in zip_ref.infolist():
                total_size += member.file_size
                if total_size > MAX_EXTRACT_SIZE:
                    raise FileValidationError("解压内容超过100MB限制")
                # 路径穿越检查
                target_path = os.path.join(extract_dir, member.filename)
                if not _is_within_directory(extract_dir, target_path):
                    raise FileValidationError("压缩包内含非法路径（路径穿越）")
            # 校验通过后统一解压
            zip_ref.extractall(extract_dir)
            extracted_files = zip_ref.namelist()
    else:
        # 兼容 .tar.gz / .tgz / 其他 tar 压缩格式
        with tarfile.open(file_path, "r:*") as tar_ref:
            for member in tar_ref.getmembers():
                if member.isfile():
                    total_size += member.size
                    if total_size > MAX_EXTRACT_SIZE:
                        raise FileValidationError("解压内容超过100MB限制")
                    target_path = os.path.join(extract_dir, member.name)
                    if not _is_within_directory(extract_dir, target_path):
                        raise FileValidationError("压缩包内含非法路径（路径穿越）")
            tar_ref.extractall(extract_dir)
            extracted_files = [m.name for m in tar_ref.getmembers() if m.isfile()]

    return extracted_files


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    project_name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_database),
    upload_config: dict = Depends(validate_file_upload),
):
    """
    上传 C++ 项目文件（支持源码文件与压缩包：.zip/.tar.gz/.tgz）
    流程：
    1) 白名单校验
    2) 保存至临时目录
    3) 若为压缩包则安全解压并记录文件列表
    4) 交由文件服务入库
    5) 清理临时文件/目录
    """
    temp_dir = "/home/wsh/ai-bug-detector/data/temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)

    extract_dir: Optional[str] = None
    tmp_file_path = os.path.join(temp_dir, file.filename)

    try:
        log_info(f"收到文件上传请求: {file.filename}")

        # 1. 基础校验（多后缀）
        if not _is_allowed(file.filename):
            allow_str = ", ".join(ALLOWED_EXTENSIONS)
            raise FileValidationError(f"不支持的文件类型，仅允许: {allow_str}")

        # 2. 保存原始文件到临时目录
        with open(tmp_file_path, "wb") as buffer:
            buffer.write(await file.read())

        # 3. 压缩包解压（如适用）
        extracted_files: List[str] = []
        low = file.filename.lower()
        if low.endswith((".zip", ".tar.gz", ".tgz")):
            extract_dir = os.path.join(temp_dir, "extracted")
            extracted_files = await handle_compressed_file(tmp_file_path, extract_dir)
            log_info(f"解压完成，共 {len(extracted_files)} 个文件")

        # 4. 交由服务层落盘/入库
        with open(tmp_file_path, "rb") as rf:
            file_bytes = rf.read()

        project, project_file, extracted_project_files = file_service.create_project_with_file(
            db=db,
            file_content=file_bytes,
            original_filename=file.filename,
            project_name=project_name,
            description=description,
            extracted_files=extracted_files,
        )

        # 5. 构造响应模型（含解压文件信息）
        extracted_file_infos: List[FileInfo] = []
        if extracted_project_files:
            for ef in extracted_project_files:
                ef_time_utc = to_utc_aware(getattr(ef, "upload_time", None))
                extracted_file_infos.append(
                    FileInfo(
                        filename=ef.filename,
                        original_name=ef.original_name,
                        size=ef.size,
                        extension=ef.extension,
                        upload_time=ef_time_utc,  # tz-aware
                        file_path=ef.file_path,
                        status=FileStatus.UPLOADED,
                        file_type=FileType.EXTRACTED,
                        parent_archive=project_file.original_name,
                    )
                )

        pf_time_utc = to_utc_aware(getattr(project_file, "upload_time", None))

        resp = FileUploadResponse(
            success=True,
            message="文件上传成功" + ("（已解压）" if extracted_files else ""),
            # BaseResponse 会自动补 timestamp=UTC 与 epoch_ms
            file_info=FileInfo(
                filename=project_file.filename,
                original_name=project_file.original_name,
                size=project_file.size,
                extension=project_file.extension,
                upload_time=pf_time_utc,  # tz-aware
                file_path=project_file.file_path,
                status=FileStatus.UPLOADED,
                file_type=FileType.ARCHIVE if getattr(project_file, "is_archive", False) else FileType.SOURCE_CODE,
            ),
            project_id=project.id,
            extracted_files=extracted_file_infos,
        )
        return resp

    except (FileUploadError, FileValidationError) as e:
        log_error(f"文件上传异常: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_error(f"系统异常: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件处理失败")
    finally:
        # 6. 清理临时文件/目录（尽量不抛异常）
        try:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
        except Exception:
            pass
        if extract_dir and os.path.exists(extract_dir):
            try:
                shutil.rmtree(extract_dir)
            except Exception:
                pass




@router.delete("/project/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db)
):
    """删除项目及其所有文件"""
    try:
        project_crud = ProjectCRUD(db)
        success = project_crud.delete_project(project_id)
        
        if success:
            return ApiResponse(
                success=True,
                data={"message": "项目已删除", "project_id": project_id}
            )
        else:
            return ApiResponse(
                success=False,
                data={"error": "项目不存在或删除失败"}
            )
            
    except Exception as e:
        log_error(f"删除项目失败: {str(e)}")
        return ApiResponse(
            success=False,
            data={"error": str(e)}
        )
