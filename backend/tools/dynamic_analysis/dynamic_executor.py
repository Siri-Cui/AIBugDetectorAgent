# -*- coding: utf-8 -*-
"""
动态执行器(完全重构版 - 修复交叉污染)
核心改动:
1. 按后缀分组可执行文件
2. 每个工具只执行对应后缀的文件
3. **添加去重逻辑,防止重复问题**
"""
import re  # 新增：用于鲁棒解析行号
import os
import asyncio
import subprocess
from typing import Dict, List, Any, Set, Tuple, Tuple, Optional 
import hashlib

from .valgrind_wrapper import ValgrindWrapper
from .sanitizer_wrapper import SanitizerWrapper
from utils.logger import log_info, log_error, log_warning
from backend.agents.ai_postprocessor import get_ai_postprocessor


class DynamicExecutor:
    """动态分析执行器"""

    def __init__(self):
        self.valgrind = ValgrindWrapper()
        self.sanitizer = SanitizerWrapper()
        self.default_timeout = 300

    async def execute_dynamic_analysis(
        self,
        project_path: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行完整的动态分析流程"""
        try:
            log_info("开始动态分析")

            # 提取配置
            tools: List[str] = config.get('tools', ['valgrind_memcheck'])
            executable_args: List[str] = config.get('executable_args', [])
            timeout: int = config.get('timeout', self.default_timeout)
            output_dir: str = config.get('output_dir', '/tmp/dynamic_analysis')

            # 创建输出目录
            os.makedirs(output_dir, exist_ok=True)




            # ===== 步骤1: 获取可执行文件（优先使用传入的映射）=====
            executables_map_param = config.get('executables_map')

            if executables_map_param:
                # 🔥 使用传入的映射（来自 workflow）
                log_info(f"✅ 使用传入的可执行文件映射（{len(executables_map_param)} 个工具）")
                
                all_executables = []
                for tool_name, exe_list in executables_map_param.items():
                    for exe in exe_list:
                        if os.path.exists(exe) and os.path.isfile(exe):
                            all_executables.append(exe)
                            log_info(f"   📍 {tool_name}: {exe}")
                        else:
                            log_warning(f"   ⚠️  {tool_name} 的文件不存在: {exe}")
                
                if not all_executables:
                    return {
                        'success': False,
                        'error': '传入的可执行文件映射为空或文件均不存在'
                    }
                
                log_info(f"✅ 共 {len(all_executables)} 个有效可执行文件")
            if executables_map_param:
                log_info(f"✅ 使用传入的可执行文件映射（{len(executables_map_param)} 个工具）")
                    
                all_executables = []
                failed_count = 0
                for tool_name, exe_list in executables_map_param.items():
                    for exe in exe_list:
                        if os.path.exists(exe) and os.path.isfile(exe):
                            all_executables.append(exe)
                            log_info(f"   📍 {tool_name}: {exe}")
                        else:
                            failed_count += 1
                            log_warning(f"   ⚠️  {tool_name} 的文件不存在: {exe}")
                    
                    # ===== 🔥 关键修改：只有在完全没有可执行文件时才失败 =====
                if not all_executables:
                    log_error(f"❌ 所有可执行文件均不存在（失败 {failed_count} 个）")
                    return {
                        'success': False,
                        'error': '传入的可执行文件映射为空或文件均不存在',
                        'issues': [],  # ← 返回空问题列表而不是完全失败
                        'summary': {
                            'total_issues': 0,
                            'tools_run': 0,
                            'compilation_failed': True
                        }
                    }
                    
                    # ===== 部分成功继续执行 =====
                log_info(f"✅ 共 {len(all_executables)} 个有效可执行文件（失败 {failed_count} 个）")


            # ===== 步骤2: 按后缀分组可执行文件 =====
            executables_by_tool = self._group_executables_by_suffix(all_executables)
            
            log_info("📦 按工具分组的可执行文件:")
            for tool, execs in executables_by_tool.items():
                if execs:
                    log_info(f"   {tool}: {len(execs)} 个文件")
                    for exe in execs[:3]:
                        log_info(f"      - {os.path.basename(exe)}")
                    if len(execs) > 3:
                        log_info(f"      ... 还有 {len(execs)-3} 个文件")

            # ===== 步骤3: 线程检测 =====
            has_threads = self._detect_threading(project_path)
            if has_threads:
                log_info("✅ 检测到多线程代码")
                if 'tsan' not in tools and executables_by_tool.get('tsan'):
                    log_info("🔧 自动启用 ThreadSanitizer (TSan)")
                    tools.append('tsan')

            # ===== 步骤4: 并行执行所有工具 =====
            all_results: List[Dict[str, Any]] = []
            all_issues: List[Dict[str, Any]] = []

            tasks = []
            log_info(f"📋 计划执行的工具: {', '.join(tools)}")

            for tool in tools:
                tool_execs = executables_by_tool.get(tool, [])
                
                if not tool_execs:
                    log_warning(f"   ⚠️ 工具 {tool} 没有对应的可执行文件,跳过")
                    continue
                
                log_info(f"   🔧 工具 {tool} 将分析 {len(tool_execs)} 个可执行文件")
                
                for exe in tool_execs:
                    # 互斥检查
                    if tool == 'tsan' and self._is_asan_binary(exe):
                        log_warning(f"   ⚠️ 跳过 ASan 二进制: {os.path.basename(exe)}")
                        continue
                    if tool == 'asan' and self._is_tsan_binary(exe):
                        log_warning(f"   ⚠️ 跳过 TSan 二进制: {os.path.basename(exe)}")
                        continue
                    
                    # 创建任务
                    if tool == 'valgrind_memcheck':
                        tasks.append(self._run_with_metadata(
                            self.valgrind.run_memcheck(exe, executable_args, timeout, output_dir),
                            tool, exe
                        ))
                    elif tool == 'asan':
                        tasks.append(self._run_with_metadata(
                            self.sanitizer.run_asan(exe, executable_args, timeout, output_dir),
                            tool, exe
                        ))
                    elif tool == 'tsan':
                        tasks.append(self._run_with_metadata(
                            self.sanitizer.run_tsan(exe, executable_args, timeout),
                            tool, exe
                        ))
                    elif tool == 'ubsan':
                        tasks.append(self._run_with_metadata(
                            self.sanitizer.run_ubsan(exe, executable_args, timeout),
                            tool, exe
                        ))

            log_info(f"🚀 开始并行执行 {len(tasks)} 个分析任务...")

            # 等待所有任务完成
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                log_info("=" * 60)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        log_error(f"❌ 任务 #{i+1} 执行异常: {result}")
                        continue

                    tool_name = result.get('tool', 'unknown')
                    exe_name = os.path.basename(result.get('executable', 'unknown'))
                    
                    if result.get('success'):
                        issue_count = len(result.get('issues', []))
                        if issue_count > 0:
                            log_info(f"✅ {tool_name} [{exe_name}]: 发现 {issue_count} 个问题")
                    else:
                        error_msg = result.get('error', '')
                        if '可执行文件不存在' not in error_msg:
                            log_error(f"❌ {tool_name} [{exe_name}]: {error_msg}")

                    all_results.append(result)
                    
                    # 标记来源
                    if result.get('success') and 'issues' in result:
                        for issue in result['issues']:
                            issue['source_executable'] = result.get('executable')
                            issue['source_tool'] = issue.get('tool', tool_name)
                            all_issues.append(issue)
                
                log_info("=" * 60)

            # ===== 🔥 步骤5: 智能去重 =====
            log_info("🧹 开始去重...")
            original_count = len(all_issues)
            deduplicated_issues = self._deduplicate_issues(all_issues)
            removed_count = original_count - len(deduplicated_issues)
            
            if removed_count > 0:
                log_info(f"✅ 去重完成: 移除 {removed_count} 个重复问题 ({original_count} -> {len(deduplicated_issues)})")
            else:
                log_info(f"✅ 无重复问题")

            # 🆕🆕🆕 ===== 步骤6: AI智能后处理 =====
            enable_ai = config.get('enable_ai_postprocess', True)
            if enable_ai and deduplicated_issues:
                log_info("=" * 60)
                log_info("🤖 步骤6/6: AI智能后处理(去重+分析+修复建议)")
                log_info("=" * 60)
                
                try:
                    # 构造临时结果用于AI分析
                    temp_results = {
                        'issues': deduplicated_issues,
                        'summary': {
                            'total_issues': len(deduplicated_issues),
                            'analysis_tools': tools
                        }
                    }
                    
                    # 调用AI后处理器
                    ai_processor = get_ai_postprocessor()
                    ai_processed = await ai_processor.process_detection_results(
                        raw_results=temp_results,
                        project_path=project_path
                    )
                    
                    # 更新issues(使用AI处理后的)
                    deduplicated_issues = ai_processed.get('issues', deduplicated_issues)
                    
                    # 添加AI分析结果
                    ai_classification = ai_processed.get('ai_classification', {})
                    repair_suggestions = ai_processed.get('repair_suggestions', [])
                    
                    log_info(f"✅ AI处理完成: {len(deduplicated_issues)} 个最终问题")
                    log_info(f"   - 真实漏洞: {len(ai_classification.get('real_vulnerabilities', []))}")
                    log_info(f"   - 修复建议: {len(repair_suggestions)}")
                    
                except Exception as e:
                    log_error(f"AI后处理失败(已降级): {e}")
                    # 降级:继续使用去重后的结果
                    ai_classification = {}
                    repair_suggestions = []
            else:
                log_info("⏭️  跳过AI后处理")
                ai_classification = {}
                repair_suggestions = []

            if not deduplicated_issues:
                log_warning("⚠️  动态分析未发现任何问题（可能所有文件编译失败）")
                return {
                    'success': True,  # ← 关键：即使没问题也返回成功
                    'tools_executed': tools,
                    'total_issues': 0,
                    'issues': [],
                    'tool_results': all_results,
                    'summary': {
                        'tools_run': len(tools),
                        'tools_succeeded': 0,
                        'tools_failed': len(tools),
                        'total_issues': 0,
                        'compilation_failed': True,  # ← 标记编译失败
                        'message': '所有可执行文件编译失败或未生成问题'
                    },
                    'output_dir': output_dir,
                    'ai_classification': {},
                    'repair_suggestions': []
                }
                
            # 统计结果
            summary = self._generate_summary(all_results, deduplicated_issues)
            
            # 🆕 添加AI分析统计
            summary['ai_processed'] = enable_ai and bool(deduplicated_issues)
            summary['repairs_generated'] = len(repair_suggestions)
            
            log_info(f"动态分析完成,共发现 {len(deduplicated_issues)} 个独立问题")

            return {
                'success': True,
                'tools_executed': tools,
                'total_issues': len(deduplicated_issues),
                'issues': deduplicated_issues,
                'tool_results': all_results,
                'summary': summary,
                'output_dir': output_dir,
                # 🆕 添加AI分析结果
                'ai_classification': ai_classification,
                'repair_suggestions': repair_suggestions
            }

        except Exception as e:
            log_error(f"动态分析执行失败: {e}")
            import traceback
            log_error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            }


    # ===== 🔥 新增: 智能去重方法 =====

    def _extract_user_location(self, issue: Dict[str, Any]) -> Tuple[Optional[str], int]:
        """
        终极位置提取：优先 stack_trace → location → file
        返回 (basename, line) ，line=0 表示未知
        """
        # ===== 优先级1: stack_trace（最可靠，所有工具都有）=====
        stack = issue.get('stack_trace', [])
        for frame in stack:
            frame_file = frame.get('file', '').strip()
            if not frame_file:
                continue
            # 用户代码判断（严格过滤系统帧）
            if frame_file.endswith(('.cpp', '.c', '.cc', '.cxx', '.h', '.hpp')):
                if any(bad in frame_file for bad in [
                    '/usr/', '/lib/', 'sanitizer_', 'tsan_', 'asan_', 'interceptors',
                    'string_fortified', 'libc_start', 'sysdeps'
                ]):
                    continue
                basename = os.path.basename(frame_file)
                line = frame.get('line', 0)
                if line > 0:
                    log_info(f"   🎯 stack提取: {basename}:{line}")
                    return basename, line
        
        # ===== 优先级2: location 字段（正则解析，超鲁棒）=====
        location = issue.get('location', '').strip()
        if location:
            # 匹配最后面的 :数字（支持 file.cpp:123 或 file.cpp:123:1）
            match = re.search(r':(\d+)(?::\d+)?\s*$', location)
            if match:
                line_num = int(match.group(1))
                # 取路径最后一部分作为basename
                file_part = location.rsplit(':', 1)[0].strip()
                basename = os.path.basename(file_part)
                if basename.endswith(('.cpp', '.c', '.cc', '.cxx', '.h', '.hpp')):
                    log_info(f"   🎯 location提取: {basename}:{line_num}")
                    return basename, line_num
        
        # ===== 优先级3: 顶层 file + line =====
        file_field = issue.get('file', '').strip()
        if file_field:
            line = issue.get('line', 0)
            if isinstance(line, (int, float)) and line > 0:
                basename = os.path.basename(file_field)
                if basename.endswith(('.cpp', '.c', '.cc', '.cxx', '.h', '.hpp')):
                    log_info(f"   🎯 file字段提取: {basename}:{line}")
                    return basename, line
        
        log_warning(f"   ⚠️ 完全失败: {issue.get('type')} @ {location or 'unknown'}")
        return None, 0


    def _deduplicate_issues(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """智能去重终极版"""
        seen: Dict[str, Dict[str, Any]] = {}
        data_race_count: Dict[str, int] = {}  # data-race 特殊：同位置最多保留2个
        
        for issue in issues:
            user_file, user_line = self._extract_user_location(issue)
            if not user_file:
                continue  # 彻底系统帧，丢弃
            
            issue_type = self._normalize_issue_type(issue.get('type', 'unknown'))
            
            # ===== 生成key =====
            if user_line > 0:
                key = f"{user_file}:{user_line}:{issue_type}"
            else:
                key = f"{user_file}::{issue_type}"
            
            # ===== data-race 特殊宽容 =====
            if issue_type == 'data_race':
                if key not in data_race_count:
                    data_race_count[key] = 0
                if data_race_count[key] >= 2:
                    log_info(f"   ⏭️ data-race 超限跳过: {key}")
                    continue
                data_race_count[key] += 1
            
            # ===== 去重核心 =====
            new_score = self._calculate_issue_score(issue)
            if key not in seen:
                seen[key] = issue
                log_info(f"   ✅ 新问题: {key} (得分 {new_score})")
            else:
                old_score = self._calculate_issue_score(seen[key])
                if new_score > old_score:
                    log_info(f"   🔄 更新: {key} (得分 {new_score} > {old_score})")
                    seen[key] = issue
                else:
                    log_info(f"   ⏭️ 跳过重复: {key} (得分 {new_score} <= {old_score})")
                
                # 可选：合并 detected_in 列表
                if 'detected_in' not in seen[key]:
                    seen[key]['detected_in'] = []
                seen[key]['detected_in'].append(issue.get('source_executable', 'unknown'))
        
        log_info(f"🎯 去重完成: {len(issues)} → {len(seen)} 个独立问题")
        return list(seen.values())

    def _normalize_issue_type(self, raw_type: str) -> str:
        """规范化问题类型名称"""
        if not raw_type:
            return 'unknown'
        
        type_map = {
            'heap-use-after-free': 'use_after_free',
            'heap-buffer-overflow': 'heap_overflow',
            'stack-buffer-overflow': 'stack_overflow',
            'data race': 'data_race',
            'data-race': 'data_race',
            'memory leak': 'memory_leak',
            'double-free': 'double_free',
        }
        
        normalized = raw_type.lower().replace(' ', '_')
        return type_map.get(normalized, normalized)

    def _calculate_issue_score(self, issue: Dict[str, Any]) -> int:
        """计算问题的信息完整度得分（用于去重时选择更完整的记录）"""
        score = 0
        
        # 有完整堆栈 +10
        if issue.get('stack_trace') and len(issue.get('stack_trace', [])) > 0:
            score += 10
        
        # 有详细描述 +5
        if issue.get('message') and len(issue.get('message', '')) > 20:
            score += 5
        
        # 有源码上下文 +5
        if issue.get('source_code'):
            score += 5
        
        # 有建议 +3
        if issue.get('suggestion'):
            score += 3
        
        return score

    def _issue_fingerprint(self, issue: Dict[str, Any]) -> str:
        """
        生成问题指纹(用于精确去重)
        包括: 类型+文件+行号+消息摘要
        """
        components = [
            issue.get('type', ''),
            issue.get('file', ''),
            str(issue.get('line', 0)),
            issue.get('message', '')[:100]  # 只取前100字符
        ]
        
        fingerprint_str = '|'.join(components)
        return hashlib.md5(fingerprint_str.encode()).hexdigest()

    # ===== 其他方法保持不变 =====
    
    def _discover_executables(self, project_path: str) -> List[str]:
        """扫描目录,查找所有可执行文件"""
        executables = []
        
        try:
            for fname in os.listdir(project_path):
                fpath = os.path.join(project_path, fname)
                
                if not os.path.isfile(fpath):
                    continue
                if not os.access(fpath, os.X_OK):
                    continue
                
                # 排除脚本和库文件
                if fname.endswith(('.so', '.a', '.dylib', '.py', '.sh', '.o', '.txt', '.md')):
                    continue
                
                if fname.startswith('.'):
                    continue
                
                executables.append(os.path.abspath(fpath))
                
        except Exception as e:
            log_error(f"扫描可执行文件失败: {e}")
        
        return executables

    def _group_executables_by_suffix(self, executables: List[str]) -> Dict[str, List[str]]:
        """按后缀分组可执行文件"""
        groups = {
            'valgrind_memcheck': [],
            'asan': [],
            'tsan': [],
            'ubsan': []
        }
        
        fallback_candidates = []
        
        for exe in executables:
            name = os.path.basename(exe)
            
            if name.endswith('_vg') or '_vg_' in name or 'valgrind' in name:
                groups['valgrind_memcheck'].append(exe)
            elif name.endswith('_asan') or '_asan_' in name:
                groups['asan'].append(exe)
            elif name.endswith('_tsan') or '_tsan_' in name:
                groups['tsan'].append(exe)
            elif name.endswith('_ubsan') or '_ubsan_' in name:
                groups['ubsan'].append(exe)
            else:
                fallback_candidates.append(exe)
        
        # 候选文件分配
        for tool in ['valgrind_memcheck', 'asan']:
            if not groups[tool] and fallback_candidates:
                candidate = fallback_candidates[0]
                if tool == 'asan' and not self._is_tsan_binary(candidate):
                    groups[tool].append(candidate)
                elif tool == 'valgrind_memcheck' and not self._is_asan_binary(candidate):
                    groups[tool].append(candidate)
        
        return groups

    async def _run_with_metadata(
        self,
        task_coro,
        tool_name: str,
        executable_path: str
    ) -> Dict[str, Any]:
        """包装任务,添加元数据"""
        try:
            result = await task_coro
            result['tool'] = tool_name
            result['executable'] = executable_path
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'tool': tool_name,
                'executable': executable_path
            }

    def _generate_summary(
        self,
        tool_results: List[Dict[str, Any]],
        all_issues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """生成动态分析摘要"""
        summary: Dict[str, Any] = {
            'tools_run': len(tool_results),
            'tools_succeeded': sum(1 for r in tool_results if r.get('success')),
            'tools_failed': sum(1 for r in tool_results if not r.get('success')),
            'total_issues': len(all_issues),
            'issues_by_severity': {},
            'issues_by_category': {},
            'issues_by_tool': {}
        }

        for issue in all_issues:
            severity = issue.get('severity', 'unknown')
            summary['issues_by_severity'][severity] = \
                summary['issues_by_severity'].get(severity, 0) + 1

        for issue in all_issues:
            category = issue.get('category', 'unknown')
            summary['issues_by_category'][category] = \
                summary['issues_by_category'].get(category, 0) + 1

        for issue in all_issues:
            tool = issue.get('source_tool', 'unknown')
            summary['issues_by_tool'][tool] = \
                summary['issues_by_tool'].get(tool, 0) + 1

        return summary

    def _detect_threading(self, project_path: str) -> bool:
        """检测项目是否使用多线程"""
        threading_keywords = [
            '#include <pthread.h>',
            'pthread_create',
            '#include <thread>',
            'std::thread',
            '#pragma omp'
        ]

        try:
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['build']]

                for file in files:
                    if file.endswith(('.cpp', '.cc', '.c', '.h', '.hpp')):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                for keyword in threading_keywords:
                                    if keyword in content:
                                        return True
                        except:
                            continue
            return False
        except:
            return False

    def _is_asan_binary(self, exe: str) -> bool:
        """检测二进制是否包含 ASan"""
        try:
            out = subprocess.run(["ldd", exe], capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and "libasan" in out.stdout:
                return True
        except:
            pass
        try:
            with open(exe, "rb") as f:
                blob = f.read(200000)
            return b"libasan" in blob
        except:
            return False

    def _is_tsan_binary(self, exe: str) -> bool:
        """检测二进制是否包含 TSan"""
        try:
            out = subprocess.run(["ldd", exe], capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and "libtsan" in out.stdout:
                return True
        except:
            pass
        try:
            with open(exe, "rb") as f:
                blob = f.read(200000)
            return b"libtsan" in blob
        except:
            return False

    # 兼容旧接口
    async def find_test_executables(self, project_path: str) -> List[str]:
        """查找测试可执行文件"""
        return self._discover_executables(project_path)

    async def run_single_tool(
        self,
        tool_name: str,
        executable_path: str,
        args: List[str] = None,
        timeout: int = None,
        output_dir: str = None
    ) -> Dict[str, Any]:
        """运行单个工具"""
        timeout = timeout or self.default_timeout
        output_dir = output_dir or '/tmp'

        tool_mapping = {
            'valgrind_memcheck': self.valgrind.run_memcheck,
            'asan': self.sanitizer.run_asan,
            'ubsan': self.sanitizer.run_ubsan,
            'tsan': self.sanitizer.run_tsan
        }

        tool_func = tool_mapping.get(tool_name)
        if not tool_func:
            return {'success': False, 'error': f'未知的工具: {tool_name}'}

        try:
            if tool_name.startswith('valgrind') or tool_name == 'asan':
                result = await tool_func(executable_path, args, timeout, output_dir)
            else:
                result = await tool_func(executable_path, args, timeout)
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}
