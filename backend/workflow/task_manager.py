"""
任务管理器
作用：管理多个检测任务的并行执行和依赖关系
依赖：asyncio、utils.logger
调用关系：被orchestrator调用，协调多个Agent并行工作
"""
import asyncio
from typing import Dict, List, Any, Callable, Optional
from enum import Enum
from utils.logger import log_info, log_error, log_warning


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 正在执行
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消


class Task:
    """单个任务"""
    
    def __init__(
        self,
        task_id: str,
        name: str,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        dependencies: List[str] = None,
        priority: int = 0
    ):
        self.task_id = task_id
        self.name = name
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.dependencies = dependencies or []
        self.priority = priority
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
        self.start_time = None
        self.end_time = None
    
    async def execute(self) -> Any:
        """执行任务"""
        try:
            self.status = TaskStatus.RUNNING
            log_info(f"任务开始执行: {self.name}")
            
            # 执行异步或同步函数
            if asyncio.iscoroutinefunction(self.func):
                self.result = await self.func(*self.args, **self.kwargs)
            else:
                self.result = self.func(*self.args, **self.kwargs)
            
            self.status = TaskStatus.COMPLETED
            log_info(f"任务完成: {self.name}")
            return self.result
            
        except Exception as e:
            self.status = TaskStatus.FAILED
            self.error = str(e)
            log_error(f"任务失败 {self.name}: {str(e)}")
            raise


class TaskManager:
    """任务管理器 - 管理多个任务的并行执行"""
    
    def __init__(self, max_concurrent_tasks: int = 5):
        """初始化任务管理器
        
        Args:
            max_concurrent_tasks: 最大并发任务数
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.tasks: Dict[str, Task] = {}
        self.completed_tasks: Dict[str, Any] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
    
    def add_task(
        self,
        task_id: str,
        name: str,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        dependencies: List[str] = None,
        priority: int = 0
    ) -> Task:
        """添加任务到管理器
        
        Args:
            task_id: 任务唯一ID
            name: 任务名称
            func: 要执行的函数（可以是async函数）
            args: 位置参数
            kwargs: 关键字参数
            dependencies: 依赖的任务ID列表（这些任务完成后才能执行）
            priority: 优先级（数字越大优先级越高）
            
        Returns:
            Task对象
        """
        task = Task(
            task_id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
            dependencies=dependencies,
            priority=priority
        )
        
        self.tasks[task_id] = task
        log_info(f"添加任务: {name} (ID: {task_id})")
        
        return task
    
    async def execute_all(self) -> Dict[str, Any]:
        """执行所有任务（并行执行，考虑依赖关系）
        
        Returns:
            所有任务的结果字典 {task_id: result}
        """
        log_info(f"开始执行 {len(self.tasks)} 个任务")
        
        # 按优先级排序任务
        sorted_tasks = sorted(
            self.tasks.values(),
            key=lambda t: t.priority,
            reverse=True
        )
        
        # 创建所有任务的协程
        task_coroutines = []
        for task in sorted_tasks:
            task_coroutines.append(self._execute_task_with_deps(task))
        
        # 并行执行所有任务
        await asyncio.gather(*task_coroutines, return_exceptions=True)
        
        log_info("所有任务执行完成")
        
        return self.completed_tasks
    
    async def _execute_task_with_deps(self, task: Task):
        """执行单个任务（等待依赖完成）"""
        # 1. 等待依赖任务完成
        if task.dependencies:
            log_info(f"任务 {task.name} 等待依赖: {task.dependencies}")
            await self._wait_for_dependencies(task.dependencies)
        
        # 2. 获取信号量（限制并发数）
        async with self.semaphore:
            try:
                result = await task.execute()
                self.completed_tasks[task.task_id] = result
                return result
            except Exception as e:
                log_error(f"任务执行失败 {task.name}: {str(e)}")
                self.completed_tasks[task.task_id] = None
                return None
    
    async def _wait_for_dependencies(self, dependencies: List[str]):
        """等待依赖任务完成"""
        while True:
            all_completed = all(
                dep_id in self.completed_tasks
                for dep_id in dependencies
            )
            
            if all_completed:
                break
            
            # 每100ms检查一次
            await asyncio.sleep(0.1)
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        task = self.tasks.get(task_id)
        return task.status if task else None
    
    def get_completed_results(self) -> Dict[str, Any]:
        """获取所有已完成任务的结果"""
        return self.completed_tasks.copy()
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self.tasks.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            log_warning(f"任务已取消: {task.name}")
            return True
        return False
    
    def clear(self):
        """清空所有任务"""
        self.tasks.clear()
        self.completed_tasks.clear()
        log_info("任务管理器已清空")
