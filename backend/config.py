# backend/config.py
from typing import List
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"   # 根目录 .env（避免 systemd 工作目录不同导致读不到）

def _parse_list(v):
    if v is None:
        return v
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if s.startswith("["):
        return json.loads(s)        # JSON 数组
    # 兼容逗号分隔
    return [x.strip() for x in s.split(",") if x.strip()]

class Settings(BaseSettings):
    """应用配置"""
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # 服务器配置
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="BACKEND_PORT")
    DEBUG: bool = Field(default=False, env="DEBUG")

    # 数据库配置
    DATABASE_URL: str = Field(default="sqlite:///./data/ai_bug_detector.db", env="DATABASE_URL")

    # GLM-4 / LLM 配置
    ZHIPU_API_KEY: str = Field(default="", env="ZHIPU_API_KEY")
    ZHIPU_BASE_URL: str = Field(default="https://open.bigmodel.cn/api/paas/v4/", env="ZHIPU_BASE_URL")
    # 模型相关（你 .env 里有 MODEL_NAME=glm-4）
    MODEL_NAME: str = Field(default="glm-4", env="MODEL_NAME")

    # 路径与存储
    # 运行目录（你 .env 里有 PROJECT_ROOT=/home/wsh/ai-bug-detector）
    PROJECT_ROOT: str = Field(default=str(PROJECT_ROOT), env="PROJECT_ROOT")

    UPLOAD_DIR: str = Field(default="./data/uploads", env="UPLOAD_DIR")
    RESULTS_DIR: str = Field(default="./data/results", env="RESULTS_DIR")
    # 处理目录（你 .env 里有 PROCESSED_DIR）
    PROCESSED_DIR: str = Field(default="./data/processed", env="PROCESSED_DIR")

    MAX_FILE_SIZE: int = Field(default=50 * 1024 * 1024, env="MAX_FILE_SIZE")
    ALLOWED_EXTENSIONS: List[str] = Field(default=[".cpp",".hpp",".h",".c",".cc",".cxx"], env="ALLOWED_EXTENSIONS")

    # 日志
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FILE: str = Field(default="./data/logs/app.log", env="LOG_FILE")

    # CORS
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        env="ALLOWED_ORIGINS"
    )

    # 可选：缓存/鉴权（你的 .env 里有）
    REDIS_URL: str = Field(default="", env="REDIS_URL")
    SECRET_KEY: str = Field(default="", env="SECRET_KEY")

    @field_validator("ALLOWED_EXTENSIONS", mode="before")
    def _v_ext(cls, v): return _parse_list(v)

    @field_validator("ALLOWED_ORIGINS", mode="before")
    def _v_origins(cls, v): return _parse_list(v)

settings = Settings()

# =========================
# ★ 路径拉直 + 目录确保（强烈建议）★
# 放在文件末尾，避免 systemd/不同工作目录导致的相对路径问题
# =========================
def _abs(p: str) -> str:
    if not p:
        return p
    pp = Path(p)
    return str(pp if pp.is_absolute() else (PROJECT_ROOT / pp).resolve())

# 拉直关键路径（相对 → 绝对）
settings.UPLOAD_DIR    = _abs(settings.UPLOAD_DIR)
settings.PROCESSED_DIR = _abs(settings.PROCESSED_DIR)
settings.RESULTS_DIR   = _abs(settings.RESULTS_DIR)
settings.LOG_FILE      = _abs(settings.LOG_FILE)

# sqlite:/// 相对路径 → 绝对路径（仅当不是 sqlite://// 开头时）
if settings.DATABASE_URL.startswith("sqlite:///") and not settings.DATABASE_URL.startswith("sqlite:////"):
    db_rel = settings.DATABASE_URL.replace("sqlite:///", "", 1)
    settings.DATABASE_URL = f"sqlite:////{_abs(db_rel).lstrip('/')}"

# 创建目录（不会报错）
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.PROCESSED_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.RESULTS_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
