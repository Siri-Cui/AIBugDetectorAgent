# -*- coding: utf-8 -*-
"""
Sanitizer工具封装器
作用：封装AddressSanitizer、UBSan、TSan
依赖：subprocess、re、utils.logger
调用关系：被dynamic_executor调用
"""
import os
import re
import subprocess
from typing import Dict, List, Any, Optional
from utils.logger import log_info, log_error, log_warning


class SanitizerWrapper:
    """Sanitizer工具封装器（ASan/UBSan/TSan）"""
    
    def __init__(self):
        self.compiler_info = self._detect_compiler()
        if not self.compiler_info:
            log_warning("未找到支持Sanitizer的编译器（需要GCC>=4.8或Clang>=3.1）")
    
    def _detect_compiler(self) -> Optional[Dict[str, str]]:
        """检测编译器及版本"""
        compilers = ['g++', 'clang++', 'gcc', 'clang']
        
        for compiler in compilers:
            try:
                result = subprocess.run(
                    [compiler, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    version_info = result.stdout
                    log_info(f"找到编译器: {compiler}\n{version_info.split(chr(10))[0]}")
                    return {
                        'compiler': compiler,
                        'version': version_info
                    }
            except Exception:
                continue
        
        return None
    
    async def run_asan(
        self,
        executable_path: str,
        args: List[str] = None,
        timeout: int = 300,
        output_dir: str = None
    ) -> Dict[str, Any]:
        """
        运行AddressSanitizer（内存错误检测）
        """
        try:
            log_info(f"开始AddressSanitizer分析: {executable_path}")
            
            # ✅ 设置ASan环境变量 - 移除log_path，直接输出到stderr
            env = os.environ.copy()
            env['ASAN_OPTIONS'] = ':'.join([
                'detect_leaks=1',
                'detect_stack_use_after_return=1',
                'quarantine_size_mb=256',
                'max_free_fill_size=4096',
                'halt_on_error=0',
                'print_stats=1',
                'atexit=1',
                'color=never',
                'symbolize=1',
                'verbosity=2'
            ])
            
            # 执行程序
            cmd = [executable_path]
            if args:
                cmd.extend(args)
            
            log_info(f"🔧 执行命令: {' '.join(cmd)}")
            log_info(f"📝 环境变量: ASAN_OPTIONS={env['ASAN_OPTIONS']}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=os.path.dirname(executable_path) or '.',
                errors='replace'
            )
            
            # ✅ 打印完整输出
            log_info("="*60)
            log_info("🔍 ASan 标准输出 (stdout):")
            log_info(result.stdout if result.stdout else "(空)")
            log_info("="*60)
            log_info("🔍 ASan 标准错误 (stderr) - 完整输出:")
            log_info(result.stderr if result.stderr else "(空)")
            log_info("="*60)
            log_info(f"🔍 退出码: {result.returncode}")
            log_info("="*60)
            
            # ✅ 先尝试解析stderr
            issues = self._parse_asan_output(result.stderr)
            
            # ✅ 如果stderr没有，尝试stdout
            if not issues and result.stdout:
                log_info("尝试从 stdout 解析...")
                issues = self._parse_asan_output(result.stdout)
            
            # ✅ 如果还是没有但退出码异常，记录诊断信息
            if not issues and result.returncode != 0:
                log_warning("⚠️ 程序异常退出但未解析到ASan错误")
                log_warning(f"stderr长度: {len(result.stderr)}, stdout长度: {len(result.stdout)}")
                
                # 查找关键字
                if result.stderr:
                    asan_keywords = ['AddressSanitizer', 'DEADLYSIGNAL', 'SEGV', 'ERROR', 'heap-', 'stack-']
                    found_keywords = [kw for kw in asan_keywords if kw in result.stderr]
                    if found_keywords:
                        log_warning(f"发现关键字: {found_keywords}")
            
            log_info(f"AddressSanitizer完成，发现 {len(issues)} 个问题")
            
            return {
                'success': True,
                'tool': 'address_sanitizer',
                'issues': issues,
                'raw_output': result.stderr,
                'exit_code': result.returncode
            }
                
        except subprocess.TimeoutExpired:
            log_error(f"AddressSanitizer超时（{timeout}秒）")
            return {
                'success': False,
                'error': f'执行超时（{timeout}秒）'
            }
        except Exception as e:
            log_error(f"AddressSanitizer执行失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _parse_asan_output(self, output: str) -> List[Dict[str, Any]]:
        """解析AddressSanitizer输出 - 终极增强版（支持SEGV）"""
        import re
        issues = []
        
        if not output or len(output.strip()) == 0:
            log_warning("⚠️ ASan 输出为空")
            return issues
        
        log_info(f"开始解析ASan输出，长度: {len(output)} 字符")
        
        # ✅ 扩展错误特征检测（🔥 新增 SEGV 和 DEADLYSIGNAL）
        asan_indicators = [
            'AddressSanitizer',
            'LeakSanitizer',
            'ERROR:',
            'DEADLYSIGNAL',
            'SEGV',  # 🔥 核心关键字
            'heap-use-after-free',
            'heap-buffer-overflow',
            'stack-buffer-overflow'
        ]
        
        has_asan_output = any(indicator in output for indicator in asan_indicators)
        if not has_asan_output:
            log_info("✅ 未发现 ASan 错误特征")
            return issues
        
        log_info("🔍 发现ASan特征，开始详细解析...")
        
        # ✅ 多种错误模式（🔥 新增 SEGV 专用模式）
        error_patterns = [
            # 🔥 SEGV 专用模式（最高优先级）
            re.compile(r'==\d+==ERROR: AddressSanitizer:\s*SEGV\s+on\s+(?:un)?known\s+address\s+(0x[\da-f]+)', re.IGNORECASE),
            re.compile(r'AddressSanitizer:\s*SEGV\s+on\s+(?:un)?known\s+address', re.IGNORECASE),
            
            # 标准格式
            re.compile(r'==\d+==ERROR: AddressSanitizer:\s*([\w-]+)'),
            
            # DEADLYSIGNAL
            re.compile(r'AddressSanitizer:(DEADLYSIGNAL)'),
            
            # 直接错误类型
            re.compile(r'(heap-use-after-free|heap-buffer-overflow|stack-buffer-overflow|global-buffer-overflow|use-after-poison)'),
        ]
        
        # ✅ 堆栈跟踪模式
        location_patterns = [
            re.compile(r'#(\d+)\s+0x[\da-f]+\s+in\s+(.+?)\s+([^\s:]+):(\d+)(?::(\d+))?'),
            re.compile(r'#(\d+)\s+([\w:<>~]+(?:::\w+)*)\s+([^\s:]+):(\d+)'),
            re.compile(r'at\s+([^\s:]+):(\d+)'),
        ]
        
        current_issue = None
        stack_trace = []
        lines = output.split('\n')
        
        for i, line in enumerate(lines):
            # ✅ 跳过 SUMMARY 行
            if line.strip().startswith('SUMMARY: AddressSanitizer:'):
                continue
        
            # ✅ 检测错误类型（🔥 SEGV 优先）
            error_found = False
            for pattern_idx, pattern in enumerate(error_patterns):
                match = pattern.search(line)
                if match:
                    if current_issue:
                        if stack_trace:
                            current_issue['stack_trace'] = stack_trace
                        issues.append(current_issue)
                        log_info(f"   ✅ 保存问题: {current_issue['type']}")
                    
                    # 🔥 提取错误类型和地址
                    if pattern_idx == 0:  # SEGV with address
                        error_type = 'SEGV'
                        address = match.group(1)
                        error_description = f"段错误(SEGV): 访问非法地址 {address}"
                    elif pattern_idx == 1:  # SEGV without address
                        error_type = 'SEGV'
                        # 尝试从下一行提取地址
                        address = 'unknown'
                        if i + 1 < len(lines):
                            addr_match = re.search(r'(0x[\da-f]+)', lines[i+1])
                            if addr_match:
                                address = addr_match.group(1)
                        error_description = f"段错误(SEGV): 访问非法地址 {address}"
                    else:
                        error_type = match.group(1)
                        error_description = line.strip()
                    
                    log_info(f"   🎯 发现错误类型: {error_type} (行{i+1})")
                    
                    # 尝试从下一行获取更多信息
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if 'on address' in next_line or 'of size' in next_line or 'The signal' in next_line:
                            error_description += ' | ' + next_line
                    
                    current_issue = {
                        'type': error_type,
                        'severity': self._map_asan_severity(error_type),
                        'message': error_description,
                        'tool': 'address_sanitizer',
                        'category': 'memory_safety',
                        'raw_line': line
                    }
                    stack_trace = []
                    error_found = True
                    break
            
            if error_found:
                continue
            
            # ✅ 提取位置信息
            if current_issue:
                for pattern in location_patterns:
                    match = pattern.search(line)
                    if match:
                        groups = match.groups()
                        
                        if len(groups) >= 4:
                            frame_num = groups[0]
                            function = groups[1]
                            file_path = groups[2]
                            line_num = int(groups[3])
                            col_num = int(groups[4]) if len(groups) > 4 and groups[4] else None
                        elif len(groups) == 4:
                            frame_num = groups[0]
                            function = groups[1]
                            file_path = groups[2]
                            line_num = int(groups[3])
                            col_num = None
                        else:
                            frame_num = None
                            function = None
                            file_path = groups[0]
                            line_num = int(groups[1])
                            col_num = None
                        
                        frame = {
                            'file': file_path,
                            'line': line_num
                        }
                        if function:
                            frame['function'] = function
                        if col_num:
                            frame['column'] = col_num
                        
                        stack_trace.append(frame)
                        
                        # ✅ 设置主位置
                        if 'file' not in current_issue:
                            is_system = any(x in file_path for x in [
                                '/usr/', '/lib/', 'sanitizer_', 'asan_', 
                                'bits/', 'libc.so', '/src/libsanitizer/',
                                '../../../../src/libsanitizer/'
                            ])
                            
                            if not is_system:
                                current_issue['file'] = os.path.basename(file_path)
                                current_issue['line'] = line_num
                                current_issue['location'] = f"{os.path.basename(file_path)}:{line_num}"
                                if col_num:
                                    current_issue['column'] = col_num
                                log_info(f"      📍 位置: {current_issue['location']}")
                        
                        break
        
        # ✅ 保存最后一个问题
        if current_issue:
            if stack_trace:
                current_issue['stack_trace'] = stack_trace
            issues.append(current_issue)
            log_info(f"   ✅ 保存最后的问题: {current_issue['type']}")
        
        log_info(f"解析完成，共发现 {len(issues)} 个问题")
        
        # ✅ 增强的UAF检测
        uaf_issues = self._detect_uaf_patterns(output)
        issues.extend(uaf_issues)
        
        # ✅ 如果没有解析到问题但有ASan特征，记录调试信息
        if not issues and has_asan_output:
            log_warning("⚠️ 检测到ASan输出但未成功解析！")
            log_warning("前200字符预览:")
            log_warning(output[:200])
            
            for i, line in enumerate(lines[:50]):
                if any(kw in line for kw in ['AddressSanitizer', 'ERROR', 'SEGV']):
                    log_warning(f"  行{i}: {line}")
        
        return issues

    
    def _map_asan_severity(self, error_type: str) -> str:
        """映射ASan错误类型到严重性级别（🔥 SEGV=critical）"""
        critical_types = [
            'SEGV',              # 🔥 段错误是致命的！
            'DEADLYSIGNAL',
            'heap-use-after-free',
            'heap-buffer-overflow',
            'stack-buffer-overflow',
            'global-buffer-overflow',
            'use-after-poison',
            'use-after-scope'
        ]
        
        high_types = [
            'stack-use-after-return',
            'stack-use-after-scope',
            'initialization-order-fiasco',
            'memory-leaks'
        ]
        
        error_type_lower = error_type.lower()
        
        if any(ct.lower() in error_type_lower for ct in critical_types):
            return 'critical'
        elif any(ht.lower() in error_type_lower for ht in high_types):
            return 'high'
        else:
            return 'medium'
    

    def _detect_uaf_patterns(self, output: str) -> List[Dict[str, Any]]:
        """增强的Use-After-Free检测"""
        issues = []
        
        log_info("🔍 开始增强 UAF 检测...")
        
        # 模式1：明确的use-after-free
        if 'use-after-free' in output.lower():
            log_info("   ✅ 检测到: use-after-free")
            issues.append({
                'type': 'use-after-free',
                'severity': 'critical',
                'message': 'AddressSanitizer: use-after-free detected',
                'tool': 'address_sanitizer',
                'category': 'memory_safety',
                'source': 'enhanced_uaf_detection'
            })
        
        # 模式2：heap-use-after-free
        if 'heap-use-after-free' in output:
            log_info("   ✅ 检测到: heap-use-after-free")
            issues.append({
                'type': 'heap-use-after-free',
                'severity': 'critical',
                'message': 'AddressSanitizer: heap-use-after-free',
                'tool': 'address_sanitizer',
                'category': 'memory_safety',
                'source': 'enhanced_uaf_detection'
            })
        
        # 模式3：访问已释放内存
        if 'freed by thread' in output and 'previously allocated by thread' in output:
            log_info("   ✅ 检测到: 访问已释放的内存")
            issues.append({
                'type': 'freed-memory-access',
                'severity': 'critical',
                'message': 'AddressSanitizer: access to freed memory',
                'tool': 'address_sanitizer',
                'category': 'memory_safety',
                'source': 'enhanced_uaf_detection'
            })
        
        # 模式4：use-after-poison
        if 'use-after-poison' in output:
            log_info("   ✅ 检测到: use-after-poison")
            issues.append({
                'type': 'use-after-poison',
                'severity': 'critical',
                'message': 'AddressSanitizer: use-after-poison',
                'tool': 'address_sanitizer',
                'category': 'memory_safety',
                'source': 'enhanced_uaf_detection'
            })
        
        # 模式5：stack-use-after-return
        if 'stack-use-after-return' in output:
            log_info("   ✅ 检测到: stack-use-after-return")
            issues.append({
                'type': 'stack-use-after-return',
                'severity': 'critical',
                'message': 'AddressSanitizer: stack-use-after-return',
                'tool': 'address_sanitizer',
                'category': 'memory_safety',
                'source': 'enhanced_uaf_detection'
            })
        
        if issues:
            log_info(f"   📊 增强检测发现 {len(issues)} 个 UAF 问题")
        else:
            log_info("   ℹ️  增强检测未发现额外 UAF 问题")
        
        return issues

    async def run_ubsan(
        self,
        executable_path: str,
        args: List[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """运行UndefinedBehaviorSanitizer（未定义行为检测）"""
        try:
            log_info(f"开始UBSan分析: {executable_path}")
            
            env = os.environ.copy()
            env['UBSAN_OPTIONS'] = 'print_stacktrace=1:halt_on_error=0'
            
            cmd = [executable_path]
            if args:
                cmd.extend(args)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=os.path.dirname(executable_path) or '.'
            )
            
            issues = self._parse_ubsan_output(result.stderr)
            log_info(f"UBSan完成，发现 {len(issues)} 个问题")
            
            return {
                'success': True,
                'tool': 'undefined_behavior_sanitizer',
                'issues': issues,
                'raw_output': result.stderr,
                'exit_code': result.returncode
            }
                
        except subprocess.TimeoutExpired:
            log_error(f"UBSan超时（{timeout}秒）")
            return {
                'success': False,
                'error': f'执行超时（{timeout}秒）'
            }
        except Exception as e:
            log_error(f"UBSan执行失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _parse_ubsan_output(self, output: str) -> List[Dict[str, Any]]:
        """解析UBSan输出"""
        issues = []
        
        ubsan_pattern = re.compile(
            r'([^:]+):(\d+):(\d+):\s+runtime error:\s+(.+)'
        )
        
        for line in output.split('\n'):
            match = ubsan_pattern.search(line)
            if match:
                file_path = match.group(1)
                line_num = int(match.group(2))
                col_num = int(match.group(3))
                error_msg = match.group(4)
                
                issue = {
                    'type': 'undefined_behavior',
                    'severity': 'high',
                    'message': f'未定义行为: {error_msg}',
                    'file': file_path,
                    'line': line_num,
                    'column': col_num,
                    'tool': 'undefined_behavior_sanitizer',
                    'category': 'undefined_behavior'
                }
                issues.append(issue)
        
        return issues
    
    async def run_tsan(
        self,
        executable_path: str,
        args: List[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """运行ThreadSanitizer（线程竞争检测）"""
        try:
            log_info(f"开始ThreadSanitizer分析: {executable_path}")
            
            env = os.environ.copy()
            env['TSAN_OPTIONS'] = ':'.join([
                'halt_on_error=0',
                'second_deadlock_stack=1',
                'report_atomic_races=1',
                'force_seq_cst_atomics=1',
                'detect_deadlocks=1',
                'history_size=7',
                'io_sync=0'
            ])
            
            cmd = [executable_path]
            if args:
                cmd.extend(args)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=os.path.dirname(executable_path) or '.'
            )
            
            issues = self._parse_tsan_output(result.stderr)
            log_info(f"ThreadSanitizer完成，发现 {len(issues)} 个问题")
            
            return {
                'success': True,
                'tool': 'thread_sanitizer',
                'issues': issues,
                'raw_output': result.stderr,
                'exit_code': result.returncode
            }
                
        except subprocess.TimeoutExpired:
            log_error(f"ThreadSanitizer超时（{timeout}秒）")
            return {
                'success': False,
                'error': f'执行超时（{timeout}秒）'
            }
        except Exception as e:
            log_error(f"ThreadSanitizer执行失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _parse_tsan_output(self, output: str) -> List[Dict[str, Any]]:
        """解析TSan输出 - 增强版"""
        import re
        issues = []
        
        if not output or len(output.strip()) == 0:
            log_info("✅ ThreadSanitizer 未发现问题")
            return issues
        
        log_info(f"开始解析TSan输出，长度: {len(output)} 字符")
        
        tsan_indicators = [
            'ThreadSanitizer:',
            'WARNING: ThreadSanitizer',
            'data race',
            'lock-order-inversion',
            'DEADLOCK'
        ]
        
        has_tsan_output = any(indicator in output for indicator in tsan_indicators)
        if not has_tsan_output:
            log_info("✅ 未发现 ThreadSanitizer 错误特征")
            return issues
        
        log_info("🔍 发现 ThreadSanitizer 特征，开始详细解析...")
        
        error_patterns = [
            re.compile(r'WARNING: ThreadSanitizer:\s*([\w\s-]+)'),
            re.compile(r'ThreadSanitizer:\s*(data race|lock-order-inversion|deadlock)'),
        ]
        
        location_patterns = [
            re.compile(r'#(\d+)\s+([\w:<>~]+(?:::\w+)*)\s+([^\s:]+):(\d+)'),
            re.compile(r'at\s+([^\s:]+):(\d+)'),
        ]
        
        current_issue = None
        stack_trace = []
        lines = output.split('\n')
        
        for i, line in enumerate(lines):
            error_found = False
            for pattern in error_patterns:
                match = pattern.search(line)
                if match:
                    if current_issue:
                        if stack_trace:
                            current_issue['stack_trace'] = stack_trace
                        issues.append(current_issue)
                        log_info(f"   ✅ 保存 TSAN 问题: {current_issue['type']}")
                    
                    error_type = match.group(1).strip()
                    log_info(f"   🎯 发现 TSAN 错误: {error_type} (行{i+1})")
                    
                    current_issue = {
                        'type': error_type.replace(' ', '-'),
                        'severity': 'critical' if 'data race' in error_type.lower() else 'high',
                        'message': f'ThreadSanitizer: {error_type}',
                        'tool': 'thread_sanitizer',
                        'category': 'concurrency',
                        'raw_line': line
                    }
                    stack_trace = []
                    error_found = True
                    break
            
            if error_found:
                continue
            
            if current_issue:
                for pattern in location_patterns:
                    match = pattern.search(line)
                    if match:
                        groups = match.groups()
                        
                        if len(groups) == 4:
                            frame_num, function, file_path, line_num = groups
                        else:
                            function = None
                            file_path, line_num = groups
                        
                        frame = {
                            'file': file_path,
                            'line': int(line_num)
                        }
                        if function:
                            frame['function'] = function
                        
                        stack_trace.append(frame)
                        
                        if 'file' not in current_issue:
                            is_system = any(x in file_path for x in [
                                '/usr/', '/lib/', 'tsan_', '/src/libsanitizer/'
                            ])
                            
                            if not is_system:
                                current_issue['file'] = os.path.basename(file_path)
                                current_issue['line'] = int(line_num)
                                current_issue['location'] = f"{os.path.basename(file_path)}:{line_num}"
                                log_info(f"      📍 位置: {current_issue['location']}")
                        
                        break
        
        if current_issue:
            if stack_trace:
                current_issue['stack_trace'] = stack_trace
            issues.append(current_issue)
            log_info(f"   ✅ 保存最后的 TSAN 问题: {current_issue['type']}")
        
        log_info(f"ThreadSanitizer 解析完成，共发现 {len(issues)} 个问题")
        
        return issues

    
    def get_compile_flags(self, sanitizers: List[str]) -> str:
        """获取Sanitizer编译标志"""
        valid_sanitizers = []
        
        for san in sanitizers:
            if san in ['address', 'undefined', 'thread', 'leak', 'memory']:
                valid_sanitizers.append(san)
        
        if not valid_sanitizers:
            return ''
        
        flags = f"-fsanitize={','.join(valid_sanitizers)} -fno-omit-frame-pointer -g"
        
        log_info(f"生成Sanitizer编译标志: {flags}")
        return flags
