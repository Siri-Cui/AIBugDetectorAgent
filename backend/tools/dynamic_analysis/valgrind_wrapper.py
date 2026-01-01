# -*- coding: utf-8 -*-
"""
Valgrind工具封装器
作用：封装Valgrind的memcheck、helgrind、cachegrind工具
依赖：subprocess、xml.etree.ElementTree、utils.logger
调用关系：被dynamic_executor调用
"""
import os
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional
from utils.logger import log_info, log_error, log_warning


class ValgrindWrapper:
    """Valgrind工具封装器"""
    
    def __init__(self):
        self.valgrind_path = self._find_valgrind()
        if not self.valgrind_path:
            log_warning("未找到Valgrind，动态分析功能可能不可用")
    
    def _find_valgrind(self) -> Optional[str]:
        """查找Valgrind可执行文件路径"""
        try:
            result = subprocess.run(
                ['which', 'valgrind'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                log_info(f"找到Valgrind: {path}")
                return path
            return None
        except Exception as e:
            log_error(f"查找Valgrind失败: {e}")
            return None
    
    async def run_memcheck(
        self,
        executable_path: str,
        args: List[str] = None,
        timeout: int = 300,
        output_dir: str = None
    ) -> Dict[str, Any]:
        """
        运行Valgrind Memcheck（内存泄漏检测）
        
        Args:
            executable_path: 可执行文件路径
            args: 程序参数
            timeout: 超时时间（秒）
            output_dir: 输出目录
            
        Returns:
            检测结果字典
        """
        if not self.valgrind_path:
            return {
                'success': False,
                'error': 'Valgrind未安装或未找到'
            }
        
        try:
            log_info(f"开始Valgrind Memcheck分析: {executable_path}")
            
            # 准备输出文件
            output_dir = output_dir or '/tmp'
            os.makedirs(output_dir, exist_ok=True)  # ⭐ 确保目录存在
            xml_output = os.path.join(output_dir, 'valgrind_memcheck.xml')
            
            # 构建Valgrind命令
            cmd = [
                self.valgrind_path,
                '--tool=memcheck',
                '--leak-check=full',
                '--show-leak-kinds=all',
                '--track-origins=yes',
                '--xml=yes',
                f'--xml-file={xml_output}',
                '--verbose',
                executable_path
            ]
            
            if args:
                cmd.extend(args)
            
            log_info(f"🔧 执行命令: {' '.join(cmd)}")  # ⭐ 打印完整命令

            # 执行Valgrind
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(executable_path) or '.'
            )
            
            # ⭐ 关键：打印原始输出
            log_info("="*60)
            log_info("🔍 Valgrind 标准输出 (stdout):")
            log_info(result.stdout if result.stdout else "(空)")
            log_info("🔍 Valgrind 标准错误 (stderr):")
            log_info(result.stderr if result.stderr else "(空)")
            log_info("="*60)
            
            # ⭐ 先检查 XML 文件是否存在
            if not os.path.exists(xml_output):
                log_error(f"❌ XML 文件未生成: {xml_output}")
                
                # 尝试从 stderr 解析（备用方案）
                log_info("尝试从 stderr 解析...")
                issues = self._parse_memcheck_text(result.stderr)
                
                if issues:
                    log_info(f"✅ 从文本输出解析到 {len(issues)} 个问题")
                    return {
                        'success': True,
                        'tool': 'valgrind_memcheck',
                        'issues': issues,
                        'raw_output': result.stderr
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Valgrind未生成XML且无法解析文本输出',
                        'stderr': result.stderr
                    }
            
            # 解析XML输出
            issues = self._parse_memcheck_xml(xml_output)
            log_info(f"Memcheck完成，发现 {len(issues)} 个问题")
            
            return {
                'success': True,
                'tool': 'valgrind_memcheck',
                'issues': issues,
                'raw_output': result.stderr,
                'xml_file': xml_output
            }
                
        except subprocess.TimeoutExpired:
            log_error(f"Valgrind Memcheck超时（{timeout}秒）")
            return {
                'success': False,
                'error': f'执行超时（{timeout}秒）'
            }
        except Exception as e:
            log_error(f"Valgrind Memcheck执行失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _parse_memcheck_text(self, output: str) -> List[Dict[str, Any]]:
        """从文本输出解析 Valgrind 结果（备用方案）"""
        import re
        issues = []
        
        if not output:
            return issues
        
        # 检测 ERROR SUMMARY
        error_summary = re.search(r'ERROR SUMMARY:\s*(\d+)\s+errors?', output)
        if error_summary:
            error_count = int(error_summary.group(1))
            log_info(f"ERROR SUMMARY: {error_count} 个错误")
            
            if error_count == 0:
                return issues
        
        # 解析具体错误
        lines = output.split('\n')
        current_issue = None
        
        for i, line in enumerate(lines):
            # 检测错误行
            if '==' in line and any(keyword in line for keyword in [
                'Invalid read', 'Invalid write', 'Invalid free',
                'Mismatched free', 'definitely lost', 'indirectly lost'
            ]):
                if current_issue:
                    issues.append(current_issue)
                
                # 提取错误类型
                error_type = 'unknown'
                if 'Invalid read' in line:
                    error_type = 'InvalidRead'
                elif 'Invalid write' in line:
                    error_type = 'InvalidWrite'
                elif 'definitely lost' in line:
                    error_type = 'Leak_DefinitelyLost'
                elif 'indirectly lost' in line:
                    error_type = 'Leak_IndirectlyLost'
                
                current_issue = {
                    'type': error_type,
                    'severity': self._map_memcheck_severity(error_type),
                    'message': line.strip(),
                    'tool': 'valgrind_memcheck',
                    'category': 'memory_safety',
                    'stack_trace': []
                }
            
            # 提取位置信息
            elif current_issue and ('at ' in line or 'by ' in line):
                location_match = re.search(r'\(([^:]+):(\d+)\)', line)
                if location_match:
                    file_path = location_match.group(1)
                    line_num = int(location_match.group(2))
                    
                    if 'file' not in current_issue:
                        current_issue['file'] = file_path
                        current_issue['line'] = line_num
                    
                    current_issue['stack_trace'].append({
                        'file': file_path,
                        'line': line_num
                    })
        
        if current_issue:
            issues.append(current_issue)
        
        return issues
    
    def _parse_memcheck_xml(self, xml_file: str) -> List[Dict[str, Any]]:
        """解析Valgrind Memcheck的XML输出"""
        issues = []
        
        # ✅ 添加过滤统计
        FILTERED_LEAK_TYPES = {
            'Leak_StillReachable',     # 仍可达内存（全局变量、静态对象）
            # 'Leak_IndirectlyLost',   # 可选：间接丢失（如果也想过滤）
        }
        
        filtered_stats = {leak_type: 0 for leak_type in FILTERED_LEAK_TYPES}
        total_errors = 0
        
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            for error in root.findall('.//error'):
                total_errors += 1  # ✅ 统计总数
                
                kind = error.find('kind')
                what = error.find('what')
                
                if kind is None:
                    continue
                
                error_kind = kind.text
                
                # ✅ 过滤逻辑
                if error_kind in FILTERED_LEAK_TYPES:
                    filtered_stats[error_kind] += 1
                    continue  # 跳过，不添加到 issues
                
                # 原有的解析逻辑...
                issue = {
                    'type': error_kind,
                    'severity': self._map_memcheck_severity(error_kind),
                    'message': what.text if what is not None else error_kind,
                    'tool': 'valgrind_memcheck',
                    'category': 'memory_safety'
                }
                
                # 提取泄漏字节数
                xwhat = error.find('.//xwhat')
                if xwhat is not None:
                    leakedbytes = xwhat.find('leakedbytes')
                    if leakedbytes is not None:
                        issue['bytes_lost'] = int(leakedbytes.text)
                
                # 提取堆栈跟踪
                stack_trace = []
                stack = error.find('stack')
                if stack is not None:
                    for frame in stack.findall('frame'):
                        fn = frame.find('fn')
                        file_elem = frame.find('file')
                        line = frame.find('line')
                        
                        frame_info = {}
                        if fn is not None:
                            frame_info['function'] = fn.text
                        if file_elem is not None:
                            frame_info['file'] = file_elem.text
                        if line is not None:
                            frame_info['line'] = int(line.text)
                        
                        if frame_info:
                            stack_trace.append(frame_info)
                
                if stack_trace:
                    issue['stack_trace'] = stack_trace
                    # 使用第一个有效栈帧作为主位置
                    for frame in stack_trace:
                        if 'file' in frame and 'line' in frame:
                            issue['file'] = frame['file']
                            issue['line'] = frame['line']
                            break
                
                issues.append(issue)
            
            # ✅ 输出过滤日志
            total_filtered = sum(filtered_stats.values())
            if total_filtered > 0 or total_errors > 0:
                log_info("="*60)
                log_info("🔍 Valgrind 结果过滤统计:")
                log_info(f"   总检测: {total_errors} 个问题")
                log_info(f"   过滤: {total_filtered} 个非关键问题")
                
                for leak_type, count in filtered_stats.items():
                    if count > 0:
                        log_info(f"      - {leak_type}: {count} 个")
                        log_info(f"        原因: 程序退出时仍可达的内存（全局变量、静态对象）")
                        log_info(f"        说明: 非真实内存泄漏，操作系统会在程序结束时回收")
                
                log_info(f"   保留: {len(issues)} 个真实问题")
                
                if len(issues) > 0:
                    # 统计保留问题的类型
                    issue_types = {}
                    for issue in issues:
                        issue_type = issue.get('type', 'unknown')
                        issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
                    
                    log_info(f"   真实问题类型分布:")
                    for issue_type, count in sorted(issue_types.items()):
                        log_info(f"      - {issue_type}: {count} 个")
                
                log_info("="*60)
            
        except Exception as e:
            log_error(f"解析Valgrind XML失败: {e}")
        
        return issues

    
    def _map_memcheck_severity(self, kind: str) -> str:
        """映射Valgrind错误类型到严重性级别"""
        critical_types = [
            'Leak_DefinitelyLost',
            'InvalidRead',
            'InvalidWrite',
            'InvalidFree',
            'MismatchedFree'
        ]
        
        high_types = [
            'Leak_IndirectlyLost',
            'UninitCondition',
            'UninitValue'
        ]
        
        if kind in critical_types:
            return 'critical'
        elif kind in high_types:
            return 'high'
        else:
            return 'medium'
    
    async def run_helgrind(
        self,
        executable_path: str,
        args: List[str] = None,
        timeout: int = 300,
        output_dir: str = None
    ) -> Dict[str, Any]:
        """
        运行Valgrind Helgrind（线程竞争检测）
        
        Args:
            executable_path: 可执行文件路径
            args: 程序参数
            timeout: 超时时间（秒）
            output_dir: 输出目录
            
        Returns:
            检测结果字典
        """
        if not self.valgrind_path:
            return {
                'success': False,
                'error': 'Valgrind未安装或未找到'
            }
        
        try:
            log_info(f"开始Valgrind Helgrind分析: {executable_path}")
            
            # 准备输出文件
            output_dir = output_dir or '/tmp'
            xml_output = os.path.join(output_dir, 'valgrind_helgrind.xml')
            
            # 构建Valgrind命令
            cmd = [
                self.valgrind_path,
                '--tool=helgrind',
                '--xml=yes',
                f'--xml-file={xml_output}',
                '--verbose',
                executable_path
            ]
            
            if args:
                cmd.extend(args)
            
            # 执行Valgrind
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(executable_path) or '.'
            )
            
            # 解析XML输出
            if os.path.exists(xml_output):
                issues = self._parse_helgrind_xml(xml_output)
                log_info(f"Helgrind完成，发现 {len(issues)} 个问题")
                
                return {
                    'success': True,
                    'tool': 'valgrind_helgrind',
                    'issues': issues,
                    'raw_output': result.stderr,
                    'xml_file': xml_output
                }
            else:
                return {
                    'success': False,
                    'error': 'Helgrind未生成输出文件',
                    'stderr': result.stderr
                }
                
        except subprocess.TimeoutExpired:
            log_error(f"Valgrind Helgrind超时（{timeout}秒）")
            return {
                'success': False,
                'error': f'执行超时（{timeout}秒）'
            }
        except Exception as e:
            log_error(f"Valgrind Helgrind执行失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _parse_helgrind_xml(self, xml_file: str) -> List[Dict[str, Any]]:
        """解析Valgrind Helgrind的XML输出"""
        issues = []
        
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            for error in root.findall('.//error'):
                kind = error.find('kind')
                what = error.find('what')
                
                if kind is None:
                    continue
                
                issue = {
                    'type': kind.text,
                    'severity': 'high',  # 线程问题默认高危
                    'message': what.text if what is not None else kind.text,
                    'tool': 'valgrind_helgrind',
                    'category': 'concurrency'
                }
                
                # 提取堆栈跟踪
                stack_trace = []
                for stack in error.findall('stack'):
                    for frame in stack.findall('frame'):
                        fn = frame.find('fn')
                        file_elem = frame.find('file')
                        line = frame.find('line')
                        
                        frame_info = {}
                        if fn is not None:
                            frame_info['function'] = fn.text
                        if file_elem is not None:
                            frame_info['file'] = file_elem.text
                        if line is not None:
                            frame_info['line'] = int(line.text)
                        
                        if frame_info:
                            stack_trace.append(frame_info)
                
                if stack_trace:
                    issue['stack_trace'] = stack_trace
                    # 使用第一个有效栈帧
                    for frame in stack_trace:
                        if 'file' in frame and 'line' in frame:
                            issue['file'] = frame['file']
                            issue['line'] = frame['line']
                            break
                
                issues.append(issue)
            
        except Exception as e:
            log_error(f"解析Helgrind XML失败: {e}")
        
        return issues
    
    async def run_cachegrind(
        self,
        executable_path: str,
        args: List[str] = None,
        timeout: int = 300,
        output_dir: str = None
    ) -> Dict[str, Any]:
        """
        运行Valgrind Cachegrind（性能分析）
        
        Args:
            executable_path: 可执行文件路径
            args: 程序参数
            timeout: 超时时间（秒）
            output_dir: 输出目录
            
        Returns:
            性能分析结果
        """
        if not self.valgrind_path:
            return {
                'success': False,
                'error': 'Valgrind未安装或未找到'
            }
        
        try:
            log_info(f"开始Valgrind Cachegrind分析: {executable_path}")
            
            # 准备输出文件
            output_dir = output_dir or '/tmp'
            cache_output = os.path.join(output_dir, 'cachegrind.out')
            
            # 构建Valgrind命令
            cmd = [
                self.valgrind_path,
                '--tool=cachegrind',
                f'--cachegrind-out-file={cache_output}',
                executable_path
            ]
            
            if args:
                cmd.extend(args)
            
            # 执行Valgrind
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(executable_path) or '.'
            )
            
            log_info("Cachegrind完成")
            
            return {
                'success': True,
                'tool': 'valgrind_cachegrind',
                'cache_file': cache_output,
                'raw_output': result.stderr,
                'message': 'Cachegrind分析完成，使用cg_annotate查看详细结果'
            }
                
        except subprocess.TimeoutExpired:
            log_error(f"Valgrind Cachegrind超时（{timeout}秒）")
            return {
                'success': False,
                'error': f'执行超时（{timeout}秒）'
            }
        except Exception as e:
            log_error(f"Valgrind Cachegrind执行失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
