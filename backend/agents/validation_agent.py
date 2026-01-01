import os
import re
import sys
import traceback
import logging
from typing import Dict, Any, List, Tuple, Optional
from utils.logger import log_info, log_error
from tools.false_positive_filter import FalsePositiveFilter
from tools.priority_scorer import PriorityScorer
from tools.defect_classifier import DefectClassifier
from tools.dynamic_analysis.result_correlator import ResultCorrelator  # ⭐ 添加导入

# 严重性映射
_SEV_MAP = {
    "error": "high",
    "warning": "medium",
    "style": "low",
    "performance": "medium",
    "portability": "medium",
    "information": "low",
    "debug": "low",
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
}

def _norm_sev(s: Optional[str]) -> str:
    """将各种 severity 字符串标准化为 critical/high/medium/low"""
    if not s:
        return "low"
    s_lower = s.lower()
    return _SEV_MAP.get(s_lower, "low")


class ValidationAgent:
    """
    结果校验Agent：负责误报过滤 + 优先级排序 + 分类统计 + 静动态交叉验证
    """

    def __init__(self):
        self.filter = FalsePositiveFilter()
        self.scorer = PriorityScorer()
        self.classifier = DefectClassifier()
        self.result_correlator = ResultCorrelator()  # ⭐ 动态分析关联器
        self.validation_rules = self._load_validation_rules()
        self.default_options = {
            "enable_filtering": True,
            "enable_scoring": True,
            "filter_level": "low",
        }
        log_info("ValidationAgent 初始化完成（支持动态分析）")

    def process(
        self,
        issues: List[Dict[str, Any]],
        context: Dict[str, Any],
        options: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """处理静态分析结果（原有方法）"""
        raw_issue_count = len(issues) if issues else 0
        log_info(f"[ValidationAgent] process - 收到 {raw_issue_count} 个 issues")

        try:
            print("!!! [DEBUG] Entering ValidationAgent.process try block.", flush=True)

            # 合并配置
            opts: Dict[str, Any] = dict(self.default_options or {})
            opts.update(context.get("options") or {})
            opts.update(options or {})
            log_info(f"[ValidationAgent] process - 合并后选项: {opts}")

            # 防御式拷贝
            raw_issues: List[Dict[str, Any]] = [dict(it or {}) for it in (issues or [])]
            before = len(raw_issues)

            if before == 0:
                print("[ValidationAgent] 收到 0 个 issues, 跳过处理")
                log_info("[ValidationAgent] process - 输入 issues 为空, 跳过")
                return {
                    "success": True,
                    "issues": [],
                    "statistics": {"before": 0, "after": 0, "filtered": 0},
                    "categories": {},
                }

            # 字段规范化 / 分类
            log_info("[ValidationAgent] process - 开始规范化和分类...")
            for i, it in enumerate(raw_issues):
                try:
                    it["file"] = it.get("file") or it.get("path") or "unknown"
                    it["line"] = it.get("line") if isinstance(it.get("line"), int) else 0
                    
                    original_category = it.get("category")
                    calculated_category = self.classifier.classify(it)
                    it["category"] = original_category or calculated_category
                    if not original_category:
                        log_info(f"  - Issue {i}: 自动分类为 '{calculated_category}' (file: {it['file']})")
                    
                    original_severity = it.get("severity")
                    normalized_severity = _norm_sev(original_severity)
                    it["severity"] = normalized_severity
                    if original_severity != normalized_severity:
                        log_info(f"  - Issue {i}: 严重性从 '{original_severity}' 规范化为 '{normalized_severity}'")
                        
                except Exception as norm_err:
                    log_error(f"[ValidationAgent] process - 规范化 Issue {i} 时出错: {norm_err}", exc_info=True)
                    it["category"] = it.get("category", "unknown_norm_error")
                    it["severity"] = it.get("severity", "low")
                    
            log_info("[ValidationAgent] process - 规范化和分类完成")

            # 误报过滤
            log_info(f"[ValidationAgent] 开始过滤 ({len(raw_issues)} issues)...")
            try:
                filtered = self.filter.apply(raw_issues, context)
                if not isinstance(filtered, list):
                    log_error(f"FalsePositiveFilter.apply() 返回非列表: {type(filtered)}")
                    filtered = raw_issues
                log_info(f"[ValidationAgent] 过滤完成: {len(filtered)} issues")
            except Exception as filter_err:
                log_error(f"FalsePositiveFilter 异常: {filter_err}", exc_info=True)
                filtered = raw_issues

            # 去重合并
            log_info(f"[ValidationAgent] process - 开始去重合并 (输入 {len(filtered)} 个 issues)...")
            bucket: Dict[Tuple, Dict[str, Any]] = {}
            counts: Dict[Tuple, int] = {}
            sev_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
            
            def _key(i: Dict) -> Tuple:
                return (i.get("file", "unknown"), i.get("line", 0), i.get("category", "unknown"))

            for it in filtered:
                k = _key(it)
                if k not in bucket:
                    it["normalized_severity"] = it.get("severity", "low")
                    bucket[k] = it
                    counts[k] = 1
                else:
                    counts[k] += 1
                    cur = bucket[k].get("normalized_severity", "low")
                    inc = it.get("severity", "low")
                    if sev_rank.get(inc, 0) > sev_rank.get(cur, 0):
                        bucket[k]["normalized_severity"] = inc

            deduped: List[Dict[str, Any]] = []
            for k, it in bucket.items():
                it["merged_count"] = counts[k]
                it["severity"] = it.get("normalized_severity", it.get("severity", "low"))
                deduped.append(it)
            log_info(f"[ValidationAgent] process - 去重合并完成, 输出 {len(deduped)} 个 issues")

            # 优先级评分 & 排序
            log_info(f"[ValidationAgent] process - 开始优先级评分 (输入 {len(deduped)} 个 issues)...")
            ranked_pairs: List[Tuple[float, Dict[str, Any]]] = []
            
            for i, it in enumerate(deduped):
                try:
                    result = self.scorer.score(it, context)
                    
                    if not isinstance(result, tuple) or len(result) != 3:
                        log_error(f"[ValidationAgent] PriorityScorer.score() 返回格式错误 (Issue {i}): {type(result)}, 值={result}")
                        score, breakdown, reason = 0.0, {}, "score_format_error"
                    else:
                        score, breakdown, reason = result
                    
                    it["priority_score"] = float(score) if score is not None else 0.0
                    it["score_breakdown"] = breakdown if isinstance(breakdown, dict) else {}
                    it["rank_reason"] = str(reason) if reason else ""
                    ranked_pairs.append((float(it["priority_score"]), it))
                    
                except Exception as score_err:
                    # ✅ 改进: 更详细的错误日志
                    log_error(
                        f"[ValidationAgent] Issue {i} 评分失败: {score_err}\n"
                        f"  文件: {it.get('file', 'N/A')}\n"
                        f"  行号: {it.get('line', 'N/A')}\n"
                        f"  类型: {it.get('category', 'N/A')}",
                        exc_info=True
                    )
                    it["priority_score"] = 0.0
                    it["score_breakdown"] = {}
                    it["rank_reason"] = f"评分异常: {str(score_err)[:50]}"
                    ranked_pairs.append((0.0, it))
            
            log_info("[ValidationAgent] process - 优先级评分完成")

            # 排序
            log_info("[ValidationAgent] process - 开始排序...")
            ranked_pairs.sort(key=lambda p: p[0], reverse=True)
            log_info("[ValidationAgent] process - 排序完成")

            # 赋予最终排名
            final_issues: List[Dict[str, Any]] = [p[1] for p in ranked_pairs]
            # ✅ 新增：处理空列表情况
            if len(final_issues) == 0:
                log_info("[ValidationAgent] 所有问题被过滤，返回空结果")
                return {
                    "success": True,
                    "issues": [],
                    "statistics": {"before": before, "after": 0, "filtered": before},
                    "categories": {},
                    "stats": {"before": before, "after": 0, "filtered": before}
                }

            for idx, it in enumerate(final_issues, 1):
                it["rank"] = idx

            # 统计 / 分类
            after = len(final_issues)
            stats = {"before": before, "after": after, "filtered": max(0, before - after)}
            categories: Dict[str, int] = {}
            for it in final_issues:
                cat = (it.get("category") or "unknown").lower()
                categories[cat] = categories.get(cat, 0) + 1

            print(f"\n{'='*60}")
            print(f"[ValidationAgent] 处理完成统计:")
            print(f"  - 输入: {before} issues")
            print(f"  - 输出: {after} issues")
            print(f"  - 过滤: {stats['filtered']} issues")
            print(f"{'='*60}\n")

            log_info(f"[ValidationAgent] process - 处理完成: 输出 {after} issues, before={before}, filtered={stats['filtered']}")
            print("!!! [DEBUG] ValidationAgent.process try block completed successfully.", flush=True)

            out = {
                "success": True,
                "issues": final_issues,
                "statistics": stats,
                "categories": categories,
            }
            out["stats"] = stats
            return out

        except Exception as e:
            print(f"!!! [FATAL DEBUG] Exception in ValidationAgent: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            
            log_error(f"[ValidationAgent] 处理失败: {e}", exc_info=True)
            
            return {
                "success": False,
                "error": str(e),
                "issues": issues,
                "statistics": {"before": raw_issue_count, "after": raw_issue_count, "filtered": 0},
                "categories": {},
            }
    
    # ========== ⭐ 新增方法：静动态交叉验证 ⭐ ==========
    
    async def validate_static_results(
        self,
        static_issues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """校验静态分析结果"""
        try:
            log_info(f"开始校验静态分析结果，共 {len(static_issues)} 个问题")
            
            validated_issues = []
            filtered_issues = []
            
            for issue in static_issues:
                if self._validate_issue_structure(issue):
                    normalized = self._normalize_issue(issue)
                    validated_issues.append(normalized)
                else:
                    filtered_issues.append({
                        'issue': issue,
                        'reason': '问题结构不完整'
                    })
            
            log_info(f"校验完成，有效问题: {len(validated_issues)}, 过滤问题: {len(filtered_issues)}")
            
            return {
                'success': True,
                'validated_issues': validated_issues,
                'filtered_issues': filtered_issues,
                'validation_summary': {
                    'total_input': len(static_issues),
                    'validated': len(validated_issues),
                    'filtered': len(filtered_issues)
                }
            }
            
        except Exception as e:
            log_error(f"静态结果校验失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def cross_validate_with_dynamic(
        self,
        static_issues: List[Dict[str, Any]],
        dynamic_issues: List[Dict[str, Any]],
        tolerance: int = 5
    ) -> Dict[str, Any]:
        """静动态交叉验证"""
        try:
            log_info("开始静动态交叉验证")
            
            # 先校验静态结果
            static_validation = await self.validate_static_results(static_issues)
            
            if not static_validation.get('success'):
                return static_validation
            
            validated_static = static_validation['validated_issues']
            
            # 关联静动态结果
            correlation_result = self.result_correlator.correlate_results(
                validated_static,
                dynamic_issues,
                tolerance
            )
            
            if not correlation_result.get('success'):
                return correlation_result
            
            # 提取关联后的问题
            confirmed_issues = correlation_result.get('confirmed_issues', [])
            static_only_issues = correlation_result.get('static_only_issues', [])
            dynamic_only_issues = correlation_result.get('dynamic_only_issues', [])
            
            # 应用置信度过滤
            high_confidence = [
                issue for issue in confirmed_issues
                if issue.get('confidence', 0) >= 0.8
            ]
            
            medium_confidence = [
                issue for issue in (confirmed_issues + static_only_issues + dynamic_only_issues)
                if 0.5 <= issue.get('confidence', 0) < 0.8
            ]
            
            low_confidence = [
                issue for issue in (confirmed_issues + static_only_issues + dynamic_only_issues)
                if issue.get('confidence', 0) < 0.5
            ]
            
            # 生成验证报告
            validation_report = {
                'high_confidence_issues': high_confidence,
                'medium_confidence_issues': medium_confidence,
                'low_confidence_issues': low_confidence,
                'dynamic_exclusive_issues': dynamic_only_issues,
                'statistics': correlation_result.get('statistics', {}),
                'recommendations': self._generate_recommendations(
                    high_confidence,
                    medium_confidence,
                    low_confidence,
                    dynamic_only_issues
                )
            }
            
            log_info(f"交叉验证完成: 高置信度 {len(high_confidence)}, 中置信度 {len(medium_confidence)}, 低置信度 {len(low_confidence)}")
            
            return {
                'success': True,
                'correlation_result': correlation_result,
                'validation_report': validation_report,
                'total_validated_issues': len(high_confidence) + len(medium_confidence) + len(low_confidence)
            }
            
        except Exception as e:
            log_error(f"交叉验证失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ========== 辅助方法 ==========
    
    def _load_validation_rules(self) -> Dict[str, Any]:
        """加载校验规则"""
        return {
            'min_confidence_threshold': 0.5,
            'require_location': True,
            'severity_mapping': {
                'error': 'high',
                'warning': 'medium',
                'info': 'low',
                'note': 'low'
            }
        }
    
    def _validate_issue_structure(self, issue: Dict[str, Any]) -> bool:
        """验证问题结构是否完整"""
        required_fields = ['file', 'line']
        
        for field in required_fields:
            if field not in issue or not issue[field]:
                return False
        
        if not isinstance(issue.get('line'), int) or issue['line'] < 1:
            return False
        
        return True
    
    def _normalize_issue(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        """标准化问题格式"""
        normalized = issue.copy()
        
        # 标准化严重性
        if 'severity' in normalized:
            severity = normalized['severity'].lower()
            normalized['severity'] = self.validation_rules['severity_mapping'].get(
                severity,
                severity
            )
        else:
            normalized['severity'] = 'medium'
        
        # 设置默认置信度
        if 'confidence' not in normalized:
            normalized['confidence'] = 0.6
        
        # 设置默认优先级
        if 'priority' not in normalized:
            severity_priority = {
                'critical': 90,
                'high': 70,
                'medium': 50,
                'low': 30
            }
            normalized['priority'] = severity_priority.get(normalized['severity'], 50)
        
        # 标准化类别
        if 'category' not in normalized:
            issue_type = normalized.get('type', '').lower()
            if 'leak' in issue_type or 'memory' in issue_type:
                normalized['category'] = 'memory_safety'
            elif 'buffer' in issue_type or 'overflow' in issue_type:
                normalized['category'] = 'memory_safety'
            elif 'null' in issue_type or 'pointer' in issue_type:
                normalized['category'] = 'null_pointer'
            elif 'thread' in issue_type or 'race' in issue_type:
                normalized['category'] = 'concurrency'
            else:
                normalized['category'] = 'general'
        
        return normalized
    
    def _generate_recommendations(
        self,
        high_confidence: List[Dict],
        medium_confidence: List[Dict],
        low_confidence: List[Dict],
        dynamic_only: List[Dict]
    ) -> List[str]:
        """生成修复建议"""
        recommendations = []
        
        if high_confidence:
            recommendations.append(
                f"🔴 发现 {len(high_confidence)} 个高置信度问题（静动态确认），建议优先修复"
            )
        
        if medium_confidence:
            recommendations.append(
                f"🟡 发现 {len(medium_confidence)} 个中置信度问题，建议审查后修复"
            )
        
        if low_confidence:
            recommendations.append(
                f"⚪ 发现 {len(low_confidence)} 个低置信度问题，可能存在误报，建议人工验证"
            )
        
        if dynamic_only:
            recommendations.append(
                f"🔍 动态分析独立发现 {len(dynamic_only)} 个问题，建议优化静态分析规则以覆盖这些场景"
            )
        
        critical_count = sum(1 for issue in high_confidence if issue.get('severity') == 'critical')
        if critical_count > 0:
            recommendations.append(
                f"⚠️ 发现 {critical_count} 个严重问题，建议立即处理"
            )
        
        return recommendations
