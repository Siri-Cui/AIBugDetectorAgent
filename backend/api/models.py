# api/models.py
"""Pydantic数据模型定义（统一UTC序列化，支持epoch_ms）"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
import zipfile
import tarfile

# ---------- 公共：UTC工具与序列化 ----------

def _ensure_utc(dt: datetime) -> datetime:
    if dt is None:
        return None
    # naive -> 作为UTC；aware -> 规整到UTC
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def _dt_to_iso_z(dt: datetime) -> str:
    """将 datetime 统一格式化为 ISO8601 且以 Z 结尾（UTC）"""
    if dt is None:
        return None
    dt_utc = _ensure_utc(dt)
    s = dt_utc.isoformat()
    # 大多数环境会输出+00:00；替换成Z统一风格
    return s.replace("+00:00", "Z")

class _UTCBaseModel(BaseModel):
    class Config:
        json_encoders = {
            datetime: _dt_to_iso_z
        }

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def epoch_ms(dt: Optional[datetime] = None) -> Optional[int]:
    if dt is None:
        return None
    return int(_ensure_utc(dt).timestamp() * 1000)

# ========== 枚举定义 ==========
class FileType(str, Enum):
    SOURCE_CODE = "source_code"
    ARCHIVE = "archive"
    EXTRACTED = "extracted"

class FileStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXTRACTING = "extracting"

class AnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class DefectSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# ========== 通用响应外壳 ==========
class ApiResponse(_UTCBaseModel):
    """统一响应外壳：与路由返回保持一致"""
    success: bool = True
    timestamp: datetime = Field(default_factory=utc_now)
    epoch_ms: Optional[int] = Field(default=None, description="UTC 毫秒时间戳")
    data: Optional[Dict[str, Any]] = None

    def __init__(self, **data):
        super().__init__(**data)
        # 自动填充 epoch_ms（如果未提供）
        if self.epoch_ms is None and isinstance(self.timestamp, datetime):
            object.__setattr__(self, 'epoch_ms', epoch_ms(self.timestamp))

# ========== 基础模型 ==========
class BaseResponse(_UTCBaseModel):
    success: bool = True
    message: str = ""
    timestamp: datetime = Field(default_factory=utc_now)
    epoch_ms: Optional[int] = None

    def __init__(self, **data):
        super().__init__(**data)
        if self.epoch_ms is None and isinstance(self.timestamp, datetime):
            object.__setattr__(self, 'epoch_ms', epoch_ms(self.timestamp))

class ErrorResponse(BaseResponse):
    success: bool = False
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

# ========== 文件相关模型 ==========
class FileInfoBase(_UTCBaseModel):
    filename: str
    original_name: str
    size: int
    extension: str
    upload_time: datetime
    upload_epoch_ms: Optional[int] = None
    file_path: str
    status: FileStatus = FileStatus.UPLOADED

    def __init__(self, **data):
        # 自动补齐 upload_epoch_ms
        if "upload_time" in data and data.get("upload_epoch_ms") is None:
            data["upload_epoch_ms"] = epoch_ms(data["upload_time"])
        # 统一 upload_time 为 UTC-aware
        if "upload_time" in data and isinstance(data["upload_time"], datetime):
            data["upload_time"] = _ensure_utc(data["upload_time"])
        super().__init__(**data)

class FileInfo(FileInfoBase):
    file_type: FileType = Field(
        default=FileType.SOURCE_CODE,
        description="文件类型（源码/压缩包/解压文件）"
    )
    parent_archive: Optional[str] = Field(
        None,
        description="如果是解压文件，记录所属压缩包文件名"
    )

class ExtractedFileInfo(FileInfoBase):
    file_type: FileType = FileType.EXTRACTED

# ========== 请求/响应模型 ==========
class FileUploadRequest(_UTCBaseModel):
    project_name: Optional[str] = None
    description: Optional[str] = None

class FileUploadResponse(BaseResponse):
    file_info: FileInfo
    project_id: str
    extracted_files: List[FileInfo] = Field(default_factory=list, description="当上传压缩包时返回解压文件列表")

class ArchiveUploadResponse(FileUploadResponse):
    extracted_files: List[ExtractedFileInfo] = Field(default_factory=list)
    archive_info: Optional[FileInfo] = None

# ========== 项目相关模型 ==========
class ProjectInfo(_UTCBaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_time: datetime
    created_epoch_ms: Optional[int] = None
    file_count: int
    status: AnalysisStatus = AnalysisStatus.PENDING

    def __init__(self, **data):
        if "created_time" in data and data.get("created_epoch_ms") is None:
            data["created_epoch_ms"] = epoch_ms(data["created_time"])
        if "created_time" in data and isinstance(data["created_time"], datetime):
            data["created_time"] = _ensure_utc(data["created_time"])
        super().__init__(**data)

class ProjectListResponse(BaseResponse):
    projects: List[ProjectInfo]
    total: int

# ========== 分析相关模型 ==========
class DefectInfo(_UTCBaseModel):
    id: str
    type: str
    severity: DefectSeverity
    description: str
    file_path: str
    line_number: int
    column_number: Optional[int] = None
    code_snippet: Optional[str] = None
    suggestion: Optional[str] = None

class AnalysisResult(_UTCBaseModel):
    project_id: str
    analysis_type: str  # static, dynamic
    start_time: datetime
    start_epoch_ms: Optional[int] = None
    end_time: Optional[datetime] = None
    end_epoch_ms: Optional[int] = None
    status: AnalysisStatus
    defects: List[DefectInfo] = Field(default_factory=list)
    statistics: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        if "start_time" in data and data.get("start_epoch_ms") is None:
            data["start_epoch_ms"] = epoch_ms(data["start_time"])
        if "end_time" in data and data.get("end_epoch_ms") is None and data.get("end_time") is not None:
            data["end_epoch_ms"] = epoch_ms(data["end_time"])
        if "start_time" in data and isinstance(data["start_time"], datetime):
            data["start_time"] = _ensure_utc(data["start_time"])
        if "end_time" in data and isinstance(data["end_time"], datetime):
            data["end_time"] = _ensure_utc(data["end_time"])
        super().__init__(**data)

class AnalysisResponse(BaseResponse):
    analysis_id: str
    result: Optional[AnalysisResult] = None

# ========== 系统模型 ==========
class SystemInfo(_UTCBaseModel):
    name: str = "AI Agent缺陷检测系统"
    version: str = "1.0.0"
    status: str = "running"
    uptime: Optional[str] = None
    supported_agents: List[str] = [
        "FileAnalyzerAgent",
        "DetectionAgent",
        "ContextAnalyzerAgent",
        "RepairGeneratorAgent",
        "ValidationAgent"
    ]
    workflow: str = "上传 → 文件分析 → 缺陷检测 → 上下文分析 → 修复生成 → 结果返回"

class HealthResponse(_UTCBaseModel):
    status: str = "healthy"
    timestamp: datetime = Field(default_factory=utc_now)
    epoch_ms: Optional[int] = None
    version: str = "1.0.0"
    services: Dict[str, str] = {
        "database": "ok",
        "redis": "ok",
        "file_system": "ok"
    }

    def __init__(self, **data):
        super().__init__(**data)
        if self.epoch_ms is None and isinstance(self.timestamp, datetime):
            object.__setattr__(self, 'epoch_ms', epoch_ms(self.timestamp))

# ========== 验证器 ==========
class FileUploadValidator:
    @staticmethod
    def validate_file_extension(filename: str, allowed_extensions: List[str]) -> bool:
        return any(filename.lower().endswith(ext.lower()) for ext in allowed_extensions)

    @staticmethod
    def validate_file_size(size: int, max_size: int) -> bool:
        return size <= max_size

    @staticmethod
    def validate_archive_content(file_path: str, allowed_extensions: List[str]) -> List[str]:
        valid_files = []
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path) as z:
                    for f in z.namelist():
                        if any(f.endswith(ext) for ext in allowed_extensions):
                            valid_files.append(f)
            else:  # .tar.gz
                with tarfile.open(file_path) as t:
                    for f in t.getnames():
                        if any(f.endswith(ext) for ext in allowed_extensions):
                            valid_files.append(f)
        except Exception as e:
            raise ValueError(f"压缩包校验失败: {str(e)}")

        if not valid_files:
            raise ValueError("压缩包中未发现合法C++文件")
        return valid_files

# ========== 分析启动与状态模型 ==========
class AnalysisRequest(_UTCBaseModel):
    analysis_type: str = Field(default="static", description="分析类型")
    config: Optional[Dict[str, Any]] = Field(None, description="分析配置")

class AnalysisStartResponse(BaseResponse):
    analysis_id: Optional[str] = None
    status: str = "starting"
    status_url: Optional[str] = None
    result_url: Optional[str] = None

class AnalysisStatusResponse(BaseResponse):
    analysis_id: Optional[str] = None
    status: str = "not_started"
    progress: int = 0
    result: Optional[Dict[str, Any]] = None
    status_url: Optional[str] = None
    result_url: Optional[str] = None

class AnalysisResultModel(_UTCBaseModel):
    analysis_id: str
    project_id: str
    status: str
    total_issues: int = 0
    severity_distribution: Dict[str, int] = Field(default_factory=dict)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    created_time: datetime
    created_epoch_ms: Optional[int] = None
    completed_time: Optional[datetime] = None
    completed_epoch_ms: Optional[int] = None

    def __init__(self, **data):
        if "created_time" in data and data.get("created_epoch_ms") is None:
            data["created_epoch_ms"] = epoch_ms(data["created_time"])
        if "completed_time" in data and data.get("completed_epoch_ms") is None and data.get("completed_time") is not None:
            data["completed_epoch_ms"] = epoch_ms(data["completed_time"])
        if "created_time" in data and isinstance(data["created_time"], datetime):
            data["created_time"] = _ensure_utc(data["created_time"])
        if "completed_time" in data and isinstance(data["completed_time"], datetime):
            data["completed_time"] = _ensure_utc(data["completed_time"])
        super().__init__(**data)
