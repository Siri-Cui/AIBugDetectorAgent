# -*- coding: utf-8 -*-
"""
Dataflow Analyzer for Iteration 5
---------------------------------
该模块在已有调用图基础上进行跨函数变量追踪与资源使用分析。
支持识别：
- 局部变量的定义与使用
- 函数参数的传递链
- 内存资源的分配与释放路径
"""
import os
import re
import json
import importlib
import traceback
from typing import Dict, List, Any, Optional

# ---------- 基础正则 ----------
VAR_DEF = re.compile(r'(?P<type>\w[\w\s\*\&]*)\s+(?P<name>[A-Za-z_]\w*)\s*=\s*[^;]+;')
VAR_USE = re.compile(r'(?P<name>[A-Za-z_]\w*)\s*(\+|-|=|\)|;|,|\])')
MALLOC_CALL = re.compile(r'\b(malloc|calloc|new)\b')
FREE_CALL = re.compile(r'\b(free|delete)\b')


class DataflowAnalyzer:
    """
    用法：
        a = DataflowAnalyzer(project_root="/path/to/project")  # 或传入 call_graph
        res = a.analyze_project()

    关键改动点：
      - 统一 project_root 的赋值与校验，避免“引用前赋值”。
      - 调用图加载流程带兜底与清晰错误栈。
      - analyze_project 支持入参覆盖 self.project_root，且会回写到实例。
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        call_graph_path: Optional[str] = None,
        call_graph: Optional[Dict[str, Any]] = None,
    ):
        self.project_root: Optional[str] = (
            os.path.abspath(project_root) if project_root else None
        )
        # 如果传入现成的调用图，优先使用；否则根据路径加载/构建
        self.call_graph: Dict[str, Any] = call_graph or {}
        # 默认把调用图放到项目目录下 analysis/call_graph.json
        self.call_graph_path: Optional[str] = (
            call_graph_path
            if call_graph_path
            else (
                os.path.join(self.project_root, "analysis", "call_graph.json")
                if self.project_root
                else None
            )
        )

        # 如未给现成的 call_graph，尝试从文件或构建加载
        if not self.call_graph:
            loaded = self._load_call_graph_if_possible()
            if loaded is not None:
                self.call_graph = loaded

    # ---------- 内部工具 ----------
    def _import_call_graph_builder(self):
        """动态导入 call_graph_builder，兼容不同运行目录/包结构"""
        for mod in ("backend.tools.call_graph_builder", "tools.call_graph_builder", "call_graph_builder"):
            try:
                return importlib.import_module(mod)
            except ModuleNotFoundError:
                continue
        raise ModuleNotFoundError("call_graph_builder module not found in any known path")

    def _load_call_graph_if_possible(self) -> Optional[Dict[str, Any]]:
        """尝试加载/构建调用图；如果条件不足则返回 None，由上层在需要时再触发"""
        # 1) 先尝试从文件加载
        if self.call_graph_path and os.path.exists(self.call_graph_path):
            try:
                with open(self.call_graph_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                # 文件存在但损坏，不抛异常，在后续构建分支处理
                pass

        # 2) 再尝试构建（需要有 project_root）
        if self.project_root and os.path.isdir(self.project_root):
            try:
                mod = self._import_call_graph_builder()
                build_call_graph = getattr(mod, "build_call_graph")
                cg = build_call_graph(self.project_root)
                return cg
            except Exception as e:
                # 推迟到真正需要用到调用图时再报错（提高健壮性）
                # 这里记录可读的错误，调用处会统一抛出
                self._last_callgraph_error = f"build_call_graph failed: {e}\n{traceback.format_exc()}"
                return None

        # 条件不足（既没有路径文件，也无法构建）
        return None

    def _ensure_call_graph(self):
        """确保 self.call_graph 可用；如果缺失则尝试构建，否则抛出清晰错误"""
        if self.call_graph:
            return
        # 再尝试一次加载（防止外部在 __init__ 后设置了 project_root/call_graph_path）
        loaded = self._load_call_graph_if_possible()
        if loaded:
            self.call_graph = loaded
            return
        # 到这里还是没有，则抛出清晰错误
        reason = getattr(self, "_last_callgraph_error", "")
        if not self.project_root:
            raise ValueError("DataflowAnalyzer: project_root is required when call_graph is not provided")
        raise RuntimeError(f"DataflowAnalyzer: call_graph unavailable. {reason}")

    # ---------------------------------------------------------
    def analyze_file(self, path: str) -> Dict[str, Any]:
        """分析单个文件中的变量定义与使用"""
        results: Dict[str, Any] = {"variables": {}, "resources": []}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()
        except Exception:
            return results

        # 定义点
        for m in VAR_DEF.finditer(code):
            name = m.group("name")
            line = code.count("\n", 0, m.start()) + 1
            results["variables"].setdefault(name, {"defs": [], "uses": []})
            results["variables"][name]["defs"].append(
                {"line": line, "type": m.group("type").strip()}
            )

        # 使用点（简单近似：仅统计在本文件中已被识别为变量名的使用）
        for m in VAR_USE.finditer(code):
            name = m.group("name")
            if name not in results["variables"]:
                continue
            line = code.count("\n", 0, m.start()) + 1
            results["variables"][name]["uses"].append({"line": line})

        # 资源分配/释放检测（非常轻量的启发式）
        if MALLOC_CALL.search(code) or FREE_CALL.search(code):
            alloc_lines = [code.count("\n", 0, m.start()) + 1 for m in MALLOC_CALL.finditer(code)]
            free_lines = [code.count("\n", 0, m.start()) + 1 for m in FREE_CALL.finditer(code)]
            if alloc_lines and not free_lines:
                results["resources"].append(
                    {
                        "warning": "可能存在内存泄漏",
                        "alloc_lines": alloc_lines,
                        "free_lines": free_lines,
                    }
                )

        return results

    # ---------------------------------------------------------
    def analyze_project(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        """
        扫描整个项目，聚合数据流信息。
        - 优先使用入参 project_root，其次使用 self.project_root
        - 在任何引用前完成赋值与存在性校验
        - 确保调用图可用，以便后续跨函数追踪
        """
        root = os.path.abspath(project_root) if project_root else self.project_root
        if not root:
            raise ValueError("analyze_project: project_root is required (arg or self.project_root)")
        if not os.path.isdir(root):
            raise NotADirectoryError(f"analyze_project: not a directory: {root}")

        # 回写至实例，后续 trace_* 可直接用
        self.project_root = root

        # 确保调用图可用（如果不可用会抛出清晰错误）
        self._ensure_call_graph()

        project_result: Dict[str, Any] = {"files": {}, "variables": {}, "resources": []}
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.endswith((".c", ".cpp", ".cc", ".h", ".hpp", ".cxx")):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, root)
                file_res = self.analyze_file(path)
                project_result["files"][rel] = file_res

                for v, meta in file_res["variables"].items():
                    project_result["variables"].setdefault(v, []).append({"file": rel, **meta})

                project_result["resources"].extend(
                    [{"file": rel, **r} for r in file_res["resources"]]
                )

        # 可选：把调用图也附带回传，方便上层联调查看
        project_result["call_graph"] = self.call_graph
        return project_result

    # ---------------------------------------------------------
    def trace_variable_flow(self, var_name: str, max_depth: int = 5) -> List[List[str]]:
        """基于调用图追踪变量在函数间传播路径（占位/启发式）"""
        self._ensure_call_graph()

        # 邻接表（from -> [to]）
        adj: Dict[str, List[str]] = {}
        for e in self.call_graph.get("call_edges", []):
            adj.setdefault(e["from"], []).append(e["to"])

        results: List[List[str]] = []
        path: List[str] = []

        def dfs(node: str, depth: int):
            if depth > max_depth:
                return
            path.append(node)
            # 简单启发式：函数名包含变量名时认为相关
            if var_name in (node or ""):
                results.append(list(path))
            for nxt in adj.get(node, []):
                dfs(nxt, depth + 1)
            path.pop()

        for func_name in self.call_graph.get("functions", {}).keys():
            dfs(func_name, 0)

        return results

    # ---------------------------------------------------------
    def trace_resource_flow(self, resource_keyword: str = "malloc") -> List[Dict[str, Any]]:
        """基于调用图检查资源分配/释放路径（占位/启发式）"""
        self._ensure_call_graph()
        results: List[Dict[str, Any]] = []
        for e in self.call_graph.get("call_edges", []):
            if resource_keyword in (e.get("to") or ""):
                results.append(e)
        return results


# ---------- 快速测试 ----------
if __name__ == "__main__":
    import pprint
    # 你可以把这里改成真实项目路径
    proj = os.path.abspath("../../../sample_cpp")
    analyzer = DataflowAnalyzer(proj)
    try:
        dataflow = analyzer.analyze_project()
        pprint.pp(dataflow.get("resources", []))
        print("Var flow (example):", analyzer.trace_variable_flow("buf"))
    except Exception as e:
        print("Dataflow analyze failed:", e)
        print(traceback.format_exc())
