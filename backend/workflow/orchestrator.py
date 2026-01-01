# -*- coding: utf-8 -*-
"""多Agent协调器（完整版：静态+动态+交叉验证）
作用：协调整个分析流程，是系统的核心控制器
依赖:agents、services、database.crud、utils.logger
调用关系:被analysis API调用,协调各个Agent工作
"""
import os
from typing import Dict, Any, Optional
import asyncio
import logging
import json
from datetime import datetime, timezone
from os.path import join, isdir

from sqlalchemy.orm import Session
from agents import (
    FileAnalyzerAgent,
    DetectionAgent,
    ContextAnalyzerAgent,
    RepairGeneratorAgent,
)

# 兼容你把校验工具放在不同目录：优先 agents，失败再尝试 tools
try:
    from agents.validation_agent import ValidationAgent
except Exception:
    try:
        from tools.validation_agent import ValidationAgent
    except Exception:
        ValidationAgent = None

from services.analysis_service import AnalysisService
from database.crud import AnalysisCRUD
from utils.logger import log_info, log_error, log_warning
from config import settings

# ⭐ 动态分析相关导入
from workflow.dynamic_workflow import DynamicWorkflow
from tools.dynamic_analysis.result_correlator import ResultCorrelator


class Orchestrator:
    """多Agent协调器 - 分析流程的大脑（支持静态+动态+交叉验证）"""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.analysis_service = AnalysisService(db_session)
        self.analysis_crud = AnalysisCRUD(db_session)

        # 初始化所有Agent
        self.file_analyzer = FileAnalyzerAgent()
        self.detection_agent = DetectionAgent()
        self.context_analyzer = ContextAnalyzerAgent()
        self.repair_generator = RepairGeneratorAgent()
        self.validation_agent = ValidationAgent() if ValidationAgent else None

        # ⭐ 动态分析组件
        self.dynamic_workflow = DynamicWorkflow()
        self.result_correlator = ResultCorrelator()
        
        log_info("Orchestrator 初始化完成（支持动态分析）")

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        """统一把 Agent/Pydantic/数据类 响应转为 dict"""
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        # Pydantic v2
        if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
            return obj.model_dump()
        # Pydantic v1
        if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
            return obj.dict()
        # dataclass
        try:
            from dataclasses import is_dataclass, asdict
            if is_dataclass(obj):
                return asdict(obj)
        except Exception:
            pass
        # 一般对象：尽量取属性
        if hasattr(obj, "__dict__"):
            return {
                k: v
                for k, v in obj.__dict__.items()
                if not k.startswith("_") and not callable(v)
            }
        # 兜底
        return {
            "success": False,
            "message": f"Unsupported response type: {type(obj).__name__}",
        }

    # ========== 静态分析流程（迭代6完整版本）==========
    
    async def start_analysis(
        self, project_id: str, analysis_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """开始完整的项目分析流程（静态分析核心方法）"""
        try:
            log_info(f"开始分析项目: {project_id}")

            # 1) 获取项目信息
            project = await self._get_project_info(project_id)
            if not project:
                return {"success": False, "error": "Project not found"}

            project_path = project["project_path"]

            # 2) 创建或更新分析记录
            if analysis_id:
                analysis_record = self.analysis_crud.get_analysis(analysis_id)
                if not analysis_record:
                    return {"success": False, "error": "Analysis record not found"}
                self.analysis_crud.update_analysis_status(analysis_id, "running")
                analysis_record.id = analysis_id
            else:
                analysis_record = self.analysis_crud.create_analysis(
                    project_id=project_id, analysis_type="static", status="running"
                )

            analysis_result: Dict[str, Any] = {
                "analysis_id": analysis_record.id,
                "project_id": project_id,
                "status": "running",
                "steps": [],
            }

            try:
                # ===== 多Agent协作流程开始 =====

                # 步骤1: 文件结构分析
                log_info("步骤1: 开始文件结构分析")
                file_analysis = await self._step_file_analysis(project)
                file_analysis = self._to_dict(file_analysis)
                analysis_result["steps"].append({
                    "step": "file_analysis",
                    "status": "completed" if file_analysis.get("success") else "failed",
                    "result": file_analysis,
                })
                if not file_analysis.get("success"):
                    raise Exception(f"文件分析失败: {file_analysis.get('message', 'Unknown error')}")

                # 步骤2: 上下文分析
                log_info("步骤2: 开始上下文分析")
                context_analysis = await self._step_context_analysis(file_analysis.get("data", {}))
                context_analysis = self._to_dict(context_analysis)
                analysis_result["steps"].append({
                    "step": "context_analysis",
                    "status": "completed" if context_analysis.get("success") else "failed",
                    "result": context_analysis,
                })
                if not context_analysis.get("success"):
                    log_error("上下文分析失败，但继续执行后续步骤")
                    context_analysis = {"success": False, "data": {}}

                # 步骤3: 静态缺陷检测
                log_info("步骤3: 开始静态缺陷检测")
                detection_result = await self._step_static_detection(
                    project,
                    file_analysis.get("data", {}),
                    context_analysis.get("data", {}),
                )
                detection_result = self._to_dict(detection_result)
                analysis_result["steps"].append({
                    "step": "static_detection",
                    "status": "completed" if detection_result.get("success") else "failed",
                    "result": detection_result,
                })
                if not detection_result.get("success"):
                    raise Exception(f"静态检测失败: {detection_result.get('message', 'Unknown error')}")

                # 步骤3.5: 误报过滤 + 优先级排序（迭代6）
                log_info("步骤3.5: 进行误报过滤与优先级排序（迭代6）")
                validated_parsed: Optional[Dict[str, Any]] = None
                
                validation_step = await self._step_validation_and_ranking(
                    detection_result.get("data", {}) or {},
                    context_analysis.get("data", {}) or {},
                    project_path,
                )

                if validation_step.get("success"):
                    validated_data = validation_step.get("data", {})
                    validated_parsed = validated_data.get("parsed_results")
                
                if validated_parsed is not None:
                    dr_data = detection_result.get("data", {})
                    dr_data["parsed_results"] = validated_parsed
                    detection_result["data"] = dr_data
                    detection_result["_validated"] = True  # ⭐ 标记已验证
                    
                    issues_count = len(validated_parsed.get('issues', []))
                    log_info(f"✅ 已更新detection_result: {issues_count} issues")
                else:
                    log_error("validated_parsed 为 None,未更新 detection_result")

                analysis_result["steps"].append({
                    "step": "validation_and_ranking",
                    "status": "completed" if validation_step.get("success") else "skipped",
                    "result": validation_step,
                })

                # 步骤4: AI修复建议生成
                log_info("步骤4: 开始生成AI修复建议（基于真实代码）")
                repair_suggestions = await self._step_repair_generation(
                    detection_result.get("data", {}),
                    file_analysis.get("data", {}),
                    context_analysis.get("data", {}),
                    project_path,
                )
                repair_suggestions = self._to_dict(repair_suggestions)
                analysis_result["steps"].append({
                    "step": "repair_generation",
                    "status": "completed" if repair_suggestions.get("success") else "skipped",
                    "result": repair_suggestions,
                })

                # ===== 多Agent协作流程结束 =====

                # 5) 生成最终报告
                final_report = await self._generate_final_report(
                    file_analysis.get("data", {}),
                    detection_result.get("data", {}),
                    context_analysis.get("data", {}),
                    repair_suggestions.get("data", {}),
                )

                # 6) 保存结果
                await self._save_analysis_results(analysis_record.id, final_report)

                # 7) 更新分析状态
                self.analysis_crud.update_analysis_status(analysis_record.id, "completed")

                analysis_result.update({
                    "success": True,
                    "status": "completed",
                    "final_report": final_report,
                    "message": f'分析完成，发现 {final_report["summary"]["total_issues"]} 个问题',
                })

                log_info(f"项目 {project_id} 分析完成")
                return analysis_result

            except Exception as step_error:
                self.analysis_crud.update_analysis_status(
                    analysis_record.id, "failed", error_message=str(step_error)
                )
                raise step_error

        except Exception as e:
            log_error(f"分析流程失败: {str(e)}")
            return {"success": False, "error": str(e), "project_id": project_id}

    # ========== 动态分析流程（新增）==========
    
    async def start_dynamic_analysis(
        self,
        project_id: str,
        analysis_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """启动动态分析工作流"""
        try:
            log_info(f"[Orchestrator] 开始动态分析: project_id={project_id}, analysis_id={analysis_id}")
            
            # 1. 更新分析状态
            self.analysis_crud.update_analysis_status(
                analysis_id,
                status="running",
                error_message="动态分析进行中..."
            )
            
            # 2. 获取项目路径
            analysis_record = self.analysis_crud.get_analysis(analysis_id)
            if not analysis_record:
                raise ValueError(f"分析记录不存在: {analysis_id}")
            
            root_dir = join(settings.UPLOAD_DIR, project_id)
            extracted_dir = join(root_dir, "extracted")
            project_path = extracted_dir if isdir(extracted_dir) else root_dir
            
            # 3. 执行动态分析工作流
            log_info("[Orchestrator] 调用 DynamicWorkflow...")
            dynamic_result = await self.dynamic_workflow.run_dynamic_analysis_workflow(
                project_id=project_id,
                project_path=project_path,
                config=config,
                static_results=None
            )
            
            if not dynamic_result.get("success"):
                log_error(f"[Orchestrator] 动态分析失败: {dynamic_result.get('error')}")
                self.analysis_crud.update_analysis_status(
                    analysis_id,
                    status="failed",
                    error_message=f"动态分析失败: {dynamic_result.get('error')}"
                )
                return dynamic_result
            
            # 4. 保存结果
            log_info("[Orchestrator] 保存动态分析结果...")
            result_file_path = os.path.join(
                config.get("output_dir", "/tmp/dynamic_analysis"),
                f"dynamic_result_{analysis_id}.json"
            )
            
            os.makedirs(os.path.dirname(result_file_path), exist_ok=True)
            with open(result_file_path, 'w', encoding='utf-8') as f:
                json.dump(dynamic_result, f, ensure_ascii=False, indent=2)
            
            # 更新数据库
            self.analysis_crud.update_analysis_status(
                analysis_id,
                status="completed"
            )
            
            log_info("[Orchestrator] 动态分析完成")
            
            return {
                "success": True,
                "analysis_id": analysis_id,
                "result": dynamic_result,
                "message": "动态分析完成"
            }
            
        except Exception as e:
            log_error(f"[Orchestrator] 动态分析异常: {e}", exc_info=True)
            self.analysis_crud.update_analysis_status(
                analysis_id,
                status="failed",
                error_message=f"动态分析异常: {str(e)}"
            )
            return {
                "success": False,
                "error": str(e),
                "analysis_id": analysis_id
            }
    
    async def start_full_analysis_with_dynamic(
        self,
        project_id: str,
        analysis_id: str,
        enable_dynamic: bool = True,
        dynamic_config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """完整分析流程（静态 + 动态 + 交叉验证）- 最终优化版"""
        import time
        
        timing = {}  # 记录各阶段耗时
        
        try:
            log_info(f"[Orchestrator] 🚀 开始完整分析流程（enable_dynamic={enable_dynamic}）")
            total_start = time.time()
            
            # ========== 阶段1: 静态分析 ==========
            phase_start = time.time()
            log_info("[Orchestrator] 📊 阶段1/4: 静态分析...")
            
            static_result = await self.start_analysis(project_id, analysis_id)
            
            if not static_result.get("success"):
                return static_result
            
            timing['static'] = round(time.time() - phase_start, 2)
            log_info(f"[Orchestrator] ✅ 静态分析完成，耗时: {timing['static']}s")
            
            # 提取静态分析结果
            final_report = static_result.get("final_report", {})
            static_issues = final_report.get("issues", [])
            
            # 初始化 summary（避免后续 KeyError）
            if "summary" not in final_report:
                final_report["summary"] = {}
            summary = final_report["summary"]
            
            # 如果不启用动态分析，补充默认值后返回
            if not enable_dynamic:
                log_info("[Orchestrator] ⏭️  动态分析未启用，补充默认信息后返回")
                summary["dynamic_analysis"] = {"executed": False}
                summary["cross_validation"] = {
                    "high_confidence": 0,
                    "medium_confidence": len(static_issues),
                    "low_confidence": 0,
                    "total_validated": len(static_issues)
                }
                summary["performance"] = {
                    "total_time": timing['static'],
                    "static_time": timing['static'],
                    "dynamic_time": 0,
                    "validation_time": 0,
                    "ai_repair_time": 0
                }
                
                # 保存结果
                await self.analysis_service.save_analysis_report(analysis_id, final_report)
                
                return {
                    "success": True,
                    "message": "静态分析完成（未启用动态分析）",
                    "analysis_id": analysis_id,
                    "result": final_report
                }
            
            # ========== 阶段2: 动态分析 ==========
            phase_start = time.time()
            log_info("[Orchestrator] 🔍 阶段2/4: 动态分析...")
            
            dynamic_config = dynamic_config or {}
            dynamic_result = await self.start_dynamic_analysis(
                project_id,
                analysis_id,
                dynamic_config
            )
            
            timing['dynamic'] = round(time.time() - phase_start, 2)
            
            # 提取动态分析数据
            dynamic_executed = dynamic_result.get("success", False)
            dynamic_data = dynamic_result.get("result", {}) if dynamic_executed else {}
            dynamic_issues = dynamic_data.get("dynamic_issues", [])
            
            # ✅ 添加调试日志
            log_info(f"🔍 调试：dynamic_data 包含的键: {list(dynamic_data.keys())}")
            if "dynamic_execution" in dynamic_data:
                log_info(f"   dynamic_execution 内容: {dynamic_data['dynamic_execution']}")
            else:
                log_warning("   ⚠️  缺少 dynamic_execution 字段！")

            # 构建动态分析统计
            dynamic_stats = self._build_dynamic_stats(dynamic_data, dynamic_issues, timing['dynamic'])
            
            log_info(f"[Orchestrator] ✅ 动态分析完成，耗时: {timing['dynamic']}s, "
                    f"发现 {len(dynamic_issues)} 个问题")
            if dynamic_executed:
                log_info("="*70)
                log_info("🔍 动态分析结果诊断")
                log_info("="*70)
                
                # 打印统计信息
                log_info(f"执行状态:")
                log_info(f"   Valgrind: {'✅' if dynamic_stats.get('valgrind_executed') else '❌'}")
                log_info(f"   ASan: {'✅' if dynamic_stats.get('asan_executed') else '❌'}")
                log_info(f"   UBSan: {'✅' if dynamic_stats.get('ubsan_executed') else '❌'}")
                
                log_info(f"\n问题统计:")
                log_info(f"   Valgrind 问题数: {dynamic_stats.get('valgrind_issues', 0)}")
                log_info(f"   ASan 问题数: {dynamic_stats.get('asan_issues', 0)}")
                log_info(f"   动态总问题数: {len(dynamic_issues)}")
                
                if dynamic_issues:
                    log_info(f"\n前5个动态问题详情:")
                    for i, issue in enumerate(dynamic_issues[:5], 1):
                        log_info(f"   {i}. [{issue.get('severity', '?')}] {issue.get('type')}")
                        log_info(f"      子类型: {issue.get('subtype', 'N/A')}")
                        log_info(f"      工具: {issue.get('tool', 'N/A')}")
                        log_info(f"      位置: {issue.get('location', 'N/A')}")
                else:
                    log_warning("\n⚠️  未发现任何动态问题！")
                    log_warning("请检查:")
                    log_warning("   1. 编译日志中是否有 -fsanitize 标志")
                    log_warning("   2. 可执行文件是否链接了 libasan/libubsan")
                    log_warning("   3. 程序是否真正运行（查看执行器日志）")
                    log_warning("   4. 解析函数是否正确工作")
                
                log_info("="*70)            
            # ========== 阶段3: 交叉验证 ==========
            phase_start = time.time()
            log_info("[Orchestrator] 🔗 阶段3/4: 交叉验证...")

            cross_validation_stats = None
            validated_issues = []  # ⭐ 初始化为空列表

            if dynamic_executed and dynamic_issues and self.validation_agent:
                try:
                    cross_validation_result = await self.validation_agent.cross_validate_with_dynamic(
                        static_issues,
                        dynamic_issues,
                        tolerance=dynamic_config.get("line_tolerance", 5)
                    )
                    
                    if cross_validation_result.get("success"):
                        validation_report = cross_validation_result.get("validation_report", {})
                        
                        # ✅ 提取所有类型的问题
                        high_confidence = validation_report.get("high_confidence_issues", [])
                        medium_confidence = validation_report.get("medium_confidence_issues", [])
                        low_confidence = validation_report.get("low_confidence_issues", [])
                        dynamic_only = validation_report.get("dynamic_exclusive_issues", [])  # ⭐ 关键
                        
                        # ✅ 合并所有问题（包括仅动态发现的）
                        validated_issues = high_confidence + medium_confidence + low_confidence + dynamic_only
                        
                        # 统计各置信度级别
                        cross_validation_stats = {
                            "high_confidence": len(high_confidence),
                            "medium_confidence": len(medium_confidence),
                            "low_confidence": len(low_confidence),
                            "dynamic_only": len(dynamic_only),  # ⭐ 新增
                            "total_validated": len(validated_issues)
                        }
                        
                        log_info(f"[Orchestrator] ✅ 交叉验证完成: "
                                f"高={len(high_confidence)}, "
                                f"中={len(medium_confidence)}, "
                                f"低={len(low_confidence)}, "
                                f"仅动态={len(dynamic_only)}")  # ⭐ 显示仅动态
                    else:
                        log_warning("[Orchestrator] ⚠️  交叉验证失败，使用原始动态结果")
                        validated_issues = dynamic_issues  # ⭐ 失败时保留动态结果
                        
                except Exception as e:
                    log_error(f"[Orchestrator] ❌ 交叉验证异常: {e}", exc_info=True)
                    validated_issues = dynamic_issues  # ⭐ 异常时保留动态结果

            elif dynamic_executed and dynamic_issues:
                # 有动态结果但无验证器
                log_warning("[Orchestrator] ⚠️  ValidationAgent 不可用，直接使用动态结果")
                validated_issues = dynamic_issues  # ⭐ 无验证器时保留动态结果

            else:
                # 无动态分析或动态结果为空
                log_info("[Orchestrator] ℹ️  无动态结果，使用静态结果")
                validated_issues = static_issues

            timing['validation'] = round(time.time() - phase_start, 2)

            # 默认交叉验证统计（如果没有执行验证）
            if cross_validation_stats is None:
                cross_validation_stats = {
                    "high_confidence": 0,
                    "medium_confidence": 0,
                    "low_confidence": 0,
                    "dynamic_only": len(validated_issues) if dynamic_executed else 0,
                    "total_validated": len(validated_issues)
                }

            
            # ========== 阶段4: 整合最终报告 ==========
            log_info("[Orchestrator] 📋 阶段4/4: 整合最终报告...")
            
            # 更新 issues（使用交叉验证后的）
            final_report["issues"] = validated_issues
            
            # 更新工具列表
            tools = set(summary.get("analysis_tools", []))
            tools.update(dynamic_stats.get("tools", []))
            summary["analysis_tools"] = sorted(list(tools))
            
            # 添加动态分析信息
            summary["dynamic_analysis"] = dynamic_stats
            
            # 添加交叉验证统计
            summary["cross_validation"] = cross_validation_stats
            
            # 添加性能统计
            timing['total'] = round(time.time() - total_start, 2)
            summary["performance"] = {
                "total_time": timing['total'],
                "static_time": timing.get('static', 0),
                "dynamic_time": timing.get('dynamic', 0),
                "validation_time": timing.get('validation', 0),
                "ai_repair_time": 0  # 如果有AI修复时间，从 static_result 提取
            }
            
            # 更新总问题数
            summary["total_issues"] = len(validated_issues)
            
            # 重新计算严重程度分布
            severity_dist = {}
            for issue in validated_issues:
                sev = (issue.get("severity") or "unknown").lower()
                severity_dist[sev] = severity_dist.get(sev, 0) + 1
            summary["severity_distribution"] = severity_dist
            
            # ========== 保存结果 ==========
            log_info("[Orchestrator] 💾 保存结果到数据库和文件...")
            await self.analysis_service.save_analysis_report(analysis_id, final_report)
            
            # 更新数据库（直接操作数据库对象）
            analysis_record = self.analysis_crud.get_analysis(analysis_id)
            if analysis_record:
                analysis_record.status = "completed"
                analysis_record.end_time = datetime.now(timezone.utc)
                analysis_record.duration = timing['total']
                analysis_record.total_defects = summary["total_issues"]
                analysis_record.high_defects = severity_dist.get("high", 0)
                analysis_record.medium_defects = severity_dist.get("medium", 0)
                analysis_record.low_defects = severity_dist.get("low", 0)
                self.db.commit()
                log_info("[Orchestrator] ✅ 数据库记录已更新")
                        
            log_info(f"[Orchestrator] 🎉 完整分析流程完成！总耗时: {timing['total']}s")
            
            return {
                "success": True,
                "message": f"分析完成，发现 {summary['total_issues']} 个问题 "
                        f"(动态确认: {cross_validation_stats['high_confidence']})",
                "analysis_id": analysis_id,
                "result": final_report
            }
            
        except Exception as e:
            log_error(f"[Orchestrator] ❌ 完整分析流程异常: {e}", exc_info=True)
            self.analysis_crud.update_analysis_status(
                analysis_id,
                status="failed",
                error_message=str(e)
            )
            return {
                "success": False,
                "error": str(e),
                "analysis_id": analysis_id
            }

    # ========== 新增辅助方法 ==========

    def _build_dynamic_stats(
        self,
        dynamic_data: Dict[str, Any],
        dynamic_issues: list,
        execution_time: float
    ) -> Dict[str, Any]:
        """构建动态分析统计信息"""
        
        # ✅ 修复：从正确的嵌套路径读取执行状态
        dynamic_execution = dynamic_data.get("dynamic_execution", {})
        
        stats = {
            "executed": bool(dynamic_data),
            "valgrind_executed": dynamic_execution.get("valgrind_executed", False),  # ✅ 修复
            "asan_executed": dynamic_execution.get("asan_executed", False),          # ✅ 修复
            "ubsan_executed": dynamic_execution.get("ubsan_executed", False),        # ✅ 新增
            "valgrind_issues": dynamic_execution.get("valgrind_issues", 0),          # ✅ 直接读取
            "asan_issues": dynamic_execution.get("asan_issues", 0),                  # ✅ 直接读取
            "ubsan_issues": dynamic_execution.get("ubsan_issues", 0),                # ✅ 新增
            "execution_time": execution_time,
            "tools": dynamic_execution.get("tools_run", [])                          # ✅ 直接读取工具列表
        }
        
        # ⚠️ 如果 dynamic_execution 为空，尝试从 issues 推断（兜底方案）
        if not dynamic_execution:
            log_warning("⚠️  dynamic_execution 字段为空，从 issues 推断执行状态")
            stats["valgrind_issues"] = 0
            stats["asan_issues"] = 0
            stats["ubsan_issues"] = 0
            
            for issue in dynamic_issues:
                tool = issue.get('source_tool', '').lower()
                if 'valgrind' in tool:
                    stats["valgrind_issues"] += 1
                    stats["valgrind_executed"] = True
                if 'asan' in tool or 'address' in tool:
                    stats["asan_issues"] += 1
                    stats["asan_executed"] = True
                if 'ubsan' in tool or 'undefined' in tool:
                    stats["ubsan_issues"] += 1
                    stats["ubsan_executed"] = True
            
            # 重建工具列表
            stats["tools"] = []
            if stats["valgrind_executed"]:
                stats["tools"].append("valgrind_memcheck")
            if stats["asan_executed"]:
                stats["tools"].append("address_sanitizer")
            if stats["ubsan_executed"]:
                stats["tools"].append("undefined_sanitizer")
        
        return stats

    # ========== 辅助方法（私有）==========
    
    async def _run_validation_in_thread(self, issues: list, context: dict) -> dict:
        """将同步的 ValidationAgent.process 放入线程池执行，避免阻塞事件循环"""
        if not self.validation_agent:
            return {"success": False, "message": "ValidationAgent not available"}
        return await asyncio.to_thread(self.validation_agent.process, issues, context)

    async def _step_validation_and_ranking(
        self,
        detection_data: Dict[str, Any],
        context_data: Dict[str, Any],
        project_path: str,
    ) -> Dict[str, Any]:
        """步骤3.5：误报过滤 + 优先级排序（迭代6核心）"""
        try:
            context_opts = context_data.get("options") or {}
            enable_validation = context_opts.get(
                "enable_validation", getattr(settings, "ENABLE_VALIDATION", True)
            )
            if not enable_validation:
                logging.info("Validation disabled. 跳过迭代6")
                return {"success": False, "message": "Validation disabled"}

            parsed = detection_data.get("parsed_results", {}) or {}
            issues = parsed.get("issues", []) or []
            if not issues:
                return {"success": False, "message": "No issues to validate"}

            before_cnt = len(issues)
            log_info(f"🔍 开始验证：{before_cnt} 个原始issues")

            v_context = {
                "project_path": project_path,
                "project_features": (context_data.get("project_features") or []),
                "options": context_opts,
            }
            vout = await self._run_validation_in_thread(issues, v_context)
            if not vout or not vout.get("success"):
                log_error("ValidationAgent 未返回成功结果，保留原始 issues")
                return {
                    "success": False,
                    "message": vout.get("message", "validation failed"),
                }

            filtered = vout.get("issues", []) or []
            after_cnt = len(filtered)
            
            log_info(f"✅ 验证完成：before={before_cnt} → after={after_cnt} (过滤{before_cnt-after_cnt}个)")

            return {
                "success": True,
                "data": {
                    "validated_before": before_cnt,
                    "validated_after": after_cnt,
                    "validated_filtered": max(0, before_cnt - after_cnt),
                    "parsed_results": {
                        "issues": filtered,
                        "statistics": {
                            "validated_before": before_cnt,
                            "validated_after": after_cnt,
                            "validated_filtered": max(0, before_cnt - after_cnt),
                        },
                        "categories": vout.get("categories", {}),
                    },
                },
            }
        
        except Exception as exc:
            log_error(f"Validation step failed: {exc}", exc_info=True)
            return {"success": False, "message": str(exc)}

    async def _get_project_info(self, project_id: str) -> Optional[Dict[str, Any]]:
        """获取项目信息"""
        project_path = os.path.join(settings.UPLOAD_DIR, project_id, "extracted")
        return {
            "id": project_id,
            "project_path": project_path,
            "name": f"Project_{project_id}",
        }

    async def _step_file_analysis(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """步骤1: 文件结构分析"""
        task_data = {
            "project_path": project["project_path"],
            "project_id": project["id"],
        }
        result = await self.file_analyzer.process(task_data)
        return self._to_dict(result)

    async def _step_context_analysis(self, file_analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """步骤2: 上下文分析"""
        task_data = {"file_analysis": file_analysis_data}
        result = await self.context_analyzer.process(task_data)
        return self._to_dict(result)

    async def _step_static_detection(
        self,
        project: Dict[str, Any],
        file_analysis_data: Dict[str, Any],
        context_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """步骤3: 静态缺陷检测"""
        analysis_config = {
            "enable_cppcheck": True,
            "source_files": file_analysis_data.get("source_files", []),
            "context": context_data,
        }
        task_data = {
            "project_path": project["project_path"],
            "analysis_config": analysis_config,
        }
        result = await self.detection_agent.process(task_data)
        return self._to_dict(result)

    async def _step_repair_generation(
        self,
        detection_results: Dict[str, Any],
        file_analysis_data: Dict[str, Any],
        context_data: Dict[str, Any],
        project_path: str,
    ) -> Dict[str, Any]:
        """步骤4: AI修复建议生成（迭代4增强：基于真实代码）"""
        task_data = {
            "detection_results": detection_results,
            "file_analysis": file_analysis_data,
            "context": context_data,
            "project_path": project_path,
        }
        result = await self.repair_generator.process(task_data)
        return self._to_dict(result)

    async def _generate_final_report(
        self,
        file_analysis: Dict[str, Any],
        detection_results: Dict[str, Any],
        context_analysis: Dict[str, Any],
        repair_suggestions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成最终分析报告"""
        parsed_results = detection_results.get("parsed_results", {}) or {}
        issues_after = parsed_results.get("issues", []) or []
        
        # 验证
        if not detection_results.get("_validated"):
            log_error("⚠️ 警告：detection_results 未经过 validation，数据可能不完整！")
        
        # ✅ 修复：添加空列表检查
        if issues_after:
            if not issues_after[0].get("priority_score"):
                log_error("⚠️ 警告：issues 缺少 priority_score 字段，校验可能失败！")
            else:
                log_info(f"✅ 验证通过：第一个 issue 有 priority_score = {issues_after[0].get('priority_score')}")
        else:
            log_info("ℹ️  未发现问题，跳过 priority_score 验证")
        
        total_issues = len(issues_after)
        
        # 重算 severity_distribution
        sev_count = {}
        for it in issues_after:
            sev = (it.get("severity") or "unknown").lower()
            sev_count[sev] = sev_count.get(sev, 0) + 1
        severity_dist = sev_count or parsed_results.get("statistics", {}).get("severity_distribution", {})
        
        # 取出校验统计
        stats = parsed_results.get("statistics", {}) or {}
        validated_before = stats.get("validated_before")
        validated_after = stats.get("validated_after")
        validated_filtered = stats.get("validated_filtered")

        repairs = repair_suggestions.get("repair_suggestions", [])

        report = {
            "summary": {
                "total_issues": total_issues,
                "files_analyzed": len(file_analysis.get("source_files", [])),
                "severity_distribution": severity_dist,
                "analysis_tools": list(detection_results.get("tool_results", {}).keys()),
                "repairs_generated": len(repairs),
                "repairs_with_real_code": len([
                    r for r in repairs
                    if r.get("type") == "llm_generated_with_context"
                ]),
                **(
                    {
                        "validated_before": validated_before,
                        "validated_after": validated_after,
                        "validated_filtered": validated_filtered,
                    }
                    if validated_before is not None
                    else {}
                ),
            },
            "file_analysis": {
                "project_structure": file_analysis.get("project_structure", {}),
                "complexity_metrics": file_analysis.get("complexity_metrics", {}),
            },
            "context_analysis": {
                "macros": context_analysis.get("macros", {}),
                "platform_info": context_analysis.get("platform_info", {}),
                "compiler_info": context_analysis.get("compiler_info", {}),
            },
            "issues": issues_after,
            "recommendations": detection_results.get("recommendations", []),
            "repair_suggestions": repairs,
        }
        return report

    async def _save_analysis_results(self, analysis_id: str, report: Dict[str, Any]) -> None:
        """保存分析结果"""
        try:
            if hasattr(self.analysis_crud, "save_analysis_results"):
                try:
                    self.analysis_crud.save_analysis_results(analysis_id, report)
                except Exception as e_db:
                    log_error(f"保存分析结果到数据库失败（将继续写文件）: {str(e_db)}")

            await self.analysis_service.save_analysis_report(analysis_id, report)
            log_info(f"分析结果已保存: {analysis_id}")
        except Exception as e:
            log_error(f"保存分析结果失败: {str(e)}")
            raise
