# -*- coding: utf-8 -*-
"""
动态分析工作流
作用:定义并执行动态分析的完整流程
依赖:tools.compiler_tools、tools.dynamic_analysis、utils.logger
调用关系:被orchestrator或API调用
"""
import os
import asyncio
import subprocess
import shutil
from typing import Dict, List, Any, Optional
from tools.compiler_tools.build_detector import BuildDetector
from tools.compiler_tools.instrumented_builder import InstrumentedBuilder
from tools.dynamic_analysis.dynamic_executor import DynamicExecutor
from tools.dynamic_analysis.result_correlator import ResultCorrelator
from utils.logger import log_info, log_error, log_warning


class DynamicWorkflow:
    """动态分析工作流"""

    def __init__(self):
        self.build_detector = BuildDetector()
        self.instrumented_builder = InstrumentedBuilder()
        self.dynamic_executor = DynamicExecutor()
        self.result_correlator = ResultCorrelator()

    async def run_dynamic_analysis_workflow(
        self,
        project_id: str,
        project_path: str,
        config: Dict[str, Any],
        static_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """运行完整的动态分析工作流"""
        try:
            log_info("=" * 70)
            log_info(f"🚀 开始动态分析工作流")
            log_info(f"   项目ID: {project_id}")
            log_info(f"   项目路径: {project_path}")
            log_info(f"   配置: {config}")
            log_info("=" * 70)

            workflow_result = {
                'project_id': project_id,
                'success': True,
                'steps': {}
            }

            # 步骤1: 检测构建系统
            log_info("📦 步骤1/5: 检测构建系统")
            build_info = self.build_detector.detect_build_system(project_path)
            workflow_result['steps']['build_detection'] = build_info
            log_info(f"   构建系统: {build_info.get('build_system', '未检测到')}")

            if not build_info.get('build_system'):
                log_warning("⚠️  未检测到构建系统")
                return {
                    'success': False,
                    'error': '未找到构建系统',
                    'steps': workflow_result['steps']
                }

            # 步骤1.5: 多线程检测
            log_info("🔍 步骤1.5/5: 检测项目特征")
            has_threads = self.dynamic_executor._detect_threading(project_path)
            workflow_result['steps']['threading_detection'] = {
                'has_threads': has_threads
            }
            
            if has_threads:
                log_info("   ✅ 检测到多线程代码（pthread/std::thread）")
            else:
                log_info("   ℹ️  未检测到明显的多线程特征")

            # 步骤2：智能编译策略
            log_info("🔧 步骤2/5: 智能编译策略")
            
            # 🆕 提前初始化所有变量
            tools: List[str] = config.get('tools', ['valgrind_memcheck', 'asan'])
            executables_map: Dict[str, List[str]] = {}
            btop_native_mode = False
            build_dir = config.get('build_dir')
            clean_build = config.get('clean_build', True)
            
            # 初始化工具分类变量(避免btop模式下未定义)
            valgrind_tools: List[str] = []
            sanitizer_tools: List[str] = []
            
            # 🔥 修复：使用 build_info 中检测到的实际项目目录
            actual_project_root = build_info.get('project_root', project_path)
            project_name = os.path.basename(actual_project_root).lower()
            
            log_info(f"   检测到项目名称: {project_name}")
            
            # 🆕 检测btop特殊处理
            if project_name == 'btop':
                log_info("⚡ 检测到btop项目,尝试使用原生Makefile编译...")
                
                # 使用实际的btop目录
                btop_project_path = actual_project_root
                
                try:
                    # 清理
                    subprocess.run(
                        ['make', 'clean'], 
                        cwd=btop_project_path,
                        capture_output=True, 
                        timeout=60,
                        check=False
                    )
                    
                    # 编译(不带sanitizer)
                    make_result = subprocess.run(
                        ['make', '-j4'],
                        cwd=btop_project_path,
                        capture_output=True,
                        timeout=1800
                    )
                    
                    if make_result.returncode == 0:
                        log_info("✅ btop原生编译成功,寻找产物...")
                        
                        # 查找可能的可执行文件位置
                        possible_bins = [
                            os.path.join(btop_project_path, 'bin/btop'),
                            os.path.join(btop_project_path, 'btop'),
                            os.path.join(btop_project_path, 'build/btop')
                        ]
                        
                        btop_bin = None
                        for candidate in possible_bins:
                            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                                btop_bin = candidate
                                break
                        
                        if btop_bin:
                            # 成功找到可执行文件
                            executables_map = {
                                'valgrind_memcheck': [btop_bin]
                            }
                            tools = ['valgrind_memcheck']
                            valgrind_tools = ['valgrind_memcheck']
                            btop_native_mode = True
                            
                            log_info(f"   ✅ 使用原生编译产物: {btop_bin}")
                            log_warning("   ⚠️  由于构建复杂度,仅使用Valgrind分析")
                        else:
                            log_warning("   ⚠️  未找到btop可执行文件,回退到常规流程")
                    else:
                        log_warning("   ⚠️  btop原生编译失败,回退到常规流程")
                        stderr = make_result.stderr.decode('utf-8', errors='ignore')
                        log_error(f"   编译错误:\n{stderr[:500]}")
                        
                except Exception as e:
                    log_error(f"   ❌ btop编译异常: {e},回退到常规流程")
            
            # 🔥 常规编译流程(仅当btop失败或非btop项目时执行)
            if not btop_native_mode:
                # 自动添加 TSan
                if has_threads and 'tsan' not in tools:
                    log_info("   🧵 检测到多线程，自动添加 ThreadSanitizer 到工具列表")
                    tools.append('tsan')
                    config['tools'] = tools

                # 归类工具
                valgrind_tools = [t for t in tools if t.startswith('valgrind')]
                sanitizer_tools = [t for t in tools if t in ['asan', 'ubsan', 'tsan']]

                log_info(f"   请求的工具（已调整）: {tools}")
                log_info(f"   - Valgrind 工具: {valgrind_tools}")
                log_info(f"   - Sanitizer 工具: {sanitizer_tools}")

                requested_sanitizers: List[str] = config.get('sanitizers', [])
                requested_sanitizers = [s.strip() for s in requested_sanitizers] if requested_sanitizers else []

                need_valgrind_build = bool(valgrind_tools)
                need_asan_build = ('asan' in sanitizer_tools) or ('address' in requested_sanitizers)
                need_ubsan_build = ('ubsan' in sanitizer_tools) or ('undefined' in requested_sanitizers)
                need_tsan_build = ('tsan' in sanitizer_tools) or ('thread' in requested_sanitizers)

                asan_ubsan_sanitizers: List[str] = []
                if need_asan_build or need_ubsan_build:
                    ru = set(requested_sanitizers)
                    base = []
                    if ('asan' in sanitizer_tools) or ('address' in ru) or not requested_sanitizers:
                        base.append('address')
                    if ('ubsan' in sanitizer_tools) or ('undefined' in ru) or not requested_sanitizers:
                        base.append('undefined')
                    seen = set()
                    for s in base:
                        if s not in seen:
                            seen.add(s)
                            asan_ubsan_sanitizers.append(s)

                tsan_sanitizers: List[str] = ['thread'] if need_tsan_build else []

                log_info("   📌 计划构建：")
                log_info(f"      - Valgrind 版本（无 sanitizer）: {need_valgrind_build}")
                log_info(f"      - ASan/UBSan 版本（{asan_ubsan_sanitizers or '无'}）: {bool(asan_ubsan_sanitizers)}")
                log_info(f"      - TSan 版本（thread）: {need_tsan_build}")

                # 构建 1:Valgrind 专用
                valgrind_exes: List[str] = []
                if need_valgrind_build:
                    log_info("   🔨 [构建A] Valgrind 版本(无Sanitizer)...")
                    valgrind_build_dir = os.path.join(project_path, "build_valgrind")
                    vg_result = await self.instrumented_builder.build_with_sanitizers(
                        project_path,
                        sanitizers=[],
                        build_dir=valgrind_build_dir,
                        clean_build=True
                    )
                    if vg_result.get('success'):
                        valgrind_exes = vg_result.get('executables', []) or []
                        
                        # 🔥 立即备份到安全目录
                        backup_dir = os.path.join(project_path, "_safe_valgrind")
                        os.makedirs(backup_dir, exist_ok=True)
                        safe_exes = []
                        for exe in valgrind_exes:
                            backup_path = os.path.join(backup_dir, os.path.basename(exe))
                            shutil.copy2(exe, backup_path)
                            safe_exes.append(backup_path)
                            log_info(f"         📍 已备份: {backup_path}")
                        
                        for t in valgrind_tools:
                            executables_map[t] = list(safe_exes)
                        log_info(f"      ✅ 成功并备份: {len(safe_exes)} 个文件")
                    else:
                        log_error(f"      ❌ 失败: {vg_result.get('error')}")

                # 构建 2:ASan/UBSan 共用版本
                asan_exes: List[str] = []
                if asan_ubsan_sanitizers:
                    log_info("   🔨 [构建B] ASan/UBSan 版本...")
                    asan_build_dir = os.path.join(project_path, "build_asan")
                    asan_result = await self.instrumented_builder.build_with_sanitizers(
                        project_path,
                        sanitizers=asan_ubsan_sanitizers,
                        build_dir=asan_build_dir,
                        clean_build=True
                    )
                    if asan_result.get('success'):
                        asan_exes = asan_result.get('executables', []) or []
                        
                        # 🔥 立即备份
                        backup_dir = os.path.join(project_path, "_safe_asan")
                        os.makedirs(backup_dir, exist_ok=True)
                        safe_exes = []
                        for exe in asan_exes:
                            backup_path = os.path.join(backup_dir, os.path.basename(exe))
                            shutil.copy2(exe, backup_path)
                            safe_exes.append(backup_path)
                            log_info(f"         📍 已备份: {backup_path}")
                        
                        if 'asan' in sanitizer_tools:
                            executables_map['asan'] = list(safe_exes)
                        if 'ubsan' in sanitizer_tools:
                            executables_map['ubsan'] = list(safe_exes)
                        log_info(f"      ✅ 成功并备份: {len(safe_exes)} 个文件")
                    else:
                        log_error(f"      ❌ 失败: {asan_result.get('error')}")

                # 构建 3:TSan 独立版本
                tsan_exes: List[str] = []
                if need_tsan_build:
                    log_info("   🔨 [构建C] TSan 版本(仅 -fsanitize=thread)...")
                    tsan_build_dir = os.path.join(project_path, "build_tsan")
                    tsan_result = await self.instrumented_builder.build_with_sanitizers(
                        project_path,
                        sanitizers=tsan_sanitizers,
                        build_dir=tsan_build_dir,
                        clean_build=True
                    )
                    if tsan_result.get('success'):
                        tsan_exes = tsan_result.get('executables', []) or []
                        
                        # 🔥 立即备份
                        backup_dir = os.path.join(project_path, "_safe_tsan")
                        os.makedirs(backup_dir, exist_ok=True)
                        safe_exes = []
                        for exe in tsan_exes:
                            backup_path = os.path.join(backup_dir, os.path.basename(exe))
                            shutil.copy2(exe, backup_path)
                            safe_exes.append(backup_path)
                            log_info(f"         📍 已备份: {backup_path}")
                        
                        executables_map['tsan'] = list(safe_exes)
                        log_info(f"      ✅ TSan 构建成功并备份: {len(safe_exes)} 个文件")
                    else:
                        log_error(f"      ❌ TSan 构建失败: {tsan_result.get('error')}")
                        log_warning("      ⚠️  将跳过 TSan 动态分析")

            # 检查可执行文件
            if not executables_map:
                return {
                    'success': False,
                    'error': '未生成任何可执行文件（所有构建均失败）'
                }

            # 步骤3：依次运行每个工具
            log_info("=" * 70)
            log_info(f"🏃 步骤3/5: 依次运行动态分析工具")
            log_info(f"   工具总数: {len(tools)}")
            log_info("=" * 70)

            executable_args = config.get('executable_args', [])
            timeout = config.get('timeout', 300)
            output_dir = config.get('output_dir', f'/tmp/dynamic_analysis_{project_id}')

            all_dynamic_issues: List[Dict[str, Any]] = []
            tool_results: List[Dict[str, Any]] = []

            for tool_idx, tool_name in enumerate(tools, 1):
                log_info(f"\n🔧 [{tool_idx}/{len(tools)}] 运行工具: {tool_name}")

                executables = executables_map.get(tool_name, [])
                if not executables:
                    log_warning(f"   ⚠️  工具 {tool_name} 没有匹配的可执行文件，跳过")
                    continue

                log_info(f"   可执行文件数: {len(executables)}")

                for exe_idx, executable_path in enumerate(executables, 1):
                    log_info(f"   └─ [{exe_idx}/{len(executables)}] {executable_path}")

                    analysis_config = {
                        'tools': [tool_name],
                        'executables_map': {tool_name: [executable_path]},
                        'executable_path': executable_path,
                        'executable_args': executable_args,
                        'timeout': timeout,
                        'output_dir': output_dir
                    }

                    exec_result = await self.dynamic_executor.execute_dynamic_analysis(
                        project_path,
                        analysis_config
                    )

                    if exec_result.get('success'):
                        issues = exec_result.get('issues', []) or []
                        log_info(f"      ✅ 发现 {len(issues)} 个问题")
                        for issue in issues:
                            issue['source_tool'] = tool_name
                            issue['source_executable'] = executable_path
                        all_dynamic_issues.extend(issues)
                    else:
                        log_warning(f"      ⚠️  执行失败: {exec_result.get('error')}")

                    tool_results.append({
                        'tool': tool_name,
                        'executable': executable_path,
                        'result': exec_result
                    })

            workflow_result['steps']['dynamic_analysis'] = {
                'tools_run': len(tools),
                'executables_analyzed': sum(len(exes) for exes in executables_map.values()),
                'total_issues': len(all_dynamic_issues),
                'tool_results': tool_results
            }

            # 汇总日志
            log_info("=" * 70)
            log_info(f"📊 动态分析汇总:")
            log_info(f"   运行的工具数: {len(tools)}")
            log_info(f"   分析的可执行文件总数: {sum(len(exes) for exes in executables_map.values())}")
            log_info(f"   发现的问题总数: {len(all_dynamic_issues)}")

            if all_dynamic_issues:
                severity_count: Dict[str, int] = {}
                tool_count: Dict[str, int] = {}
                for issue in all_dynamic_issues:
                    sev = issue.get('severity', 'unknown')
                    tool = issue.get('source_tool', 'unknown')
                    severity_count[sev] = severity_count.get(sev, 0) + 1
                    tool_count[tool] = tool_count.get(tool, 0) + 1

                log_info(f"   问题严重程度分布:")
                for sev, count in sorted(severity_count.items()):
                    log_info(f"      {sev}: {count}")

                log_info(f"   工具检出分布:")
                for tool, count in sorted(tool_count.items()):
                    log_info(f"      {tool}: {count}")

            log_info("=" * 70)

            # 步骤4: 结果关联
            if static_results:
                log_info("🔗 步骤4/5: 关联静态和动态分析结果")

                correlation_result = self.result_correlator.correlate_results(
                    static_results,
                    all_dynamic_issues,
                    tolerance=config.get('line_tolerance', 5)
                )

                workflow_result['steps']['result_correlation'] = correlation_result

                if correlation_result.get('success'):
                    log_info(f"   ✅ 关联成功")
                    log_info(f"      已确认问题: {len(correlation_result.get('confirmed_issues', []))}")
                    log_info(f"      仅静态发现: {len(correlation_result.get('static_only_issues', []))}")
                    log_info(f"      仅动态发现: {len(correlation_result.get('dynamic_only_issues', []))}")
            else:
                log_info("⏭️  步骤4/5: 跳过关联（无静态分析结果）")

            # 步骤5: 汇总结果
            workflow_result['dynamic_issues'] = all_dynamic_issues
            workflow_result['total_issues'] = len(all_dynamic_issues)

            # 统计实际运行的工具
            tools_actually_run = set()
            valgrind_actually_run = False
            asan_actually_run = False
            ubsan_actually_run = False
            tsan_actually_run = False

            for tr in tool_results:
                tool_name = tr.get('tool', '')
                ok = tr.get('result', {}).get('success', False)
                if not ok:
                    continue
                tools_actually_run.add(tool_name)
                if tool_name.startswith('valgrind'):
                    valgrind_actually_run = True
                elif tool_name in ['asan', 'address_sanitizer']:
                    asan_actually_run = True
                elif tool_name in ['ubsan', 'undefined_sanitizer']:
                    ubsan_actually_run = True
                elif tool_name == 'tsan':
                    tsan_actually_run = True

            # 各工具问题数
            valgrind_issue_count = sum(1 for i in all_dynamic_issues if i.get('source_tool', '').startswith('valgrind'))
            asan_issue_count = sum(1 for i in all_dynamic_issues if i.get('source_tool', '') in ['asan', 'address_sanitizer'])
            ubsan_issue_count = sum(1 for i in all_dynamic_issues if i.get('source_tool', '') in ['ubsan', 'undefined_sanitizer'])
            tsan_issue_count = sum(1 for i in all_dynamic_issues if i.get('source_tool', '') == 'tsan')

            # 动态执行信息
            workflow_result['dynamic_execution'] = {
                'executed': len(tools_actually_run) > 0,
                'valgrind_executed': valgrind_actually_run,
                'asan_executed': asan_actually_run,
                'ubsan_executed': ubsan_actually_run,
                'tsan_executed': tsan_actually_run,
                'tools_run': list(tools_actually_run),
                'valgrind_issues': valgrind_issue_count,
                'asan_issues': asan_issue_count,
                'ubsan_issues': ubsan_issue_count,
                'tsan_issues': tsan_issue_count,
                'executables_map': {
                    tool: [os.path.basename(exe) for exe in exes]
                    for tool, exes in executables_map.items()
                },
                'total_executables_analyzed': sum(len(exes) for exes in executables_map.values())
            }

            log_info("=" * 70)
            log_info(f"📊 动态执行状态:")
            log_info(f"   Valgrind 已运行: {valgrind_actually_run}")
            log_info(f"   ASan 已运行: {asan_actually_run}")
            log_info(f"   UBSan 已运行: {ubsan_actually_run}")
            log_info(f"   TSan 已运行: {tsan_actually_run}")
            log_info(f"   Valgrind 问题数: {valgrind_issue_count}")
            log_info(f"   ASan 问题数: {asan_issue_count}")
            log_info(f"   UBSan 问题数: {ubsan_issue_count}")
            log_info(f"   TSan 问题数: {tsan_issue_count}")
            log_info(f"   实际运行工具: {', '.join(sorted(tools_actually_run)) if tools_actually_run else '(无)'}")
            log_info("=" * 70)

            # 最终问题集
            if static_results and workflow_result['steps'].get('result_correlation', {}).get('success'):
                corr = workflow_result['steps']['result_correlation']
                workflow_result['final_issues'] = (
                    corr.get('confirmed_issues', []) +
                    corr.get('static_only_issues', []) +
                    corr.get('dynamic_only_issues', [])
                )
                workflow_result['total_unique_issues'] = len(workflow_result['final_issues'])
            else:
                workflow_result['final_issues'] = all_dynamic_issues
                workflow_result['total_unique_issues'] = len(all_dynamic_issues)

            log_info("=" * 70)
            log_info("🎉 动态分析工作流完成！")
            log_info(f"   最终问题数: {workflow_result.get('total_unique_issues', len(all_dynamic_issues))}")
            log_info("=" * 70)

            return workflow_result

        except Exception as e:
            log_error("=" * 70)
            log_error(f"❌ 动态分析工作流失败: {e}")
            log_error("=" * 70)
            import traceback
            log_error(traceback.format_exc())

            return {
                'success': False,
                'error': str(e),
                'project_id': project_id
            }

    async def run_simple_dynamic_check(
        self,
        executable_path: str,
        tools: List[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """简化的动态检查（直接分析已编译的可执行文件）"""
        tools = tools or ['valgrind_memcheck']

        config = {
            'tools': tools,
            'executable_path': executable_path,
            'executable_args': [],
            'timeout': timeout,
            'output_dir': '/tmp/dynamic_quick_check'
        }

        result = await self.dynamic_executor.execute_dynamic_analysis(
            os.path.dirname(executable_path) or '.',
            config
        )

        return result
