from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import logging
from pathlib import Path
import json

from backend.services.metrics_service import MetricsService
from backend.services.report_generator import ReportGenerator
from backend.utils.chart_generator import ChartGenerator
from backend.database import get_db
from backend.database.crud import get_analysis, get_project_analyses
from config import settings  # ✅ 新增：获取结果目录配置

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["metrics"])


def load_analysis_result(analysis_id: str) -> Dict[str, Any]:
    """从文件系统加载分析结果"""
    # ✅ 修复路径：data/results/{analysis_id}/analysis_result.json
    result_file = Path(settings.RESULTS_DIR) / analysis_id / "analysis_result.json"

    if not result_file.exists():
        raise HTTPException(
            status_code=404, detail=f"Analysis result file not found at: {result_file}"
        )

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in result file: {e}")
        raise HTTPException(
            status_code=500, detail=f"Invalid JSON format in result file"
        )
    except Exception as e:
        logger.error(f"Failed to load result file: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load analysis result: {str(e)}"
        )


@router.get("/metrics/summary/{analysis_id}")
async def get_metrics_summary(analysis_id: str, db: Session = Depends(get_db)):
    """获取分析任务的综合指标"""
    try:
        # 1. 验证分析记录是否存在
        analysis = get_analysis(db, analysis_id)
        if not analysis:
            raise HTTPException(
                status_code=404, detail=f"Analysis {analysis_id} not found"
            )

        # 2. 从文件系统加载分析结果 ✅ 修复
        analysis_result = load_analysis_result(analysis_id)

        # 3. 计算综合指标
        metrics = MetricsService.calculate_comprehensive_metrics(analysis_result)

        return {
            "analysis_id": analysis_id,
            "project_id": analysis.project_id,
            "status": analysis.status,
            "metrics": metrics,
            "timestamp": metrics["timestamp"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to calculate metrics for {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/reports/generate/{analysis_id}")
async def generate_reports(
    analysis_id: str, formats: List[str] = None, db: Session = Depends(get_db)
):
    """生成多格式报告"""
    try:
        if formats is None:
            formats = ["html", "markdown", "json", "charts"]

        # 1. 验证分析记录
        analysis = get_analysis(db, analysis_id)
        if not analysis:
            raise HTTPException(
                status_code=404, detail=f"Analysis {analysis_id} not found"
            )

        # 2. 从文件系统加载分析结果 ✅ 修复
        analysis_result = load_analysis_result(analysis_id)

        # 3. 计算指标
        metrics = MetricsService.calculate_comprehensive_metrics(analysis_result)

        # 4. 准备输出目录
        output_dir = Path(settings.RESULTS_DIR).parent / "reports" / analysis_id
        output_dir.mkdir(parents=True, exist_ok=True)

        charts_dir = output_dir / "charts"
        charts_dir.mkdir(exist_ok=True)

        generator = ReportGenerator()
        chart_gen = ChartGenerator()
        generated_files = {}

        # 5. 生成HTML报告
        if "html" in formats:
            html_path = generator.generate_html_report(
                analysis_result, metrics, str(output_dir / "report.html")
            )
            generated_files["html"] = html_path

        # 6. 生成Markdown报告
        if "markdown" in formats:
            md_path = generator.generate_markdown_report(
                analysis_result, metrics, str(output_dir / "report.md")
            )
            generated_files["markdown"] = md_path

        # 7. 生成JSON报告
        if "json" in formats:
            json_path = output_dir / "report.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "analysis_id": analysis_id,
                        "project_id": analysis.project_id,
                        "analysis_type": analysis.analysis_type,
                        "status": analysis.status,
                        "metrics": metrics,
                        "raw_result": analysis_result,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            generated_files["json"] = str(json_path)

        # 8. 生成图表
        if "charts" in formats:
            charts = {}

            severity_dist = analysis_result["summary"]["severity_distribution"]
            if severity_dist:
                charts["severity"] = chart_gen.generate_severity_distribution_chart(
                    severity_dist, str(charts_dir / "severity_distribution.png")
                )

            tool_stats = metrics["tools_comparison"]["counts"]
            if tool_stats:
                charts["tools"] = chart_gen.generate_tool_comparison_chart(
                    tool_stats, str(charts_dir / "tool_comparison.png")
                )

            issues = analysis_result.get("issues", [])
            if issues:
                charts["files"] = chart_gen.generate_file_heatmap(
                    issues, str(charts_dir / "file_heatmap.png")
                )

            generated_files["charts"] = charts

        logger.info(f"Reports generated for analysis {analysis_id}")

        return {
            "analysis_id": analysis_id,
            "status": "success",
            "generated_files": generated_files,
            "output_directory": str(output_dir),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate reports for {analysis_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Report generation failed: {str(e)}"
        )


@router.get("/reports/download/{analysis_id}/{format}")
async def download_report(analysis_id: str, format: str, db: Session = Depends(get_db)):
    """下载指定格式的报告文件"""
    from fastapi.responses import FileResponse

    try:
        analysis = get_analysis(db, analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")

        report_dir = Path(settings.RESULTS_DIR).parent / "reports" / analysis_id

        format_map = {
            "html": report_dir / "report.html",
            "markdown": report_dir / "report.md",
            "json": report_dir / "report.json",
        }

        if format not in format_map:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid format: {format}. Must be one of {list(format_map.keys())}",
            )

        file_path = format_map[format]

        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Report file not found. Please generate reports first.",
            )

        media_types = {
            "html": "text/html",
            "markdown": "text/markdown",
            "json": "application/json",
        }

        return FileResponse(
            path=str(file_path),
            media_type=media_types[format],
            filename=f"analysis_{analysis_id}.{format}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/quality-score/{analysis_id}")
async def get_quality_score(analysis_id: str, db: Session = Depends(get_db)):
    """快速获取代码质量评分"""
    try:
        analysis = get_analysis(db, analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")

        # 从文件系统加载 ✅ 修复
        analysis_result = load_analysis_result(analysis_id)

        metrics = MetricsService.calculate_comprehensive_metrics(analysis_result)
        quality_score = metrics["quality_score"]

        return {
            "analysis_id": analysis_id,
            "quality_score": quality_score["score"],
            "grade": quality_score["grade"],
            "breakdown": quality_score["breakdown"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get quality score: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/comparison/{project_id}")
async def get_analysis_comparison(project_id: str, db: Session = Depends(get_db)):
    """获取同一项目多次分析的对比数据"""
    try:
        analyses = get_project_analyses(db, project_id)

        if not analyses:
            raise HTTPException(
                status_code=404, detail="No analyses found for this project"
            )

        trend_data = []
        for analysis in analyses:
            try:
                # 从文件系统加载 ✅ 修复
                analysis_result = load_analysis_result(analysis.id)
                metrics = MetricsService.calculate_comprehensive_metrics(
                    analysis_result
                )

                trend_data.append(
                    {
                        "analysis_id": analysis.id,
                        "timestamp": analysis.start_time.isoformat() + "Z",
                        "quality_score": metrics["quality_score"]["score"],
                        "total_issues": metrics["detection"]["total_issues"],
                        "high_severity": metrics["detection"][
                            "severity_distribution"
                        ].get("high", 0),
                        "status": analysis.status,
                    }
                )
            except Exception as e:
                logger.warning(f"Skipping analysis {analysis.id}: {e}")
                continue

        return {
            "project_id": project_id,
            "total_analyses": len(trend_data),
            "trend_data": trend_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get comparison data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
