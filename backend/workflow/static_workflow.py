"""静态分析工作流
作用：定义静态分析的具体流程
依赖：utils.logger
调用关系：被orchestrator使用
"""
from typing import Dict, List, Any
from utils.logger import log_info, log_error


class StaticWorkflow:
    """静态分析工作流"""
    
    def __init__(self):
        self.workflow_steps = [
            'file_analysis',
            'static_detection', 
            'ai_analysis',
            'report_generation'
        ]
    
    def get_workflow_steps(self) -> List[str]:
        """获取工作流步骤"""
        return self.workflow_steps
    
    def validate_step_result(self, step_name: str, result: Dict[str, Any]) -> bool:
        """验证步骤结果"""
        if not isinstance(result, dict):
            return False
        
        if not result.get('success', False):
            log_error(f"工作流步骤 {step_name} 失败: {result.get('message', 'Unknown error')}")
            return False
        
        return True
    
    def get_next_step(self, current_step: str) -> str:
        """获取下一步骤"""
        try:
            current_index = self.workflow_steps.index(current_step)
            if current_index < len(self.workflow_steps) - 1:
                return self.workflow_steps[current_index + 1]
            return None
        except ValueError:
            return None