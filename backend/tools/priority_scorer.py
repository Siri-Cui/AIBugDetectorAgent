from typing import Dict, Any, Tuple
import os

try:
    import yaml
except Exception:
    yaml = None
from utils.logger import log_error

try:
    from config import settings

    PROJECT_ROOT = getattr(settings, "PROJECT_ROOT", os.getcwd())
except Exception:
    PROJECT_ROOT = os.getcwd()

DEFAULT_WEIGHTS = {"severity": 40, "category": 30, "impact": 15, "confidence": 15}
SEV_BASE = {"critical": 40, "high": 30, "medium": 20, "low": 10, "info": 5}
CATEGORY_W = {
    "memory_safety": 30,
    "concurrency": 25,
    "null_deref": 20,
    "buffer_overflow": 25,
    "other": 10,
}


def _normalize_category(raw: str, message: str) -> str:
    """把各种工具的原生类别统一映射为高层大类"""
    r = (raw or "").lower()
    m = (message or "").lower()
    if any(k in r for k in ("deadlock", "race", "thread", "concurrency")):
        return "concurrency"
    if "use-after" in r or "double free" in r or "uaf" in r:
        return "memory_safety"
    if "null" in r or "nullptr" in r or "null deref" in r:
        return "null_deref"
    if "overflow" in r:
        return "buffer_overflow"
    # 根据 message 再判断
    if any(k in m for k in ("deadlock", "lock order", "atomic", "tsan")):
        return "concurrency"
    if any(k in m for k in ("use-after-free", "double free", "uaf")):
        return "memory_safety"
    if "null" in m or "nullptr" in m:
        return "null_deref"
    if "overflow" in m:
        return "buffer_overflow"
    return "other"


class PriorityScorer:
    """多维度优先级评分（迭代6）"""

    def __init__(self, cfg_path: str = None):
        cfg_path = cfg_path or os.path.join(
            PROJECT_ROOT, "configs/priority_weights.yaml"
        )
        self.weights = self._load_weights(cfg_path)

    def score(
        self, issue: Dict[str, Any], context: Dict[str, Any]
    ) -> Tuple[float, Dict[str, float], str]:
        sev = (issue.get("severity") or "medium").lower()
        norm_cat = _normalize_category(
            issue.get("category") or "", issue.get("message") or ""
        )
        depth = int(issue.get("call_depth") or 0)
        on_critical_path = bool(issue.get("on_critical_path") or False)
        dyn_confirmed = bool(issue.get("dynamic_confirmed") or False)
        multi_tools = int(issue.get("detected_by_tools") or 1)

        # 1) 基础分
        s_sev = SEV_BASE.get(sev, 20)
        s_cat = CATEGORY_W.get(norm_cat, CATEGORY_W["other"])

        # 2) 影响范围
        s_impact = min(10, max(0, depth * 2))
        if on_critical_path:
            s_impact += 5

        # 3) 置信度
        s_conf = (15 if dyn_confirmed else 0) + (
            10 if multi_tools >= 2 else (5 if multi_tools == 1 else 0)
        )

        # 4) 加权汇总 - ✅ 修复: 先计算加权分数
        w = self.weights
        weighted_sev = s_sev * (w["severity"] / 40.0)
        weighted_cat = s_cat * (w["category"] / 30.0)
        weighted_impact = s_impact * (w["impact"] / 15.0)
        weighted_conf = s_conf * (w["confidence"] / 15.0)
        
        total = weighted_sev + weighted_cat + weighted_impact + weighted_conf

        # ✅ 修复: 使用已定义的加权变量
        breakdown = {
            "severity": round(weighted_sev, 2),
            "category": round(weighted_cat, 2),
            "impact": round(weighted_impact, 2),
            "confidence": round(weighted_conf, 2),
        }

        reason = self._reason(
            sev, norm_cat, on_critical_path, dyn_confirmed, multi_tools
        )
        return round(total, 2), breakdown, reason

    def _load_weights(self, path: str):
        if os.path.exists(path) and yaml is not None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                loaded_weights = data.get("weights", {})    
                return {**DEFAULT_WEIGHTS, **data}
            except Exception as e:
                log_error(f"加载优先级权重失败，使用默认: {e}")
        return DEFAULT_WEIGHTS.copy()

    def _reason(self, sev: str, cat: str, on_cp: bool, dyn: bool, tools: int) -> str:
        parts = [f"严重度={sev}", f"类型={cat}"]
        if on_cp:
            parts.append("关键路径")
        if dyn:
            parts.append("动态确认")
        if tools >= 2:
            parts.append("多工具一致")
        return "，".join(parts) or "综合得分"
