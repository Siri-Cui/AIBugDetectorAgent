from typing import Dict, Any, List
import os, re
try:
    import yaml
except Exception:
    yaml = None
from utils.logger import log_info, log_error
from config import settings

DEFAULT_RULES = {
    "magic_numbers": ["0","1","-1","2","10","100","1000"],
    "common_fp_keywords": ["todo:", "fixme:", "sample code", "demo"],
    "suspected_fp_keywords": ["heuristic", "may be false positive"],
}

class PatternLibrary:
    """从 YAML 载入规则；缺省时使用内置默认值"""
    def __init__(self, cfg_path: str = None):
        self.cfg_path = cfg_path or os.path.join(settings.PROJECT_ROOT, "configs/false_positive_rules.yaml")
        self._rules = None

    def get_rules(self) -> Dict[str, Any]:
        if self._rules is None:
            self._rules = self._load()
        return self._rules

    def is_common_fp(self, text: str) -> bool:
        t = text.lower()
        for k in self.get_rules().get("common_fp_keywords", []):
            if k in t:
                return True
        return False

    def is_suspected_fp(self, text: str) -> bool:
        t = text.lower()
        for k in self.get_rules().get("suspected_fp_keywords", []):
            if k in t:
                return True
        return False

    def _load(self) -> Dict[str, Any]:
        path = self.cfg_path
        if os.path.exists(path) and yaml is not None:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                return {**DEFAULT_RULES, **data}
            except Exception as e:
                log_error(f"加载规则失败，使用默认: {e}")
        return DEFAULT_RULES.copy()
