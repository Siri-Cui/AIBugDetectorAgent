"""Agent基类和接口定义
作用：定义所有Agent的基础接口和通用功能
依赖：pydantic（数据验证）、utils.logger（日志系统）
调用关系：被所有具体Agent继承使用
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from utils.logger import log_info, log_error


class AgentStatus(str, Enum):
    """Agent状态枚举"""

    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentResponse(BaseModel):
    """Agent响应结果"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    errors: List[str] = []
    timestamp: datetime = Field(default_factory=datetime.now)


class BaseAgent(ABC):
    """Agent基类 - 所有Agent的父类"""

    def __init__(self, agent_id: str, name: str):
        self.agent_id = agent_id
        self.name = name
        self.status = AgentStatus.IDLE
        self.context: Dict[str, Any] = {}

    @abstractmethod
    async def process(self, task_data: Dict[str, Any]) -> AgentResponse:
        """处理任务的抽象方法 - 每个Agent必须实现"""
        pass

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """获取Agent能力列表 - 每个Agent必须实现"""
        pass

    def set_status(self, status: AgentStatus) -> None:
        """设置Agent状态"""
        self.status = status
        log_info(f"{self.name} 状态变更为: {status.value}")

    def update_context(self, key: str, value: Any) -> None:
        """更新上下文信息"""
        self.context[key] = value
