from typing import Dict, Any, List, Optional, Set
import os, re, json
from utils.logger import log_info, log_error

# PatternLibrary 可选依赖
try:
    from tools.pattern_library import PatternLibrary
except Exception:
    PatternLibrary = None


class FalsePositiveFilter:
    """
    误报过滤器（迭代6达标版）
    功能：
      - 过滤低价值/测试噪声告警
      - 降级中危可解释项
      - 标注可疑误报（供人工复核）
    """

    _re_test_dir = re.compile(r"(?:^|/)(tests?|test|unittests?)(?:/|$)", re.I)
    _re_magic = re.compile(r"[-+]?\d*\.?\d+") 

    def __init__(self):
        self.plib = PatternLibrary() if PatternLibrary else None
        # ⭐⭐⭐ （可选但推荐）确保 plib 加载日志 ⭐⭐⭐
        if self.plib:
             log_info("[FalsePositiveFilter] PatternLibrary 初始化成功。")
        else:
             log_info("[FalsePositiveFilter] PatternLibrary 未加载（可选依赖）。")

    def apply(
        self, issues: List[Dict[str, Any]], context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        应用所有过滤规则。
        A. 强制过滤（基于工具、文件名、特定规则）
        B. 降级与普通过滤（基于类型、上下文）
        C. 强制过滤（基于最终严重性）
        """
        cfg = self._safe_plib_rules()
        # ⭐⭐⭐ 添加日志，确认 cfg 加载情况 ⭐⭐⭐
        log_info(f"[FalsePositiveFilter] apply - 从 _safe_plib_rules 加载的 cfg: {cfg}") # 看看加载了什么
        
        common_magic: Set[str] = set(map(str, cfg.get("magic_numbers", [])))
        # ⭐⭐⭐ 添加日志，确认 common_magic ⭐⭐⭐
        log_info(f"[FalsePositiveFilter] apply - common_magic 集合: {common_magic}")
        project_features: Set[str] = set((context.get("project_features") or []))
        callgraph = self._maybe_load_callgraph(context)
        reachable = self._build_reachable(callgraph) or set()

        out: List[Dict[str, Any]] = []
        for it in issues:
            sev = (it.get("severity") or "medium").lower()
            msg = (
                str(it.get("message") or "")
                + " "
                + str((it.get("type") or ""))
                + " "
                + str((it.get("category") or ""))
            ).lower()
            fpath = it.get("file")
            fname = os.path.basename(fpath or "")
            cat = (it.get("category") or "").lower()
            tool = (it.get("tool") or "").lower()

            # === A. 强制过滤（高置信度误报） ===
            # 1) cppcheck 配置噪声
            if cat == "missingincludesystem":
                log_info(f"过滤 missingIncludeSystem: {fpath}:{it.get('line')}")
                continue

            # 2) 测试/基准识别
            is_test_dir = bool(self._re_test_dir.search(fpath or ""))
            is_bench_or_ut = fname in ("Benchmark.cpp", "UnitTest.cpp")

            # 3) 自定义规则：printf/魔法数字 → 过滤
            if tool == "custom_rules" and (is_bench_or_ut or is_test_dir):
                if "魔法数字" in msg:
                    log_info(
                        f"过滤 自定义-魔法数字(基准/单测)：{fpath}:{it.get('line')}"
                    )
                    continue
                if "printf" in msg:
                    log_info(
                        f"过滤 自定义-printf(基准/单测)：{fpath}:{it.get('line')}"
                    )
                    continue

            # 4) 基准/单测中的低价值告警
            if is_bench_or_ut or is_test_dir:
                if cat in ("unusedfunction", "invalidprintfargtype_uint"):
                    log_info(
                        f"过滤 基准/单测低价值：{cat} {fpath}:{it.get('line')}"
                    )
                    continue

            # === B. 降级与普通过滤 ===
            # 5) 内存池项目：自定义规则中的魔法数字，如果不在测试文件，且数字常见 -> 过滤
            if (
                tool == "custom_rules"
                and "魔法数字" in msg
                and not (is_bench_or_ut or is_test_dir)
            ):
                # ⭐⭐⭐ 确认这里的 self._re_magic 现在已定义 ⭐⭐⭐
                magic_num_found = self._re_magic.search(it.get("message") or "")
                if magic_num_found:
                     num_str = magic_num_found.group(0) # 获取匹配到的数字字符串
                     log_info(f"  - B5 检查: 找到魔法数字 '{num_str}' in message for issue {it.get('id', 'N/A')}")
                     # ⭐⭐⭐ 修正: group(1) -> group(0) ⭐⭐⭐
                     # ⭐⭐⭐ 并且要确保 common_magic 包含的是字符串形式 ⭐⭐⭐
                     if num_str in common_magic: 
                          log_info(f"过滤 常见魔法数字: {num_str} at {fpath}:{it.get('line')}")
                          continue
                     else:
                          log_info(f"  - B5 检查: 数字 '{num_str}' 不在 common_magic 集合 {common_magic} 中。")
                else:
                     log_info(f"  - B5 检查: 未在消息中匹配到数字 for issue {it.get('id', 'N/A')}: {it.get('message')}")


            # 6) 内存池项目：printf，如果不在测试文件 -> 降级
            if (
                tool == "custom_rules"
                and "printf" in msg
                and not (is_bench_or_ut or is_test_dir)
            ):
                it["severity"] = "low"
                sev = "low"  # 更新本地变量

            # 7) 内存池项目：C-Style Cast
            if cat == "cstylecast":
                if "memory_pool" in project_features:
                    # 内存池项目里 C-Style Cast 很常见，降级
                    it["severity"] = "low"
                    sev = "low"
                else:
                    # 其他项目里，它可能是中风险
                    it["severity"] = "medium"
                    sev = "medium"

            # 8) 内存池项目： unreadVariable 降级
            if cat == "unreadvariable":
                it["severity"] = "low"
                sev = "low"

            # 9) 未使用函数
            if cat == "unusedfunction":
                # 如果函数不在可达路径上，过滤
                func_name = it.get("message", "").split("'")[1]
                if func_name and func_name not in reachable:
                    log_info(
                        f"过滤 不可达 UnusedFunction: {func_name} {fpath}:{it.get('line')}"
                    )
                    continue
                else:
                    it["severity"] = "low"  # 如果可达，降级
                    sev = "low"

            # 10) 严重度修正 (针对 memory_pool 特化规则)
            if tool == "memory_pool_specialized":
                it["severity"] = "high"  # 专项规则都是高危
                sev = "high"

            # 11) 一般降级项
            if cat in (
                "implicitructor",  # 你提供的原始数据中有这个
                "shadowvariable",
                "shadowargument",
                "constvariable",
            ):
                it["severity"] = "low"
                sev = "low"

            # 12) 可疑误报标记
            if self._is_suspected_fp(msg):  # ⭐ 删除第二个参数
                it.setdefault("tags", []).append("need_human_review")

            out.append(it)
        
        # ⭐⭐ 关键修复点 ⭐⭐
        # 必须在 for 循环 *结束* 之后，再执行 C 阶段的过滤
        
        # ⭐⭐ 1. 在 C 阶段前打印 out 列表的大小和内容样本 ⭐⭐
        log_info(f"[FalsePositiveFilter] 即将进入 C 阶段过滤，当前 out 列表包含 {len(out)} 个 issues。")
        # 打印前 5 个 issue 的 severity 看看
        if out:
             log_info(f"  - 前 5 个 issue 的 severity: {[item.get('severity', 'N/A') for item in out[:5]]}")

        # === C. 迭代6：强制过滤低严重度问题 ===
        high_priority_filtered: List[Dict[str, Any]] = []
        low_severity_count = 0
        medium_severity_count = 0 # ⭐⭐ 新增计数 ⭐⭐
        high_severity_count = 0   # ⭐⭐ 新增计数 ⭐⭐
        critical_severity_count = 0 # ⭐⭐ 新增计数 ⭐⭐
        other_severity_count = 0 # ⭐⭐ 新增计数 ⭐⭐        
        
        # ⭐⭐ 2. 在循环内部打印每个 issue 的严重性判断 ⭐⭐
        for issue in out:
            current_sev = (issue.get('severity') or 'medium').lower()  # ← 默认改为 medium
            cat = (issue.get('category') or '').lower()
            tool = (issue.get('tool') or '').lower()
            
            log_info(f"  - C阶段检查 Issue {issue.get('id', 'N/A')}: severity='{current_sev}', category='{cat}'")
            
            # ✅ 白名单：高价值类别直接保留
            high_value_categories = {
                'memoryleak', 'memleak', 'doublefree', 'use-after-free',
                'buffer-overflow', 'nullpointer', 'null-pointer-dereference',
                'data-race', 'deadlock', 'resource-leak'
            }
            
            if any(hv in cat for hv in high_value_categories):
                high_priority_filtered.append(issue)
                log_info(f"    ✅ 白名单保留（高价值类别）: {cat}")
                continue

            if current_sev == 'critical':
                 high_priority_filtered.append(issue)
                 critical_severity_count += 1
            elif current_sev == 'high':
                 high_priority_filtered.append(issue)
                 high_severity_count += 1
            elif current_sev == 'medium':
                 high_priority_filtered.append(issue)
                 medium_severity_count += 1
            elif current_sev == 'low':
                # ✅ 修复：只过滤纯格式化问题
                low_value_patterns = [
                    'unusedfunction', 'unreadvariable', 'constvariable',
                    'shadowvariable', 'cstylecast', 'invalidprintfargtype'
                ]
                
                if cat in low_value_patterns:
                    low_severity_count += 1
                    log_info(f"    ⏭️ 过滤低价值 low: {cat}")
                else:
                    # 保留其他 low 问题（可能是误判）
                    high_priority_filtered.append(issue)
                    log_info(f"    ✅ 保留非噪声 low: {cat}")
            else: # 处理未知的 severity 值
                 log_error(f"  - C 阶段发现未知 severity: '{current_sev}' for Issue {issue.get('id', 'N/A')}")
                 other_severity_count += 1
                 high_priority_filtered.append(issue) 


        # ⭐⭐ 3. 输出更详细的过滤统计 ⭐⭐
        total_processed_c = (low_severity_count + medium_severity_count + 
                            high_severity_count + critical_severity_count + other_severity_count)

        log_info(
            f"[FalsePositiveFilter] C阶段完成: 输入 {len(out)}, "
            f"保留 C({critical_severity_count}) H({high_severity_count}) M({medium_severity_count}), "
            f"过滤 L({low_severity_count}), 输出 {len(high_priority_filtered)}"
        )
        
        return high_priority_filtered  # ⭐ 现在返回的是完整过滤后的列表


    # === 辅助函数 ===
    def _safe_plib_rules(self) -> Dict[str, Any]:
        if not self.plib:
            return {"magic_numbers": []}
        try:
            return self.plib.get_rules() or {"magic_numbers": []}
        except Exception as e:
            log_error(f"PatternLibrary 失败: {e}")
            return {"magic_numbers": []}

    def _is_assert_or_debug(self, text: str) -> bool:
        t = text.lower()
        return "assert" in t or "debug" in t or "#ifdef debug" in t

    def _has_null_guard_hint(self, text: str) -> bool:
        t = text.lower()
        hints = [
            "null check",
            "nullptr check",
            "if (ptr",
            "if(ptr",
            "!= nullptr",
            "!= null",
            "!= NULL",
        ]
        return any(h in t for h in hints)

    def _maybe_load_callgraph(self, context: Dict[str, Any]):
        cg = (context or {}).get("call_graph") or {}
        path = cg.get("path")
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error(f"加载调用图失败: {e}")
            return None

    def _build_reachable(self, callgraph) -> Optional[Set[str]]:
        if not callgraph:
            log_info("[FalsePositiveFilter] _build_reachable - callgraph 为空, 返回 None")
            return None
        edges = callgraph.get("call_edges", [])
        reach: Set[str] = set()
        for e in edges:
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                reach.update(e[:2])
            elif isinstance(e, dict) and "src" in e and "dst" in e:
                reach.add(e["src"])
                reach.add(e["dst"])
        log_info(f"[FalsePositiveFilter] _build_reachable - 构建了包含 {len(reach)} 个函数的可达集合")
        return reach or None

    def _downgrade(self, sev: Optional[str]) -> str:
        order = ["info", "low", "medium", "high", "critical"]
        s = (sev or "medium").lower()
        return order[max(0, order.index(s) - 1)] if s in order else "medium"

    def _is_common_fp(self, msg: str) -> bool:
        try:
            return bool(self.plib and self.plib.is_common_fp(msg))
        except Exception:
            return False

    def _is_suspected_fp(self, msg: str) -> bool:
        try:
            return bool(self.plib and self.plib.is_suspected_fp(msg))
        except Exception:
            return False
