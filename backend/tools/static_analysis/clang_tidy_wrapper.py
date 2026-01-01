# -*- coding: utf-8 -*-
import os
import subprocess
import json
import asyncio
from typing import Dict, Any, List
from utils.logger import log_info, log_error

class ClangTidyWrapper:
    """Clang-Tidy 静态分析工具封装"""
    
    def __init__(self):
        pass

    async def analyze(self, project_path: str) -> Dict[str, Any]:
        """运行 Clang-Tidy 分析"""
        issues = []
        try:
            # 查找所有 cpp/cc/cxx 文件
            files_to_check = []
            for root, _, files in os.walk(project_path):
                for f in files:
                    if f.endswith(('.cpp', '.cc', '.cxx', '.c')):
                        files_to_check.append(os.path.join(root, f))
            
            if not files_to_check:
                return {"success": True, "issues": []}

            # 构造命令：检查性能、可读性、bugprone
            # 注意：没有 compile_commands.json 时，可能需要传入 -- 后面跟编译参数，这里做简化处理
            checks = "-*,bugprone-*,performance-*,readability-*,modernize-use-nullptr,modernize-use-override"
            
            # 限制并发数或每次只跑一部分，防止卡死
            # 这里简单演示跑前 10 个文件，或者你可以全跑
            cmd = ["clang-tidy", f"-checks={checks}"] + files_to_check[:20] + ["--", "-std=c++17"]

            log_info(f"启动 Clang-Tidy 分析 {len(files_to_check)} 个文件...")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            # 解析输出 (Clang-tidy 输出格式: file:line:col: error: message [check-name])
            output = stdout.decode('utf-8', errors='ignore')
            for line in output.splitlines():
                if "error:" in line or "warning:" in line:
                    parts = line.split(':')
                    if len(parts) >= 4:
                        try:
                            file_path = parts[0].strip()
                            line_num = int(parts[1])
                            # 提取 severity 和 message
                            content = ":".join(parts[3:]).strip()
                            
                            issues.append({
                                "file": file_path,
                                "line": line_num,
                                "column": int(parts[2]) if parts[2].isdigit() else 0,
                                "severity": "medium", # Clang-tidy 大多是 medium/high
                                "message": content,
                                "tool": "clang-tidy",
                                "category": "code_quality"
                            })
                        except:
                            continue

            return {
                "success": True, 
                "issues": issues,
                "tool_name": "clang-tidy"
            }

        except Exception as e:
            log_error(f"Clang-Tidy 分析失败: {e}")
            return {"success": False, "error": str(e), "issues": []}
