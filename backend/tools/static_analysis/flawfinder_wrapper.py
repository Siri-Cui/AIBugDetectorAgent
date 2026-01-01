# -*- coding: utf-8 -*-
import subprocess
import asyncio
import csv
import io
from typing import Dict, Any
from utils.logger import log_info, log_error

class FlawfinderWrapper:
    """Flawfinder 安全漏洞扫描封装"""

    async def analyze(self, project_path: str) -> Dict[str, Any]:
        issues = []
        try:
            # Flawfinder 支持直接输出 CSV，方便解析
            cmd = ["flawfinder", "--csv", project_path]
            
            log_info("启动 Flawfinder 安全扫描...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            
            # 解析 CSV
            content = stdout.decode('utf-8', errors='ignore')
            # 跳过 CSV 头部之前的潜在文本，找到 File,Line...
            lines = content.splitlines()
            start_idx = 0
            for i, line in enumerate(lines):
                if line.startswith("File,Line"):
                    start_idx = i
                    break
            
            if start_idx < len(lines):
                csv_content = "\n".join(lines[start_idx:])
                reader = csv.DictReader(io.StringIO(csv_content))
                for row in reader:
                    issues.append({
                        "file": row.get('File'),
                        "line": int(row.get('Line', 0)),
                        "severity": "high" if int(row.get('Level', 1)) >= 4 else "medium",
                        "message": row.get('Warning', '') + " (" + row.get('Suggestion', '') + ")",
                        "tool": "flawfinder",
                        "category": "security"
                    })

            return {"success": True, "issues": issues, "tool_name": "flawfinder"}

        except Exception as e:
            # 如果没装 flawfinder，优雅降级
            log_error(f"Flawfinder 分析失败 (可能未安装): {e}")
            return {"success": False, "error": str(e), "issues": []}
