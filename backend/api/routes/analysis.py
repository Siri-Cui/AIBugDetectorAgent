"""分析任务路由（统一UTC时间 + epoch_ms + 动态分析支持）"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncio

# 导入部分
from api.models import AnalysisRequest, ApiResponse
from api.dependencies import get_database
from services.analysis_service import AnalysisService
from database.crud import AnalysisCRUD
from workflow.orchestrator import Orchestrator
from agents.validation_agent import ValidationAgent
from utils.logger import log_info, log_error
from database.connection import get_db

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# 存储正在运行的分析任务
running_analyses: Dict[str, Dict[str, Any]] = {}
dynamic_analysis_tasks: Dict[str, Dict[str, Any]] = {}

# ---------- UTC 工具 ----------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)

# ---- 统一响应外壳 ----
def _api_response(data: Dict[str, Any]) -> Dict[str, Any]:
    now = utc_now()
    return {
        "success": True,
        "timestamp": now.isoformat(),
        "epoch_ms": epoch_ms(now),
        "data": data,
    }

def _build_urls(project_id: str, analysis_id: str) -> Dict[str, str]:
    return {
        "status_url": f"/api/analysis/status/{project_id}",
        "result_url": f"/api/analysis/result/{analysis_id}",
    }

# ========== 原有静态分析路由（保持不变）==========

@router.post("/start/{project_id}")
async def start_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    request: Optional[AnalysisRequest] = None,
    db: Session = Depends(get_database),
):
    """启动项目分析"""
    try:
        log_info(f"收到分析请求: {project_id}")

        analysis_service = AnalysisService(db)
        project = analysis_service.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")

        if project_id in running_analyses:
            analysis_id_existing = running_analyses[project_id]["analysis_id"]
            urls = _build_urls(project_id, analysis_id_existing)
            return _api_response({
                "message": "分析已在进行中",
                "project_id": project_id,
                "analysis_id": analysis_id_existing,
                "status": "running",
                **urls,
            })

        analysis_crud = AnalysisCRUD(db)
        analysis_record = analysis_crud.create_analysis(
            project_id=project_id,
            analysis_type="static",
            status="starting",
            start_time=utc_now(),
        )
        analysis_id = analysis_record.id

        orchestrator = Orchestrator(db)
        background_tasks.add_task(run_analysis_task, project_id, orchestrator, analysis_id)

        running_analyses[project_id] = {
            "analysis_id": analysis_id,
            "status": "starting",
            "progress": 0,
            "message": "分析任务初始化…",
        }

        urls = _build_urls(project_id, analysis_id)
        return _api_response({
            "message": "分析任务已启动",
            "project_id": project_id,
            "analysis_id": analysis_id,
            "status": "starting",
            **urls,
        })

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"启动分析失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动分析失败: {str(e)}")

@router.get("/status/{project_id}")
async def get_analysis_status(project_id: str, db: Session = Depends(get_database)):
    """获取分析状态"""
    try:
        if project_id in running_analyses:
            t = running_analyses[project_id]
            urls = _build_urls(project_id, t["analysis_id"])
            return _api_response({
                "project_id": project_id,
                "analysis_id": t["analysis_id"],
                "status": t.get("status", "running"),
                "progress": t.get("progress", 0),
                "message": t.get("message", "分析进行中..."),
                **urls,
            })

        analysis_service = AnalysisService(db)
        latest_analysis = analysis_service.get_latest_analysis(project_id)

        if not latest_analysis:
            dummy_id = f"analysis_{project_id}_none"
            urls = _build_urls(project_id, dummy_id)
            return _api_response({
                "project_id": project_id,
                "status": "not_started",
                "message": "尚未开始分析",
                **urls,
            })

        analysis_id = latest_analysis.id
        status = latest_analysis.status
        urls = _build_urls(project_id, analysis_id)

        resp = {
            "project_id": project_id,
            "analysis_id": analysis_id,
            "status": status,
            "progress": 100 if status == "completed" else 0,
            "message": "分析已完成" if status == "completed" else ("分析失败" if status == "failed" else "分析状态更新"),
            **urls,
        }

        if status == "completed":
            result = analysis_service.get_analysis_result(analysis_id)
            if isinstance(result, dict):
                summary = result.get("summary")
                if isinstance(summary, dict):
                    resp["summary"] = summary

        return _api_response(resp)

    except Exception as e:
        log_error(f"获取分析状态失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")

@router.get("/result/{analysis_id}")
async def get_analysis_result(analysis_id: str, db: Session = Depends(get_database)):
    """获取分析结果详情"""
    try:
        analysis_service = AnalysisService(db)
        result = analysis_service.get_analysis_result(analysis_id)

        if not result:
            raise HTTPException(status_code=404, detail="分析结果不存在")

        return _api_response(result)

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"获取分析结果失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取结果失败: {str(e)}")

@router.get("/result/by-project/{project_id}")
async def get_latest_result_by_project(project_id: str, db: Session = Depends(get_database)):
    """按项目获取最新分析结果"""
    try:
        svc = AnalysisService(db)
        latest = svc.get_latest_analysis(project_id)
        if not latest:
            raise HTTPException(status_code=404, detail="该项目尚无任何分析记录")

        data = svc.get_analysis_result(latest.id)
        if not data:
            raise HTTPException(status_code=404, detail="分析结果不存在或尚未生成")

        urls = _build_urls(project_id, latest.id)
        if isinstance(data, dict):
            data.setdefault("_links", urls)

        return _api_response(data)

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"按项目获取最新结果失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取结果失败: {str(e)}")

@router.delete("/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    db: Session = Depends(get_db)
):
    """删除分析记录"""
    try:
        analysis_crud = AnalysisCRUD(db)
        success = analysis_crud.delete_analysis(analysis_id)
        
        if success:
            return ApiResponse(
                success=True,
                data={"message": "分析记录已删除", "analysis_id": analysis_id}
            )
        else:
            return ApiResponse(
                success=False,
                data={"error": "分析记录不存在或删除失败"}
            )
            
    except Exception as e:
        log_error(f"删除分析记录失败: {str(e)}")
        return ApiResponse(
            success=False,
            data={"error": str(e)}
        )

async def run_analysis_task(project_id: str, orchestrator: Orchestrator, analysis_id: str):
    """后台分析任务"""
    try:
        log_info(f"开始后台分析任务: {project_id}, analysis_id: {analysis_id}")

        running_analyses[project_id]["status"] = "running"
        running_analyses[project_id]["progress"] = 10

        # ⭐ 改为调用完整分析（静态+动态+交叉验证）
        result = await orchestrator.start_full_analysis_with_dynamic(
            project_id, 
            analysis_id=analysis_id,
            enable_dynamic=True,  # 启用动态分析
            dynamic_config={
                'tools': ['valgrind_memcheck', 'asan'],
                'sanitizers': ['address', 'undefined'],
                'timeout': 300,
                'clean_build': True,
                'line_tolerance': 5
            }
        )

        if result.get("success", False):
            running_analyses[project_id]["status"] = "completed"
            running_analyses[project_id]["progress"] = 100
            running_analyses[project_id]["message"] = result.get("message", "分析完成")
        else:
            running_analyses[project_id]["status"] = "failed"
            running_analyses[project_id]["message"] = result.get("error", "分析失败")

        log_info(f"分析任务完成: {project_id}")

    except Exception as e:
        log_error(f"分析任务异常: {str(e)}", exc_info=True)
        running_analyses[project_id]["status"] = "failed"
        running_analyses[project_id]["message"] = f"分析异常: {str(e)}"

# ========== ⭐ 新增：动态分析路由 ⭐ ==========

class DynamicAnalysisConfig(BaseModel):
    """动态分析配置模型"""
    tools: List[str] = ['valgrind_memcheck', 'asan']
    sanitizers: List[str] = ['address', 'undefined']
    timeout: int = 300
    clean_build: bool = True
    executable_args: List[str] = []
    line_tolerance: int = 5
    build_dir: Optional[str] = None
    output_dir: Optional[str] = None


@router.post("/dynamic/{project_id}")  # ⭐ 修正：去掉重复前缀
async def start_dynamic_analysis(
    project_id: str,
    config: DynamicAnalysisConfig,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_database)  # ⭐ 添加数据库依赖
):
    """启动动态分析任务"""
    try:
        log_info(f"收到动态分析请求: project_id={project_id}")
        
        # 检查项目是否存在
        analysis_service = AnalysisService(db)
        project = analysis_service.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 创建分析记录
        analysis_crud = AnalysisCRUD(db)
        analysis_record = analysis_crud.create_analysis(
            project_id=project_id,
            analysis_type="dynamic",
            status="starting",
            start_time=utc_now(),
        )
        analysis_id = analysis_record.id
        
        # 初始化任务状态
        task_id = f"dynamic_{project_id}_{analysis_id}"
        dynamic_analysis_tasks[task_id] = {
            'status': 'pending',
            'project_id': project_id,
            'analysis_id': analysis_id,
            'started_at': None,
            'completed_at': None,
            'result': None
        }
        
        # 后台执行
        background_tasks.add_task(
            execute_dynamic_analysis_background,
            task_id,
            project_id,
            analysis_id,
            config,
            db
        )
        
        urls = _build_urls(project_id, analysis_id)
        return _api_response({
            'task_id': task_id,
            'project_id': project_id,
            'analysis_id': analysis_id,
            'status': 'pending',
            'message': '动态分析任务已启动',
            **urls
        })
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"启动动态分析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def execute_dynamic_analysis_background(
    task_id: str,
    project_id: str,
    analysis_id: str,
    config: DynamicAnalysisConfig,
    db: Session  # ⭐ 添加数据库参数
):
    """后台执行动态分析任务"""
    try:
        import time
        
        dynamic_analysis_tasks[task_id]['status'] = 'running'
        dynamic_analysis_tasks[task_id]['started_at'] = time.time()
        
        # ⭐ 通过 Orchestrator 执行（保持架构一致性）
        orchestrator = Orchestrator(db)
        
        config_dict = {
            'tools': config.tools,
            'sanitizers': config.sanitizers,
            'timeout': config.timeout,
            'clean_build': config.clean_build,
            'executable_args': config.executable_args,
            'line_tolerance': config.line_tolerance,
            'build_dir': config.build_dir,
            'output_dir': config.output_dir or f'/tmp/dynamic_analysis_{project_id}'
        }
        
        result = await orchestrator.start_dynamic_analysis(
            project_id,
            analysis_id,
            config_dict
        )
        
        # 更新任务状态
        dynamic_analysis_tasks[task_id]['status'] = 'completed' if result.get('success') else 'failed'
        dynamic_analysis_tasks[task_id]['completed_at'] = time.time()
        dynamic_analysis_tasks[task_id]['result'] = result
        
        log_info(f"动态分析任务完成: {task_id}")
        
    except Exception as e:
        log_error(f"动态分析任务执行失败: {e}", exc_info=True)
        dynamic_analysis_tasks[task_id]['status'] = 'failed'
        dynamic_analysis_tasks[task_id]['error'] = str(e)


@router.get("/dynamic/status/{task_id}")  # ⭐ 修正路径
async def get_dynamic_analysis_status(task_id: str):
    """查询动态分析任务状态"""
    try:
        if task_id not in dynamic_analysis_tasks:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        task_info = dynamic_analysis_tasks[task_id]
        
        response = {
            'task_id': task_id,
            'project_id': task_info['project_id'],
            'analysis_id': task_info.get('analysis_id'),
            'status': task_info['status'],
            'started_at': task_info['started_at'],
            'completed_at': task_info['completed_at']
        }
        
        if task_info['status'] == 'completed' and task_info['result']:
            result = task_info['result']
            response['summary'] = {
                'total_issues': result.get('total_issues', 0),
                'success': result.get('success', False)
            }
        
        return _api_response(response)
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"查询任务状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dynamic/result/{task_id}")  # ⭐ 修正路径
async def get_dynamic_analysis_result(task_id: str):
    """获取动态分析完整结果"""
    try:
        if task_id not in dynamic_analysis_tasks:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        task_info = dynamic_analysis_tasks[task_id]
        
        if task_info['status'] != 'completed':
            raise HTTPException(
                status_code=400,
                detail=f"任务尚未完成，当前状态: {task_info['status']}"
            )
        
        return _api_response({
            'task_id': task_id,
            'project_id': task_info['project_id'],
            'analysis_id': task_info.get('analysis_id'),
            'result': task_info['result']
        })
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"获取分析结果失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cross-validate/{project_id}")  # ⭐ 修正路径
async def cross_validate_results(
    project_id: str,
    static_task_id: str,
    dynamic_task_id: str,
    tolerance: int = 5,
    db: Session = Depends(get_database)  # ⭐ 添加数据库依赖
):
    """对静态和动态分析结果进行交叉验证"""
    try:
        log_info(f"开始交叉验证: project_id={project_id}")
        
        # 获取静态分析结果
        analysis_service = AnalysisService(db)
        static_result = analysis_service.get_analysis_result(static_task_id)
        if not static_result:
            raise HTTPException(status_code=404, detail="静态分析结果不存在")
        
        static_issues = static_result.get('issues', [])
        
        # 获取动态分析结果
        if dynamic_task_id not in dynamic_analysis_tasks:
            raise HTTPException(status_code=404, detail="动态分析任务不存在")
        
        dynamic_task = dynamic_analysis_tasks[dynamic_task_id]
        if dynamic_task['status'] != 'completed':
            raise HTTPException(status_code=400, detail="动态分析任务尚未完成")
        
        dynamic_issues = dynamic_task['result'].get('result', {}).get('dynamic_issues', [])
        
        # 执行交叉验证
        validation_agent = ValidationAgent()
        validation_result = await validation_agent.cross_validate_with_dynamic(
            static_issues,
            dynamic_issues,
            tolerance
        )
        
        if not validation_result.get('success'):
            raise HTTPException(status_code=500, detail="交叉验证失败")
        
        report = validation_result.get('validation_report', {})
        
        return _api_response({
            'project_id': project_id,
            'validation_result': validation_result,
            'summary': {
                'high_confidence_count': len(report.get('high_confidence_issues', [])),
                'medium_confidence_count': len(report.get('medium_confidence_issues', [])),
                'low_confidence_count': len(report.get('low_confidence_issues', [])),
                'recommendations': report.get('recommendations', [])
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"交叉验证失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
