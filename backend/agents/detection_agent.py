# -*- coding: utf-8 -*-
"""静态缺陷检测Agent
作用：运行Cppcheck、Clang-Tidy、Flawfinder等静态分析工具检测代码缺陷
依赖：base_agent、tools.static_analysis模块、utils.logger
调用关系：被orchestrator调用，在上下文分析后执行
"""
import asyncio
import os
from typing import Dict, List, Any
from .base_agent import BaseAgent, AgentResponse, AgentStatus
from tools.static_analysis.cppcheck_wrapper import CppcheckWrapper
from tools.static_analysis.clang_tidy_wrapper import ClangTidyWrapper  # 🆕 新增
from tools.static_analysis.flawfinder_wrapper import FlawfinderWrapper  # 🆕 新增
from tools.static_analysis.result_parser import ResultParser
from tools.specialized_detectors.memory_pool_detector import MemoryPoolDetector
from tools.specialized_detectors.custom_rules import CustomRulesEngine
from utils.logger import log_info, log_error


class DetectionAgent(BaseAgent):
    """静态缺陷检测Agent (集成多引擎)"""
    
    def __init__(self):
        super().__init__(
            agent_id="detection_001", 
            name="DetectionAgent"
        )
        # 初始化三大静态分析引擎
        self.cppcheck = CppcheckWrapper()
        self.clang_tidy = ClangTidyWrapper()    # 🆕
        self.flawfinder = FlawfinderWrapper()   # 🆕
        
        self.result_parser = ResultParser()
        self.memory_pool_detector = MemoryPoolDetector()
        self.custom_rules_engine = CustomRulesEngine()
        
    def get_capabilities(self) -> List[str]:
        """返回Agent能力列表"""
        return [
            "static_code_analysis",        # 基础静态分析
            "modern_cpp_check",            # 🆕 现代C++规范检查 (Clang-Tidy)
            "security_audit",              # 🆕 安全漏洞审计 (Flawfinder)
            "memory_leak_detection",       # 内存泄漏检测
            "buffer_overflow_detection",   # 缓冲区溢出检测
            "null_pointer_detection",      # 空指针检测
            "unused_variable_detection",   # 未使用变量检测
            "specialized_detection",       # 专项检测
            "custom_rules_detection"       # 自定义规则
        ]
    
    async def process(self, task_data: Dict[str, Any]) -> AgentResponse:
        """处理静态检测任务 (并行执行)"""
        try:
            self.set_status(AgentStatus.WORKING)
            log_info(f"{self.name} 开始多引擎静态代码分析")
            
            project_path = task_data.get('project_path')
            analysis_config = task_data.get('analysis_config', {})
            context_data = analysis_config.get('context', {})
            
            if not project_path or not os.path.exists(project_path):
                return AgentResponse(
                    success=False,
                    message="项目路径无效",
                    errors=["项目路径不存在或无效"]
                )
            
            # --- 1. 准备并行任务 ---
            results = {}
            static_tasks = []
            task_names = []

            # (1) Cppcheck
            if analysis_config.get('enable_cppcheck', True):
                static_tasks.append(self.cppcheck.analyze(project_path))
                task_names.append('cppcheck')

            # (2) Clang-Tidy (新)
            if analysis_config.get('enable_clang_tidy', True):
                static_tasks.append(self.clang_tidy.analyze(project_path))
                task_names.append('clang_tidy')

            # (3) Flawfinder (新)
            if analysis_config.get('enable_flawfinder', True):
                static_tasks.append(self.flawfinder.analyze(project_path))
                task_names.append('flawfinder')

            # --- 2. 执行并行检测 ---
            log_info(f"🚀 启动并行分析矩阵: {', '.join(task_names)}")
            
            # 使用 return_exceptions=True 确保一个工具挂了不影响其他工具
            task_results = await asyncio.gather(*static_tasks, return_exceptions=True)

            # 处理常规工具结果
            extra_static_issues = []  # 用于存储 Clang-Tidy 和 Flawfinder 的结果
            
            for name, res in zip(task_names, task_results):
                if isinstance(res, Exception):
                    log_error(f"{name} 分析失败: {res}")
                    # 可以选择将错误信息记录到 results 中，方便前端展示
                    results[name] = {"success": False, "error": str(res)}
                elif isinstance(res, dict):
                    results[name] = res
                    issue_count = len(res.get('issues', []))
                    log_info(f"✅ {name} 完成，发现 {issue_count} 个问题")
                    
                    # 收集额外工具的问题 (因为 ResultParser 可能只默认处理 cppcheck，需要手动聚合新工具的issues)
                    if name in ['clang_tidy', 'flawfinder']:
                        extra_static_issues.extend(res.get('issues', []))

            # --- 3. 执行专项检测 (串行执行) ---
            
            # 3.1 内存池专项
            if self._is_memory_pool_project(project_path):
                log_info("启用内存池专项检测器...")
                memory_pool_result = await self.memory_pool_detector.detect(project_path)
                if memory_pool_result.get('success'):
                    results['memory_pool_specialized'] = memory_pool_result
                    log_info(f"内存池专项检测完成，发现 {len(memory_pool_result.get('issues', []))} 个问题")
            
            # 3.2 自定义规则 (按需开启)
            if analysis_config.get('enable_custom_rules', True):
                # log_info("运行自定义规则检测...")
                # custom_rules_result = await self.custom_rules_engine.detect(project_path)
                # if custom_rules_result.get('success'):
                #     results['custom_rules'] = custom_rules_result
                pass 

            # --- 4. 结果聚合与解析 ---
            
            # 使用 ResultParser 解析基础结果 (主要处理 Cppcheck 的标准化)
            parsed_results = self.result_parser.parse_and_merge(
                results, 
                context=context_data
            )
            
            # 收集所有"额外"发现的问题 (专项 + 新工具)
            all_extra_issues = []
            all_extra_issues.extend(extra_static_issues) # Clang-Tidy + Flawfinder
            
            if 'memory_pool_specialized' in results:
                all_extra_issues.extend(results['memory_pool_specialized'].get('issues', []))
            if 'custom_rules' in results:
                all_extra_issues.extend(results['custom_rules'].get('issues', []))
            
            # 计算总统计数据
            total_issues_count = parsed_results.get('total_issues', 0) + len(all_extra_issues)
            
            # 合并严重度分布
            final_severity_dist = self._merge_severity_distribution(
                parsed_results.get('statistics', {}).get('severity_distribution', {}),
                all_extra_issues
            )
            
            # 生成综合建议
            final_recommendations = self._generate_recommendations(
                parsed_results, 
                context_data, 
                all_extra_issues
            )

            # 构造最终返回结构
            final_result = {
                'tool_results': results,
                'parsed_results': parsed_results,
                'specialized_issues': all_extra_issues, # 前端需要展示这些额外问题
                'project_path': project_path,
                'total_issues': total_issues_count,
                'severity_distribution': final_severity_dist,
                'recommendations': final_recommendations,
                'context_aware': bool(context_data),
                'tools_used': task_names,
                'has_specialized_detection': bool(all_extra_issues)
            }
            
            self.set_status(AgentStatus.COMPLETED)
            log_info(f"{self.name} 分析结束，总计发现 {total_issues_count} 个问题")
            
            return AgentResponse(
                success=True,
                message=f"静态分析完成，发现 {total_issues_count} 个问题",
                data=final_result
            )
            
        except Exception as e:
            self.set_status(AgentStatus.FAILED)
            log_error(f"{self.name} 致命错误: {str(e)}")
            return AgentResponse(
                success=False,
                message="静态代码分析流程异常",
                errors=[str(e)]
            )
    
    def _is_memory_pool_project(self, project_path: str) -> bool:
        """判断是否是内存池项目"""
        key_files = ['ThreadCache.h', 'CentralCache.h', 'PageCache.h']
        for root, dirs, files in os.walk(project_path):
            if any(kf in files for kf in key_files):
                log_info(f"识别为内存池项目（在 {root} 找到关键文件）")
                return True
        return False
    
    def _merge_severity_distribution(
        self, 
        general_dist: Dict[str, int], 
        extra_issues: List[Dict]
    ) -> Dict[str, int]:
        """合并严重度分布"""
        merged = general_dist.copy()
        for issue in extra_issues:
            severity = issue.get('severity', 'medium')
            merged[severity] = merged.get(severity, 0) + 1
        return merged
    
    def _generate_recommendations(
        self, 
        parsed_results: Dict[str, Any],
        context_data: Dict[str, Any],
        extra_issues: List[Dict] = None
    ) -> List[Dict[str, Any]]:
        """生成综合修复建议（整合多引擎结果）"""
        recommendations = []
        extra_issues = extra_issues or []
        
        # 基础统计
        total_issues = parsed_results.get('total_issues', 0) + len(extra_issues)
        severity_dist = parsed_results.get('statistics', {}).get('severity_distribution', {})
        
        high_issues = severity_dist.get('high', 0)
        # 统计额外问题中的关键问题
        critical_issues = len([i for i in extra_issues if i.get('severity') == 'critical'])
        high_extra_issues = len([i for i in extra_issues if i.get('severity') == 'high'])
        total_high = high_issues + high_extra_issues

        # --- 新增：工具特定建议 ---
        
        # Flawfinder 安全警告
        security_issues = len([i for i in extra_issues if i.get('tool') == 'flawfinder'])
        if security_issues > 0:
            recommendations.append({
                'priority': 'critical',
                'type': 'security_audit',
                'message': f'🛡️ 安全警告：Flawfinder 发现了 {security_issues} 个潜在安全漏洞，建议立即审查'
            })
            
        # Clang-Tidy 现代化建议
        modern_cpp_issues = len([i for i in extra_issues if i.get('tool') == 'clang-tidy' and 'modernize' in i.get('message', '')])
        if modern_cpp_issues > 5:
            recommendations.append({
                'priority': 'low',
                'type': 'modernize_cpp',
                'message': f'💡 代码现代化：Clang-Tidy 提供了 {modern_cpp_issues} 个现代化C++改进建议（如使用nullptr, override等）'
            })

        # --- 原有：通用建议逻辑 ---

        if critical_issues > 0:
            recommendations.append({
                'priority': 'critical',
                'type': 'immediate_action',
                'message': f'🚨 发现{critical_issues}个严重问题（线程安全/内存管理），必须修复'
            })
        
        if total_high > 0:
            recommendations.append({
                'priority': 'high',
                'type': 'critical_fixes',
                'message': f'发现{total_high}个高严重性问题，建议优先修复'
            })
        
        if total_issues > 10:
            recommendations.append({
                'priority': 'medium',
                'type': 'systematic_review',
                'message': '问题数量较多，建议安排系统性代码审查'
            })
        
        # 平台相关建议
        platform_info = context_data.get('platform_info', {})
        detected_platforms = platform_info.get('detected_platforms', [])
        
        if detected_platforms and len(detected_platforms) > 1:
            recommendations.append({
                'priority': 'medium',
                'type': 'platform_testing',
                'message': f'代码支持多平台({", ".join(detected_platforms)})，建议在各平台分别进行编译测试'
            })
        
        # 专项检测特定建议
        if extra_issues:
            thread_safety_issues = [i for i in extra_issues if i.get('type') == 'thread_safety']
            if thread_safety_issues:
                recommendations.append({
                    'priority': 'high',
                    'type': 'concurrency_review',
                    'message': f'发现{len(thread_safety_issues)}个线程安全问题，建议重点审查锁机制'
                })
            
            deadlock_issues = [i for i in extra_issues if i.get('type') == 'deadlock_risk']
            if deadlock_issues:
                recommendations.append({
                    'priority': 'critical',
                    'type': 'deadlock_prevention',
                    'message': '⚠️ 检测到潜在死锁风险，请仔细审查锁的获取顺序'
                })
        
        return recommendations
