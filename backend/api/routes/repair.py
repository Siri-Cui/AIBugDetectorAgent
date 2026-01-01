# -*- coding: utf-8 -*-
"""
修复建议API路由
作用：提供修复建议的查询、预览、应用接口
依赖：fastapi、services.repair_service、database.connection
调用关系：被main.py注册到FastAPI应用
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from api.dependencies import get_database
from services.repair_service import RepairService
from services.analysis_service import AnalysisService
from utils.logger import log_info, log_error

router = APIRouter(prefix="/api/repair", tags=["repair"])


@router.get("/{analysis_id}")
async def get_repair_suggestions(
    analysis_id: str,
    db: Session = Depends(get_database)
):
    """获取分析的所有修复建议"""
    try:
        repair_service = RepairService(db)
        result = repair_service.get_repair_suggestions(analysis_id)
        
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('error', '获取失败'))
        
        return {
            "success": True,
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"获取修复建议失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{analysis_id}/{repair_id}")
async def get_repair_detail(
    analysis_id: str,
    repair_id: str,
    db: Session = Depends(get_database)
):
    """获取单个修复建议的详细信息"""
    try:
        repair_service = RepairService(db)
        result = repair_service.get_repair_detail(analysis_id, repair_id)
        
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('error', '修复建议不存在'))
        
        return {
            "success": True,
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"获取修复详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{analysis_id}/{repair_id}/apply")
async def apply_repair(
    analysis_id: str,
    repair_id: str,
    project_id: str = Query(..., description="项目ID"),
    dry_run: bool = Query(False, description="是否仅预览"),
    db: Session = Depends(get_database)
):
    """应用修复补丁"""
    try:
        # 获取项目路径
        analysis_service = AnalysisService(db)
        project = analysis_service.get_project(project_id)
        
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 构造项目路径（需要从数据库的上传路径推断）
        from config import settings
        project_path = f"{settings.UPLOAD_DIR}/{project_id}/extracted"
        
        repair_service = RepairService(db)
        result = repair_service.apply_repair(
            analysis_id,
            repair_id,
            project_path,
            dry_run
        )
        
        if not result.get('success'):
            raise HTTPException(status_code=400, detail=result.get('error', '应用失败'))
        
        return {
            "success": True,
            "message": result.get('message'),
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"应用修复失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{analysis_id}/batch-apply")
async def batch_apply_repairs(
    analysis_id: str,
    repair_ids: List[str],
    project_id: str = Query(..., description="项目ID"),
    dry_run: bool = Query(False, description="是否仅预览"),
    db: Session = Depends(get_database)
):
    """批量应用修复补丁"""
    try:
        analysis_service = AnalysisService(db)
        project = analysis_service.get_project(project_id)
        
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        
        from config import settings
        project_path = f"{settings.UPLOAD_DIR}/{project_id}/extracted"
        
        repair_service = RepairService(db)
        result = repair_service.batch_apply_repairs(
            analysis_id,
            repair_ids,
            project_path,
            dry_run
        )
        
        return {
            "success": True,
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"批量应用修复失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
