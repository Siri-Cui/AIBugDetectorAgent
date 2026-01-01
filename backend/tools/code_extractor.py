# -*- coding: utf-8 -*-
"""
改进版 CodeExtractor v2
支持多行函数签名、模板、类作用域、构造/析构函数等复杂 C++ 语法。
"""
"""
代码提取器
作用：提取缺陷周围的真实代码上下文（完整函数体+周围代码）
依赖：re、os、typing、utils.logger
调用关系：被repair_generator_agent调用
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from utils.logger import log_info, log_error


# ✅ 新版正则：支持多行、模板、类作用域、修饰符、返回类型
FUNC_START_RE = re.compile(
    r"""
    ^[ \t]*(?:template\s*<[^>]+>\s*)*        # 模板声明
    (?:inline|static|virtual|constexpr|explicit|friend|typename)?\s*  # 修饰符
    (?:[\w:\<\>\*\&\s]+)?                    # 返回类型（可为空，如构造函数）
    [A-Za-z_]\w*(?:::[A-Za-z_]\w*)*\s*       # 函数名或作用域
    \([^)]*\)?                               # 参数列表（允许为空）
    [ \t]*(?:const|noexcept|override|final)? # 可选关键字
    [ \t]*(?:->\s*[\w:\<\>\*&]+)?            # 可选返回类型
    [ \t]*(?:\{|$)                           # 行尾或函数体开始
    """,
    re.MULTILINE | re.VERBOSE
)


class CodeExtractor:
    """代码上下文提取器"""

    def __init__(self):
        self.compiled_patterns = [FUNC_START_RE]

    # ===============================================================
    # 主入口
    # ===============================================================
    def extract_context(
        self, file_path: str, defect_line: int,
        context_lines: int = 10, project_path: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            actual_file_path = self._resolve_file_path(file_path, project_path)
            if not actual_file_path or not os.path.exists(actual_file_path):
                log_error(f"文件不存在或无法找到: {file_path}")
                return self._empty_context(file_path, defect_line)

            with open(actual_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            if defect_line < 1 or defect_line > len(lines):
                log_error(f"行号越界: {defect_line}，文件共{len(lines)}行")
                return self._empty_context(file_path, defect_line)

            defect_line_content = lines[defect_line - 1].rstrip()
            start = max(0, defect_line - context_lines - 1)
            end = min(len(lines), defect_line + context_lines)
            context_before = ''.join(lines[start:defect_line - 1])
            context_after = ''.join(lines[defect_line:end])

            function_info = self._extract_function_body(lines, defect_line)
            class_info = self._extract_class_context(lines, defect_line)
            includes = self._extract_includes(lines)

            return {
                'file': actual_file_path,
                'defect_line': defect_line,
                'defect_line_content': defect_line_content,
                'context': {'before': context_before, 'after': context_after},
                'function': function_info,
                'class_context': class_info,
                'includes': includes,
                'total_lines': len(lines)
            }

        except Exception as e:
            log_error(f"提取代码上下文失败: {str(e)}")
            return self._empty_context(file_path, defect_line)

    # ===============================================================
    # 智能文件路径解析
    # ===============================================================
    def _resolve_file_path(self, file_path: str, project_path: Optional[str]) -> Optional[str]:
        if os.path.isabs(file_path) and os.path.exists(file_path):
            return file_path
        if project_path:
            candidate = os.path.join(project_path, file_path)
            if os.path.exists(candidate):
                return candidate
            filename = os.path.basename(file_path)
            for root, dirs, files in os.walk(project_path):
                if filename in files:
                    return os.path.join(root, filename)
        if os.path.exists(file_path):
            return file_path
        return None

    # ===============================================================
    # 函数体提取核心逻辑
    # ===============================================================
    def _extract_function_body(self, lines: List[str], defect_line: int) -> Dict[str, Any]:
        try:
            func_start = self._find_function_start(lines, defect_line - 1)
            if func_start is None:
                return {'found': False, 'name': 'unknown', 'signature': '', 'body': '', 'start_line': 0, 'end_line': 0}
            func_end = self._find_function_end(lines, func_start)
            func_name, func_signature = self._parse_function_signature(lines, func_start)
            body = ''.join(lines[func_start:func_end + 1])
            return {
                'found': True,
                'name': func_name,
                'signature': func_signature,
                'body': body,
                'start_line': func_start + 1,
                'end_line': func_end + 1
            }
        except Exception as e:
            log_error(f"提取函数体失败: {str(e)}")
            return {'found': False}

    # ===============================================================
    # 🔍 改进函数起点搜索（多行拼接）
    # ===============================================================
    def _find_function_start(self, lines: List[str], start_line: int) -> Optional[int]:
        for i in range(start_line, max(-1, start_line - 400), -1):
            snippet = ""
            for j in range(max(0, i - 6), i + 1):  # 向上拼接最多6行
                snippet += lines[j]
            if FUNC_START_RE.search(snippet):
                return max(0, i - 6)
        return None

    # ===============================================================
    # 改进花括号匹配
    # ===============================================================
    def _find_function_end(self, lines: List[str], start: int) -> int:
        brace_count = 0
        found_brace = False
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == '{':
                    brace_count += 1
                    found_brace = True
                elif ch == '}':
                    brace_count -= 1
            if found_brace and brace_count == 0:
                return i
        return len(lines) - 1

    # ===============================================================
    # 提取函数签名
    # ===============================================================
    def _parse_function_signature(self, lines: List[str], start_line: int) -> Tuple[str, str]:
        snippet = ""
        for i in range(start_line, min(len(lines), start_line + 10)):
            snippet += lines[i]
            if "{" in lines[i]:
                break
        snippet = snippet.strip()
        match = re.search(r'([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\([^)]*\)', snippet)
        name = match.group(1) if match else 'unknown'
        clean_sig = re.sub(r'\s+', ' ', snippet.split("{")[0]).strip()
        return name, clean_sig

    # ===============================================================
    # 类上下文提取
    # ===============================================================
    def _extract_class_context(self, lines: List[str], defect_line: int) -> Optional[Dict[str, Any]]:
        for i in range(defect_line - 1, max(-1, defect_line - 200), -1):
            match = re.match(r'^\s*(class|struct)\s+(\w+)', lines[i])
            if match:
                return {'type': match.group(1), 'name': match.group(2), 'line': i + 1}
        return None

    # ===============================================================
    # include 提取
    # ===============================================================
    def _extract_includes(self, lines: List[str]) -> List[str]:
        includes = []
        for line in lines[:100]:
            match = re.match(r'^\s*#include\s*[<"]([^>"]+)[>"]', line)
            if match:
                includes.append(match.group(1))
        return includes

    # ===============================================================
    # 辅助函数
    # ===============================================================
    def _empty_context(self, file_path: str, defect_line: int) -> Dict[str, Any]:
        return {
            'file': file_path,
            'defect_line': defect_line,
            'defect_line_content': '',
            'context': {'before': '', 'after': ''},
            'function': {'found': False},
            'class_context': None,
            'includes': [],
            'error': 'Failed to extract context'
        }

    def extract_multiple_contexts(self, issues: List[Dict[str, Any]], project_path: str) -> Dict[str, Dict[str, Any]]:
        contexts = {}
        for issue in issues:
            issue_id = issue.get('id')
            file_rel = issue.get('file', '')
            line = issue.get('line', 0)
            context = self.extract_context(file_path=file_rel, defect_line=line, project_path=project_path)
            contexts[issue_id] = context
        return contexts

