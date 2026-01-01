from typing import Dict

class DefectClassifier:
    """极简分类器：根据 message/type 关键词分类"""
    def classify(self, issue: Dict) -> str:
        text = ((issue.get('message') or '') + ' ' + (issue.get('type') or '')).lower()
        if any(k in text for k in ['use-after-free', 'double free', 'memory leak']):
            return 'memory_safety'
        if 'overflow' in text:
            return 'buffer_overflow'
        if any(k in text for k in ['data race', 'deadlock', 'race condition']):
            return 'concurrency'
        if any(k in text for k in ['null deref', 'null pointer', 'nullptr']):
            return 'null_deref'
        return 'other'
