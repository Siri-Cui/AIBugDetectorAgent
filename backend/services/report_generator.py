from typing import Dict, Any
import json
from pathlib import Path
from jinja2 import Template
import logging

logger = logging.getLogger(__name__)


class ReportGenerator:
    """报告生成器 - 生成多格式报告"""

    def __init__(self, template_dir: str = "configs/report_templates"):
        self.template_dir = Path(template_dir)

    def generate_html_report(
        self, analysis_result: Dict[str, Any], metrics: Dict[str, Any], output_path: str
    ) -> str:
        """生成HTML报告"""
        template_path = self.template_dir / "executive_summary.html"

        # 使用Jinja2模板（如果没有模板文件，使用内联模板）
        html_content = self._render_html_template(analysis_result, metrics)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html_content, encoding="utf-8")

        logger.info(f"HTML report generated: {output_path}")
        return str(output_file)

    def generate_markdown_report(
        self, analysis_result: Dict[str, Any], metrics: Dict[str, Any], output_path: str
    ) -> str:
        """生成Markdown报告"""
        md_content = self._build_markdown_content(analysis_result, metrics)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(md_content, encoding="utf-8")

        logger.info(f"Markdown report generated: {output_path}")
        return str(output_file)

    def _render_html_template(self, analysis: Dict, metrics: Dict) -> str:
        """渲染HTML模板"""
        # 简化版内联模板
        html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Bug Detector - 分析报告</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            border-radius: 10px;
            margin-bottom: 30px;
        }
        .score-card {
            display: inline-block;
            background: white;
            padding: 20px;
            border-radius: 10px;
            font-size: 48px;
            font-weight: bold;
            color: {{ score_color }};
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .metric-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .metric-card h3 {
            margin-top: 0;
            color: #667eea;
        }
        .issue-list {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }
        .issue-item {
            border-left: 4px solid #f56565;
            padding: 15px;
            margin: 10px 0;
            background: #fff5f5;
        }
        .issue-item.medium {
            border-left-color: #ed8936;
            background: #fffaf0;
        }
        .severity-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }
        .severity-high {
            background: #fed7d7;
            color: #c53030;
        }
        .severity-medium {
            background: #feebc8;
            color: #c05621;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 AI Bug Detector 分析报告</h1>
        <div class="score-card" style="color: {{ score_color }};">
            {{ quality_score }} / 100
        </div>
        <p>等级: {{ quality_grade }}</p>
        <p>生成时间: {{ timestamp }}</p>
    </div>

    <div class="metrics-grid">
        <div class="metric-card">
            <h3>📊 检测概览</h3>
            <p><strong>总问题数:</strong> {{ total_issues }}</p>
            <p><strong>分析文件:</strong> {{ files_analyzed }}</p>
            <p><strong>高危问题:</strong> <span class="severity-badge severity-high">{{ high_count }}</span></p>
            <p><strong>中危问题:</strong> <span class="severity-badge severity-medium">{{ medium_count }}</span></p>
        </div>

        <div class="metric-card">
            <h3>🛠️ 修复建议</h3>
            <p><strong>生成建议:</strong> {{ repairs_generated }}</p>
            <p><strong>可自动应用:</strong> {{ auto_applicable }}</p>
            <p><strong>覆盖率:</strong> {{ repair_coverage }}%</p>
        </div>

        <div class="metric-card">
            <h3>⚡ 性能统计</h3>
            <p><strong>总耗时:</strong> {{ total_time }}s</p>
            <p><strong>静态分析:</strong> {{ static_time }}s ({{ static_percentage }}%)</p>
            <p><strong>动态验证:</strong> {{ dynamic_time }}s ({{ dynamic_percentage }}%)</p>
        </div>

        <div class="metric-card">
            <h3>✅ 验证结果</h3>
            <p><strong>验证前:</strong> {{ validated_before }}</p>
            <p><strong>验证后:</strong> {{ validated_after }}</p>
            <p><strong>误报率:</strong> {{ false_positive_rate }}%</p>
        </div>
    </div>

    <div class="issue-list">
        <h2>🚨 Top 10 关键问题</h2>
        {% for issue in top_issues %}
        <div class="issue-item {{ issue.severity }}">
            <p><strong>{{ issue.file }}:{{ issue.line }}</strong></p>
            <p>{{ issue.message }}</p>
            <p><span class="severity-badge severity-{{ issue.severity }}">{{ issue.severity }}</span> | 工具: {{ issue.tool }}</p>
        </div>
        {% endfor %}
    </div>
</body>
</html>
        """

        # 准备模板变量
        quality_score = metrics["quality_score"]["score"]
        score_color = (
            "#48bb78"
            if quality_score >= 80
            else ("#ed8936" if quality_score >= 60 else "#f56565")
        )

        top_issues = sorted(
            analysis["issues"],
            key=lambda x: (x.get("severity") == "high", x.get("priority_score", 0)),
            reverse=True,
        )[:10]

        template = Template(html_template)
        return template.render(
            quality_score=quality_score,
            quality_grade=metrics["quality_score"]["grade"],
            score_color=score_color,
            timestamp=metrics["timestamp"],
            total_issues=analysis["summary"]["total_issues"],
            files_analyzed=analysis["summary"]["files_analyzed"],
            high_count=analysis["summary"]["severity_distribution"].get("high", 0),
            medium_count=analysis["summary"]["severity_distribution"].get("medium", 0),
            repairs_generated=metrics["repair"]["suggestions_generated"],
            auto_applicable=metrics["repair"]["auto_applicable"],
            repair_coverage=round(metrics["repair"]["coverage_rate"] * 100, 1),
            total_time=round(metrics["performance"]["total_time"], 2),
            static_time=round(metrics["performance"]["static_time"], 2),
            dynamic_time=round(metrics["performance"]["dynamic_time"], 2),
            static_percentage=metrics["performance"]["breakdown_percentage"][
                "static_analysis"
            ],
            dynamic_percentage=metrics["performance"]["breakdown_percentage"][
                "dynamic_analysis"
            ],
            validated_before=analysis["summary"]["validated_before"],
            validated_after=analysis["summary"]["validated_after"],
            false_positive_rate=round(
                metrics["detection"]["false_positive_estimation"] * 100, 1
            ),
            top_issues=top_issues,
        )

    def _build_markdown_content(self, analysis: Dict, metrics: Dict) -> str:
        """构建Markdown内容"""
        quality_score = metrics["quality_score"]

        md_content = f"""# 🔍 AI Bug Detector 分析报告

## 📊 执行摘要

**代码质量评分**: {quality_score['score']}/100 ({quality_score['grade']}等级)

**生成时间**: {metrics['timestamp']}

---

## 🎯 检测概览

| 指标 | 数值 |
|------|------|
| 总问题数 | {analysis['summary']['total_issues']} |
| 分析文件数 | {analysis['summary']['files_analyzed']} |
| 高危问题 | {analysis['summary']['severity_distribution'].get('high', 0)} |
| 中危问题 | {analysis['summary']['severity_distribution'].get('medium', 0)} |
| 误报率估计 | {round(metrics['detection']['false_positive_estimation'] * 100, 1)}% |

---

## 🛠️ 修复建议

- **生成建议数**: {metrics['repair']['suggestions_generated']}
- **可自动应用**: {metrics['repair']['auto_applicable']}
- **覆盖率**: {round(metrics['repair']['coverage_rate'] * 100, 1)}%

---

## ⚡ 性能统计

- **总耗时**: {round(metrics['performance']['total_time'], 2)}秒
- **静态分析**: {round(metrics['performance']['static_time'], 2)}秒 ({metrics['performance']['breakdown_percentage']['static_analysis']}%)
- **动态验证**: {round(metrics['performance']['dynamic_time'], 2)}秒 ({metrics['performance']['breakdown_percentage']['dynamic_analysis']}%)

---

## 🚨 Top 10 关键问题

"""

        top_issues = sorted(
            analysis["issues"],
            key=lambda x: (x.get("severity") == "high", x.get("priority_score", 0)),
            reverse=True,
        )[:10]

        for i, issue in enumerate(top_issues, 1):
            md_content += f"""
### {i}. {issue['file']}:{issue['line']}

- **严重度**: {issue['severity']}
- **类型**: {issue['category']}
- **工具**: {issue['tool']}
- **描述**: {issue['message']}

"""

        return md_content
