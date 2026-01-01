# -*- coding: utf-8 -*-
"""Call graph builder using ast_parser (Iteration 5)"""

import os
import json
import importlib
import traceback
from typing import Dict, Any, List, Optional

# ---- 动态导入 ast_parser，兼容不同运行目录/包结构 ----
def _import_ast_parser():
    for mod in ("backend.tools.ast_parser", "tools.ast_parser", "ast_parser"):
        try:
            return importlib.import_module(mod)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError("ast_parser module not found in any known path")

ast_parser = _import_ast_parser()

# 优先使用模块自带的 parse_project；若缺失则用 parse_file 兜底实现一个
parse_project = getattr(ast_parser, "parse_project", None)
if parse_project is None:
    parse_file = getattr(ast_parser, "parse_file", None)
    if parse_file is None:
        raise ImportError("ast_parser has neither parse_project nor parse_file")

    def parse_project(project_root: str, extensions: Optional[List[str]] = None) -> Dict[str, Any]:
        """fallback: 基于 parse_file 拼装项目级解析结果"""
        project_root = os.path.abspath(project_root)
        extensions = extensions or [".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"]
        result: Dict[str, Any] = {"files": {}, "functions": []}
        for dirpath, _, filenames in os.walk(project_root):
            for fn in filenames:
                if any(fn.lower().endswith(ext) for ext in extensions):
                    fp = os.path.join(dirpath, fn)
                    rel = os.path.relpath(fp, project_root)
                    parsed = parse_file(fp)
                    result["files"][rel] = parsed
                    for func in parsed.get("functions", []):
                        fmeta = dict(func)
                        fmeta["file"] = rel
                        result["functions"].append(fmeta)
        return result


def build_call_graph(project_root: str, out_path: Optional[str] = None) -> Dict[str, Any]:
    """
    扫描全项目，生成函数索引 & 调用边
    返回:
        {
          "functions": { name: [ {file,line,args?}, ... ] },
          "call_edges": [ {from,to,file,line,callee?}, ... ]
        }
    """
    if not project_root:
        raise ValueError("build_call_graph: project_root is required")
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        raise NotADirectoryError(f"build_call_graph: not a directory: {root}")

    # ---- 项目解析（带清晰错误栈，便于定位）----
    try:
        proj = parse_project(root)
    except Exception as e:
        raise RuntimeError(f"parse_project failed: {e}\n{traceback.format_exc()}")

    # ---- 构建函数索引 ----
    func_index: Dict[str, List[Dict[str, Any]]] = {}
    for f in proj.get("functions", []):
        func_index.setdefault(f.get("name", ""), []).append(
            {
                "file": f.get("file"),
                "line": f.get("line"),
                "args": f.get("args"),
            }
        )

    # ---- 基于每个文件的调用记录生成调用边 ----
    edges: List[Dict[str, Any]] = []
    files = proj.get("files", {})
    for rel, parsed in files.items():
        parsed = parsed or {}
        funcs_in_file = [f for f in proj.get("functions", []) if f.get("file") == rel]
        funcs_in_file.sort(key=lambda x: x.get("line", 0))

        for call in parsed.get("calls", []):
            call_line = call.get("line", 0)
            # 找到包围该调用的最近的函数定义（同文件内按行号）
            enclosing = None
            for fn in funcs_in_file:
                if (fn.get("line") or 0) <= call_line:
                    enclosing = fn
                else:
                    break
            caller = enclosing.get("name") if enclosing else f"<global::{rel}>"

            # 简单的被调候选（同名函数中任选其一，可视需要再做消歧）
            callee_name = call.get("name")
            callee_candidates = func_index.get(callee_name, [])
            callee_ref = None
            if callee_candidates:
                c = callee_candidates[0]
                if c.get("file") is not None and c.get("line") is not None:
                    callee_ref = f"{c['file']}:{c['line']}"

            edges.append(
                {
                    "from": caller,
                    "to": callee_name,
                    "file": rel,
                    "line": call_line,
                    "callee": callee_ref,
                }
            )

    graph: Dict[str, Any] = {"functions": func_index, "call_edges": edges}

    if out_path:
        # 允许只给文件名（当前目录），此时不创建空目录名
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(graph, fh, indent=2, ensure_ascii=False)

    return graph

