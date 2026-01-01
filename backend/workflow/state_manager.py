"""
状态管理器
作用：管理分析流程的状态机，跟踪进度
依赖：enum、typing、utils.logger
调用关系：被orchestrator调用，记录分析各阶段状态
"""
import time
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime
from utils.logger import log_info, log_warning


class AnalysisState(Enum):
    """分析状态枚举"""
    CREATED = "created"                   # 已创建
    UPLOADING = "uploading"               # 正在上传
    UPLOADED = "uploaded"                 # 上传完成
    FILE_ANALYZING = "file_analyzing"     # 文件结构分析中
    CONTEXT_ANALYZING = "context_analyzing"  # 上下文分析中
    STATIC_DETECTING = "static_detecting"    # 静态检测中
    SPECIALIZED_DETECTING = "specialized_detecting"  # 专项检测中
    REPAIR_GENERATING = "repair_generating"  # 生成修复建议中
    COMPLETED = "completed"               # 全部完成
    FAILED = "failed"                     # 失败
    CANCELLED = "cancelled"               # 已取消


class AnalysisProgress:
    """分析进度"""
    
    def __init__(self, analysis_id: str, project_name: str = ""):
        self.analysis_id = analysis_id
        self.project_name = project_name
        self.state = AnalysisState.CREATED
        self.progress_percentage = 0  # 0-100
        self.current_step = ""
        self.total_steps = 0
        self.completed_steps = 0
        self.start_time = datetime.now()
        self.end_time = None
        self.error_message = None
        self.step_details: Dict[str, Dict[str, Any]] = {}
    
    def update_state(self, new_state: AnalysisState, message: str = ""):
        """更新状态"""
        self.state = new_state
        self.current_step = message
        log_info(f"[{self.analysis_id}] 状态更新: {new_state.value} - {message}")
    
    def set_progress(self, percentage: int):
        """设置进度百分比"""
        self.progress_percentage = max(0, min(100, percentage))
    
    def add_step_detail(self, step_name: str, details: Dict[str, Any]):
        """添加步骤详情"""
        self.step_details[step_name] = {
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
    
    def mark_completed(self):
        """标记完成"""
        self.state = AnalysisState.COMPLETED
        self.progress_percentage = 100
        self.end_time = datetime.now()
        log_info(f"[{self.analysis_id}] 分析完成")
    
    def mark_failed(self, error: str):
        """标记失败"""
        self.state = AnalysisState.FAILED
        self.error_message = error
        self.end_time = datetime.now()
        log_warning(f"[{self.analysis_id}] 分析失败: {error}")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于API返回）"""
        duration = None
        if self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        
        return {
            'analysis_id': self.analysis_id,
            'project_name': self.project_name,
            'state': self.state.value,
            'progress_percentage': self.progress_percentage,
            'current_step': self.current_step,
            'total_steps': self.total_steps,
            'completed_steps': self.completed_steps,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': duration,
            'error_message': self.error_message,
            'step_details': self.step_details
        }


class StateManager:
    """状态管理器 - 管理所有分析任务的状态"""
    
    def __init__(self):
        self.progresses: Dict[str, AnalysisProgress] = {}
    
    def create_progress(self, analysis_id: str, project_name: str = "") -> AnalysisProgress:
        """创建新的进度追踪"""
        progress = AnalysisProgress(analysis_id, project_name)
        self.progresses[analysis_id] = progress
        log_info(f"创建分析进度追踪: {analysis_id}")
        return progress
    
    def get_progress(self, analysis_id: str) -> Optional[AnalysisProgress]:
        """获取进度"""
        return self.progresses.get(analysis_id)
    
    def update_progress(
        self,
        analysis_id: str,
        state: AnalysisState = None,
        percentage: int = None,
        message: str = ""
    ) -> bool:
        """更新进度"""
        progress = self.get_progress(analysis_id)
        if not progress:
            log_warning(f"未找到分析进度: {analysis_id}")
            return False
        
        if state:
            progress.update_state(state, message)
        
        if percentage is not None:
            progress.set_progress(percentage)
        
        return True
    
    def complete_analysis(self, analysis_id: str) -> bool:
        """标记分析完成"""
        progress = self.get_progress(analysis_id)
        if progress:
            progress.mark_completed()
            return True
        return False
    
    def fail_analysis(self, analysis_id: str, error: str) -> bool:
        """标记分析失败"""
        progress = self.get_progress(analysis_id)
        if progress:
            progress.mark_failed(error)
            return True
        return False
    
    def get_all_progresses(self) -> List[Dict[str, Any]]:
        """获取所有进度（转为字典列表）"""
        return [p.to_dict() for p in self.progresses.values()]
    
    def cleanup_old_progresses(self, hours: int = 24):
        """清理旧的进度记录"""
        now = datetime.now()
        to_remove = []
        
        for analysis_id, progress in self.progresses.items():
            if progress.end_time:
                age = (now - progress.end_time).total_seconds() / 3600
                if age > hours:
                    to_remove.append(analysis_id)
        
        for analysis_id in to_remove:
            del self.progresses[analysis_id]
            log_info(f"清理旧进度记录: {analysis_id}")
        
        return len(to_remove)
