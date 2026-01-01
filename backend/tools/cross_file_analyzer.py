# -*- coding: utf-8 -*-
"""Cross-file analyzer based on call_graph.json"""
import json, os
from typing import List, Dict, Any

def load_call_graph(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def trace_call_chain(call_graph: Dict[str, Any], start: str, target: str, max_depth: int = 6) -> List[List[str]]:
    """在调用图中查找从 start 到 target 的调用链"""
    edges = call_graph.get('call_edges', [])
    adj = {}
    for e in edges:
        adj.setdefault(e['from'], []).append(e['to'])
    results = []
    path = [start]

    def dfs(node, depth):
        if depth > max_depth:
            return
        if node == target:
            results.append(list(path))
            return
        for nxt in adj.get(node, []):
            if nxt in path:
                continue
            path.append(nxt)
            dfs(nxt, depth + 1)
            path.pop()

    dfs(start, 0)
    return results

def find_functions_by_name(call_graph: Dict[str, Any], name: str) -> List[str]:
    """查找指定函数名在项目中的所有定义位置"""
    funcs = call_graph.get('functions', {})
    matches = []
    for fname, locs in funcs.items():
        if fname == name:
            for loc in locs:
                matches.append(f"{loc.get('file')}:{loc.get('line')}")
    return matches