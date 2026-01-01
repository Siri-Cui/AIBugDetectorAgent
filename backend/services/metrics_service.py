from typing import Dict, Any, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MetricsService:
    """指标计算服务 - 基于现有JSON数据进行二次计算"""

    @staticmethod
    def calculate_comprehensive_metrics(
        analysis_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        基于完整的分析结果计算综合指标

        参数:
            analysis_result: 从数据库或API获取的完整分析结果（就是你给的那个JSON）

        返回:
            重组后的指标数据
        """
        summary = analysis_result.get("summary", {})
        issues = analysis_result.get("issues", [])

        # 1. 检测效果指标
        detection_metrics = {
            "total_issues": summary.get("total_issues", 0),
            "files_analyzed": summary.get("files_analyzed", 0),
            "severity_distribution": summary.get("severity_distribution", {}),
            # 计算误报率（基于动态验证）
            "false_positive_estimation": MetricsService._estimate_false_positive_rate(
                summary.get("validated_before", 0), summary.get("validated_after", 0)
            ),
            # 计算各类型分布
            "category_distribution": MetricsService._calculate_category_distribution(
                issues
            ),
            # 动态验证确认率
            "dynamic_confirmation_rate": MetricsService._calculate_confirmation_rate(
                summary.get("cross_validation", {})
            ),
        }

        # 2. 修复效果指标
        repair_metrics = {
            "suggestions_generated": summary.get("repairs_generated", 0),
            "with_real_code_context": summary.get("repairs_with_real_code", 0),
            "auto_applicable": sum(
                1
                for r in analysis_result.get("repair_suggestions", [])
                if r.get("can_auto_apply", False)
            ),
            "coverage_rate": MetricsService._calculate_repair_coverage(
                summary.get("total_issues", 0), summary.get("repairs_generated", 0)
            ),
        }

        # 3. 性能指标
        performance_metrics = summary.get("performance", {})
        performance_metrics["breakdown_percentage"] = {
            "static_analysis": round(
                performance_metrics.get("static_time", 0)
                / performance_metrics.get("total_time", 1)
                * 100,
                2,
            ),
            "dynamic_analysis": round(
                performance_metrics.get("dynamic_time", 0)
                / performance_metrics.get("total_time", 1)
                * 100,
                2,
            ),
        }

        # 4. 工具对比指标
        tools_comparison = MetricsService._calculate_tool_contribution(
            issues, summary.get("analysis_tools", [])
        )

        # 5. 代码质量评分（0-100）
        quality_score = MetricsService._calculate_quality_score(
            detection_metrics, analysis_result.get("file_analysis", {})
        )

        return {
            "detection": detection_metrics,
            "repair": repair_metrics,
            "performance": performance_metrics,
            "tools_comparison": tools_comparison,
            "quality_score": quality_score,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    @staticmethod
    def _estimate_false_positive_rate(before: int, after: int) -> float:
        """估计误报率"""
        if before == 0:
            return 0.0
        filtered_count = before - after
        return round(filtered_count / before, 3)

    @staticmethod
    def _calculate_category_distribution(issues: List[Dict]) -> Dict[str, int]:
        """计算问题类型分布"""
        distribution = {}
        for issue in issues:
            category = issue.get("category", "unknown")
            distribution[category] = distribution.get(category, 0) + 1
        return distribution

    @staticmethod
    def _calculate_confirmation_rate(cross_validation: Dict) -> Dict[str, Any]:
        """计算动态验证确认率"""
        total = cross_validation.get("total_validated", 0)
        if total == 0:
            return {"rate": 0.0, "distribution": cross_validation}

        high = cross_validation.get("high_confidence", 0)
        return {"rate": round(high / total, 3), "distribution": cross_validation}

    @staticmethod
    def _calculate_repair_coverage(total_issues: int, repairs: int) -> float:
        """计算修复建议覆盖率"""
        if total_issues == 0:
            return 0.0
        return round(repairs / total_issues, 3)

    @staticmethod
    def _calculate_tool_contribution(
        issues: List[Dict], tools: List[str]
    ) -> Dict[str, Any]:
        """计算各工具的检测贡献"""
        tool_stats = {tool: 0 for tool in tools}

        for issue in issues:
            tool = issue.get("tool", "unknown")
            if tool in tool_stats:
                tool_stats[tool] += 1

        return {"counts": tool_stats, "tools_used": tools}

    @staticmethod
    def _calculate_quality_score(
        detection: Dict, file_analysis: Dict
    ) -> Dict[str, Any]:
        """
        计算代码质量评分（0-100）

        评分规则：
        - 基础分60分
        - 无high问题：+20分
        - 无medium问题：+10分
        - 圈复杂度低：+10分
        """
        base_score = 60

        severity_dist = detection.get("severity_distribution", {})
        high_count = severity_dist.get("high", 0)
        medium_count = severity_dist.get("medium", 0)

        # 严重性扣分
        if high_count == 0:
            base_score += 20
        elif high_count <= 3:
            base_score += 10

        if medium_count == 0:
            base_score += 10
        elif medium_count <= 5:
            base_score += 5

        # 复杂度加分
        complexity = file_analysis.get("complexity_metrics", {}).get(
            "cyclomatic_complexity", 0
        )
        total_lines = file_analysis.get("complexity_metrics", {}).get("code_lines", 1)
        complexity_per_line = complexity / total_lines if total_lines > 0 else 0

        if complexity_per_line < 0.1:
            base_score += 10

        final_score = min(base_score, 100)

        return {
            "score": final_score,
            "grade": MetricsService._get_grade(final_score),
            "breakdown": {
                "base": 60,
                "severity_bonus": base_score - 60,
                "total": final_score,
            },
        }

    @staticmethod
    def _get_grade(score: int) -> str:
        """获取等级"""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
