# -*- coding: utf-8 -*-
"""
Simple AST-like parser for C/C++ (regex-based fallback)
轻量级C/C++函数定义与调用提取器（迭代5使用）
"""
import re
import os
import json  # 保留以兼容外部可能的引用
from typing import List, Dict, Any

# 模块对外可用符号（供 import * 或 getattr 安全引用）
__all__ = ["parse_file", "parse_project"]

# 粗粒度函数定义与调用模式（基于正则的降级实现）
FUNC_DEF_PAT = re.compile(
    r'(?P<ret>[\w:\<\>\s\*\&~]+?)\s+(?P<name>[A-Za-z_][\w:<>]*)\s*\((?P<args>[^)]*)\)\s*(\{|;)',
    re.M,
)
CALL_PAT = re.compile(r'(?P<name>[A-Za-z_][\w:]*)\s*\(', re.M)


def parse_file(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """解析单个 C/C++ 文件，返回函数定义与调用（正则近似）
    返回:
        {
            "functions": [{"name","ret","args","line"}...],
            "calls": [{"name","line"}...]
        }
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    except Exception:
        return {"functions": [], "calls": []}

    functions: List[Dict[str, Any]] = []
    for m in FUNC_DEF_PAT.finditer(txt):
        name = m.group("name")
        start = txt.count("\n", 0, m.start()) + 1
        functions.append(
            {
                "name": name,
                "ret": m.group("ret").strip(),
                "args": m.group("args").strip(),
                "line": start,
            }
        )

    calls: List[Dict[str, Any]] = []
    keywords = {"if", "for", "while", "switch", "return", "sizeof", "catch", "new"}
    for m in CALL_PAT.finditer(txt):
        n = m.group("name")
        if n in keywords:
            continue
        start = txt.count("\n", 0, m.start()) + 1
        calls.append({"name": n, "line": start})

    return {"functions": functions, "calls": calls}


def parse_project(project_root: str, extensions: List[str] | None = None) -> Dict[str, Any]:
    """递归解析整个项目，聚合函数定义与调用信息

    参数:
        project_root: 项目根目录
        extensions: 需要解析的文件后缀列表（默认包含常见 C/C++ 扩展名）

    返回:
        {
          "files": { "rel/path.cpp": {"functions":[...], "calls":[...]} },
          "functions": [ { "name": "...", "file": "rel/path.cpp", "line": 123, "signature": "..." }, ... ]
        }
    """
    if not project_root:
        raise ValueError("parse_project: project_root is required")

    project_root = os.path.abspath(project_root)
    if not os.path.isdir(project_root):
        raise NotADirectoryError(f"parse_project: not a directory: {project_root}")

    extensions = extensions or [".c", ".cpp", ".cc", ".h", ".hpp", ".cxx"]

    result: Dict[str, Any] = {"files": {}, "functions": []}
    for dirpath, _, filenames in os.walk(project_root):
        for fn in filenames:
            if not any(fn.lower().endswith(ext) for ext in extensions):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, project_root)
            try:
                parsed = parse_file(fp)
            except Exception:
                # 单文件失败不影响整体；记录为空结果继续前进
                parsed = {"functions": [], "calls": []}
            result["files"][rel] = parsed
            for func in parsed.get("functions", []):
                fmeta = dict(func)
                fmeta["file"] = rel
                result["functions"].append(fmeta)

    return result