# backend/services/analysis_service.py
"""分析业务服务：查询/保存分析结果，与 CRUD 打通（统一UTC tz-aware + ISO/Z + epoch_ms）"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from database.crud import ProjectCRUD, AnalysisCRUD
from utils.logger import log_info, log_error
from config import settings  # 确保 config.py 定义了 RESULTS_DIR 等路径


# ---------- UTC / 序列化工具 ----------
def utc_now() -> datetime:
    """返回 tz-aware 的 UTC 时间"""
    return datetime.now(timezone.utc)

def to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """naive -> 视为UTC；aware -> 统一到UTC；None原样返回"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def iso_z(dt: Optional[datetime]) -> Optional[str]:
    """统一序列化为 ISO8601，UTC 且以 Z 结尾"""
    if dt is None:
        return None
    dtu = to_utc_aware(dt)
    return dtu.isoformat().replace("+00:00", "Z")

def epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    dtu = to_utc_aware(dt)
    return int(dtu.timestamp() * 1000)


# ---------- JSON 解析容错 ----------
def _try_json_loads(v: Any) -> Optional[Dict[str, Any]]:
    """尽可能把任意值解析成 dict（用于 DB result 兼容字符串 JSON 的情况）"""
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, (bytes, bytearray)):
        try:
            return json.loads(v.decode("utf-8"))
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None
    return None


class AnalysisService:
    """分析业务服务"""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.project_crud = ProjectCRUD(db_session)
        self.analysis_crud = AnalysisCRUD(db_session)

    # -------- 项目/分析记录查询 --------

    def get_project(self, project_id: str) -> Optional[Any]:
        """获取项目信息"""
        try:
            return self.project_crud.get_project(project_id)
        except Exception as e:
            log_error(f"获取项目失败: {str(e)}")
            return None

    def get_latest_analysis(self, project_id: str) -> Optional[Any]:
        """获取项目最新的分析记录"""
        try:
            return self.analysis_crud.get_latest_analysis_by_project(project_id)
        except Exception as e:
            log_error(f"获取最新分析记录失败: {str(e)}")
            return None

    def get_analysis_result(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """
        获取分析结果详情（容错版）：
        1) 优先从文件系统：<RESULTS_DIR>/<analysis_id>/analysis_result.json
        2) 文件不存在则回退到 DB 字段（result 可为 dict 或 JSON 字符串）
        3) 最后兜底返回记录的基础信息（含统计与时间，时间统一UTC）
        """
        try:
            # 先查 DB，拿到基本记录信息
            analysis = self.analysis_crud.get_analysis(analysis_id)
            if not analysis:
                return None

            result_dir = os.path.join(settings.RESULTS_DIR, analysis_id)
            result_file = os.path.join(result_dir, "analysis_result.json")

            # 1) 文件优先
            if os.path.exists(result_file):
                try:
                    with open(result_file, "r", encoding="utf-8") as f:
                        detailed_result = json.load(f)
                    return detailed_result
                except Exception as fe:
                    log_error(f"读取文件结果失败（将回退 DB）: {result_file} - {fe}")

            # 2) 回退 DB：解析 result 字段
            parsed_result = _try_json_loads(getattr(analysis, "result", None))

            # 统一处理时间为 UTC + 补 epoch_ms
            st = to_utc_aware(getattr(analysis, "start_time", None))
            et = to_utc_aware(getattr(analysis, "end_time", None))

            base: Dict[str, Any] = {
                "analysis_id": getattr(analysis, "id", analysis_id),
                "project_id": getattr(analysis, "project_id", None),
                "status": getattr(analysis, "status", "unknown"),

                # 统一 UTC 时间（ISO Z + epoch_ms）
                "start_time": iso_z(st),
                "start_epoch_ms": epoch_ms(st),
                "end_time": iso_z(et),
                "end_epoch_ms": epoch_ms(et),

                "duration": getattr(analysis, "duration", None),
                "total_defects": getattr(analysis, "total_defects", 0),
                "critical_defects": getattr(analysis, "critical_defects", 0),
                "high_defects": getattr(analysis, "high_defects", 0),
                "medium_defects": getattr(analysis, "medium_defects", 0),
                "low_defects": getattr(analysis, "low_defects", 0),
            }

            if parsed_result is not None:
                # 若 DB 里保存了完整报告（或其子集），并能解析出 dict，则合并进去
                if isinstance(parsed_result, dict):
                    # 注意：parsed_result 中如包含时间字段，通常是字符串；不再强制改写，交给前端工具转时区
                    base.update(parsed_result)
                else:
                    base["result"] = parsed_result
            else:
                # 没有 result / 解析失败，也保持一个结构化返回
                base.setdefault("result", {})
                # 附带 error_message 方便排查
                em = getattr(analysis, "error_message", None)
                if em:
                    base["error_message"] = em

            return base

        except Exception as e:
            log_error(f"获取分析结果失败: {str(e)}")
            return None

    # --------（可选）提供工具方法：路径/摘要读取 --------

    def get_result_dir(self, analysis_id: str) -> str:
        return os.path.join(settings.RESULTS_DIR, analysis_id)

    def load_summary_from_file(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """若存在 data/results/<analysis_id>/summary.json 则读取供 status 附带摘要使用"""
        try:
            p = os.path.join(self.get_result_dir(analysis_id), "summary.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            log_error(f"读取 summary.json 失败: {str(e)}")
        return None

    # -------- 结果落盘 --------

    async def save_analysis_report(self, analysis_id: str, report: Dict[str, Any]) -> None:
        """
        保存分析报告到文件系统：
        - 完整报告：analysis_result.json
        - 摘要信息：summary.json
        说明：
        - 仅负责文件落盘；DB 持久化由 AnalysisCRUD 负责（调用方已处理）
        - 目录不存在会自动创建
        """
        try:
            result_dir = self.get_result_dir(analysis_id)
            os.makedirs(result_dir, exist_ok=True)

            # 完整报告
            report_file = os.path.join(result_dir, "analysis_result.json")
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            # 归纳摘要（保持键名与你路由/前端一致），时间用UTC
            now = utc_now()
            summary = {
                "analysis_id": analysis_id,
                "total_issues": report.get("summary", {}).get("total_issues", 0),
                "severity_distribution": report.get("summary", {}).get("severity_distribution", {}),
                "timestamp": iso_z(now),
                "epoch_ms": epoch_ms(now),
            }
            summary_file = os.path.join(result_dir, "summary.json")
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            log_info(f"分析报告已保存: {result_dir}")

        except Exception as e:
            log_error(f"保存分析报告失败: {str(e)}")
            raise
