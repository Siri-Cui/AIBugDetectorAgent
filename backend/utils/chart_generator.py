import matplotlib
import matplotlib.pyplot as plt
from typing import Dict, List, Any
import logging
from pathlib import Path

# ✅ 配置中文字体支持
matplotlib.use("Agg")  # 非GUI后端
plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "DejaVu Sans", "Arial"]
plt.rcParams["axes.unicode_minus"] = False  # 解决负号显示问题

logger = logging.getLogger(__name__)


class ChartGenerator:
    """图表生成器"""

    def __init__(self):
        self._configure_fonts()

    def _configure_fonts(self):
        """配置matplotlib中文字体"""
        try:
            import matplotlib.font_manager as fm

            # 清除字体缓存
            fm._load_fontmanager(try_read_cache=False)

            # 查找中文字体
            chinese_fonts = [
                "WenQuanYi Micro Hei",
                "WenQuanYi Zen Hei",
                "Noto Sans CJK SC",
                "SimHei",
                "Microsoft YaHei",
            ]

            font_list = [f.name for f in fm.fontManager.ttflist]

            for font in chinese_fonts:
                if font in font_list:
                    plt.rcParams["font.sans-serif"] = [font]
                    logger.info(f"✅ Using Chinese font: {font}")
                    return

            logger.warning("⚠️ No Chinese font found, using default")

        except Exception as e:
            logger.error(f"❌ Failed to configure fonts: {e}")

    def generate_severity_distribution_chart(
        self, severity_dist: Dict[str, int], output_path: str
    ) -> str:
        """生成严重度分布饼图"""
        try:
            # 数据准备
            labels = {
                "critical": "严重",
                "high": "高危",
                "medium": "中危",
                "low": "低危",
            }

            colors = {
                "critical": "#dc3545",
                "high": "#fd7e14",
                "medium": "#ffc107",
                "low": "#17a2b8",
            }

            data = []
            label_list = []
            color_list = []

            for severity, count in severity_dist.items():
                if count > 0:
                    data.append(count)
                    label_list.append(f"{labels.get(severity, severity)} ({count})")
                    color_list.append(colors.get(severity, "#6c757d"))

            if not data:
                logger.warning("No data for severity distribution chart")
                return ""

            # 创建图表
            fig, ax = plt.subplots(figsize=(10, 6))

            wedges, texts, autotexts = ax.pie(
                data,
                labels=label_list,
                colors=color_list,
                autopct="%1.1f%%",
                startangle=90,
            )

            # 设置字体大小
            for text in texts:
                text.set_fontsize(12)
            for autotext in autotexts:
                autotext.set_color("white")
                autotext.set_fontsize(10)
                autotext.set_weight("bold")

            ax.set_title("缺陷严重度分布", fontsize=16, pad=20)

            plt.tight_layout()
            plt.savefig(output_path, dpi=300, bbox_inches="tight")
            plt.close()

            logger.info(f"✅ Severity chart generated: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to generate severity chart: {e}")
            return ""

    def generate_tool_comparison_chart(
        self, tool_stats: Dict[str, int], output_path: str
    ) -> str:
        """生成工具对比柱状图"""
        try:
            if not tool_stats:
                logger.warning("No data for tool comparison chart")
                return ""

            # 数据准备
            tool_names = {
                "cppcheck": "Cppcheck",
                "asan": "AddressSanitizer",
                "valgrind_memcheck": "Valgrind Memcheck",
                "memory_pool_specialized": "内存池专项",
            }

            tools = []
            counts = []
            colors = []
            color_map = ["#007bff", "#28a745", "#dc3545", "#ffc107"]

            for i, (tool, count) in enumerate(tool_stats.items()):
                tools.append(tool_names.get(tool, tool))
                counts.append(count)
                colors.append(color_map[i % len(color_map)])

            # 创建图表
            fig, ax = plt.subplots(figsize=(10, 6))

            bars = ax.bar(tools, counts, color=colors, alpha=0.8)

            # 添加数值标签
            for bar in bars:
                height = bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    height,
                    f"{int(height)}",
                    ha="center",
                    va="bottom",
                    fontsize=12,
                )

            ax.set_xlabel("检测工具", fontsize=12)
            ax.set_ylabel("检测问题数", fontsize=12)
            ax.set_title("工具检测效果对比", fontsize=16, pad=20)
            ax.grid(axis="y", alpha=0.3)

            plt.xticks(rotation=15, ha="right")
            plt.tight_layout()
            plt.savefig(output_path, dpi=300, bbox_inches="tight")
            plt.close()

            logger.info(f"✅ Tool comparison chart generated: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to generate tool chart: {e}")
            return ""

    def generate_file_heatmap(
        self, issues: List[Dict[str, Any]], output_path: str, top_n: int = 15
    ) -> str:
        """生成文件问题热力图"""
        try:
            if not issues:
                logger.warning("No issues for file heatmap")
                return ""

            # 统计每个文件的问题数
            file_counts = {}
            for issue in issues:
                file_path = issue.get("file", "unknown")
                # 只保留文件名
                file_name = Path(file_path).name
                file_counts[file_name] = file_counts.get(file_name, 0) + 1

            # 排序并取前N个
            sorted_files = sorted(
                file_counts.items(), key=lambda x: x[1], reverse=True
            )[:top_n]

            if not sorted_files:
                return ""

            files = [f[0] for f in sorted_files]
            counts = [f[1] for f in sorted_files]

            # 创建图表
            fig, ax = plt.subplots(figsize=(10, max(6, len(files) * 0.4)))

            # 颜色映射（问题越多颜色越深）
            colors = plt.cm.Reds([0.3 + (c / max(counts)) * 0.6 for c in counts])

            bars = ax.barh(files, counts, color=colors)

            # 添加数值标签
            for i, (bar, count) in enumerate(zip(bars, counts)):
                ax.text(
                    count,
                    bar.get_y() + bar.get_height() / 2,
                    f" {count}",
                    va="center",
                    fontsize=10,
                )

            ax.set_xlabel("问题数量", fontsize=12)
            ax.set_title(f"文件问题热力图 (Top {len(files)})", fontsize=16, pad=20)
            ax.grid(axis="x", alpha=0.3)

            plt.tight_layout()
            plt.savefig(output_path, dpi=300, bbox_inches="tight")
            plt.close()

            logger.info(f"✅ File heatmap generated: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to generate file heatmap: {e}")
            return ""
