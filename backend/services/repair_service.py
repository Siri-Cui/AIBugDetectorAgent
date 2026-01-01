# -*- coding: utf-8 -*-
"""
修复服务
作用：管理修复建议，提供补丁预览和应用功能
依赖：database.crud、tools.patch_generator、utils.logger
调用关系：被repair API路由调用
"""
import os
import json
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session

from database.crud import AnalysisCRUD
from tools.patch_generator import PatchGenerator
from utils.logger import log_info, log_error
from config import settings


class RepairService:
    """修复服务 - 管理修复建议和补丁应用"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.analysis_crud = AnalysisCRUD(db_session)
        self.patch_generator = PatchGenerator()
    
    def get_repair_suggestions(self, analysis_id: str) -> Dict[str, Any]:
        """
        获取分析的所有修复建议
        
        Args:
            analysis_id: 分析ID
            
        Returns:
            {
                'analysis_id': str,
                'repairs': [修复建议列表],
                'summary': {...}
            }
        """
        try:
            # 从数据库获取分析结果
            analysis = self.analysis_crud.get_analysis(analysis_id)
            
            if not analysis:
                return {
                    'success': False,
                    'error': '分析记录不存在'
                }
            
            # 从结果文件读取修复建议
            result_file = os.path.join(
                settings.RESULTS_DIR,
                analysis_id,
                'analysis_result.json'
            )
            
            if not os.path.exists(result_file):
                return {
                    'success': False,
                    'error': '分析结果文件不存在'
                }
            
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            
            repairs = result.get('repair_suggestions', [])
            
            # 生成摘要统计
            summary = {
                'total_repairs': len(repairs),
                'high_priority': len([r for r in repairs if r.get('priority') == 'high']),
                'auto_applicable': len([r for r in repairs if r.get('type') == 'llm_generated_with_context']),
                'analysis_id': analysis_id
            }
            
            return {
                'success': True,
                'analysis_id': analysis_id,
                'repairs': repairs,
                'summary': summary
            }
            
        except Exception as e:
            log_error(f"获取修复建议失败: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_repair_detail(self, analysis_id: str, repair_id: str) -> Dict[str, Any]:
        """
        获取单个修复建议的详细信息（包含代码预览）
        
        Args:
            analysis_id: 分析ID
            repair_id: 修复建议ID
            
        Returns:
            {
                'repair': 修复建议详情,
                'preview': 补丁预览
            }
        """
        try:
            repairs = self.get_repair_suggestions(analysis_id)
            
            if not repairs.get('success'):
                return repairs
            
            # 查找指定的修复建议
            target_repair = None
            for repair in repairs['repairs']:
                if repair.get('id') == repair_id:
                    target_repair = repair
                    break
            
            if not target_repair:
                return {
                    'success': False,
                    'error': '修复建议不存在'
                }
            
            # 如果有diff_patch，生成预览
            preview = None
            if 'diff_patch' in target_repair:
                preview = {
                    'diff': target_repair['diff_patch'],
                    'can_apply': target_repair.get('can_auto_apply', False)
                }
            
            return {
                'success': True,
                'repair': target_repair,
                'preview': preview
            }
            
        except Exception as e:
            log_error(f"获取修复详情失败: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def apply_repair(
        self,
        analysis_id: str,
        repair_id: str,
        project_path: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        应用修复补丁到项目文件
        
        Args:
            analysis_id: 分析ID
            repair_id: 修复建议ID
            project_path: 项目根路径
            dry_run: 是否仅预览不实际修改
            
        Returns:
            {
                'success': bool,
                'message': str,
                'applied_files': [已修改的文件],
                'backup_paths': [备份文件路径]
            }
        """
        try:
            # 获取修复详情
            repair_detail = self.get_repair_detail(analysis_id, repair_id)
            
            if not repair_detail.get('success'):
                return repair_detail
            
            repair = repair_detail['repair']
            
            # 检查是否可以自动应用
            if not repair.get('can_auto_apply', False):
                return {
                    'success': False,
                    'error': '此修复建议不支持自动应用，请手动修改'
                }
            
            # 获取补丁内容
            patch_content = repair.get('diff_patch', '')
            if not patch_content:
                return {
                    'success': False,
                    'error': '修复建议缺少补丁内容'
                }
            
            # 解析补丁中的文件路径
            issue = repair.get('issue_id', '')
            file_path = repair.get('file_path', '')
            
            if not file_path:
                return {
                    'success': False,
                    'error': '无法确定目标文件路径'
                }
            
            full_path = os.path.join(project_path, file_path)
            
            if dry_run:
                # 仅预览
                log_info(f"预览模式：将应用补丁到 {full_path}")
                return {
                    'success': True,
                    'message': '预览成功（未实际修改文件）',
                    'target_file': full_path,
                    'patch_preview': patch_content
                }
            else:
                # 实际应用补丁
                result = self.patch_generator.apply_patch(
                    full_path,
                    patch_content,
                    backup=True
                )
                
                if result['success']:
                    log_info(f"成功应用补丁到 {full_path}")
                
                return result
            
        except Exception as e:
            log_error(f"应用修复失败: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def batch_apply_repairs(
        self,
        analysis_id: str,
        repair_ids: List[str],
        project_path: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        批量应用多个修复建议
        
        Returns:
            {
                'success': bool,
                'results': {repair_id: result},
                'summary': {...}
            }
        """
        results = {}
        success_count = 0
        failed_count = 0
        
        for repair_id in repair_ids:
            result = self.apply_repair(analysis_id, repair_id, project_path, dry_run)
            results[repair_id] = result
            
            if result.get('success'):
                success_count += 1
            else:
                failed_count += 1
        
        return {
            'success': failed_count == 0,
            'results': results,
            'summary': {
                'total': len(repair_ids),
                'success': success_count,
                'failed': failed_count
            }
        }
