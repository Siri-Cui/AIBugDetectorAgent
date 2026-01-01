"""
btop专项检测器
作用：检测btop项目（C++系统监控工具）的常见问题
重点：内存管理、多线程、系统调用、动态库加载
依赖：pattern_matcher、utils.logger
调用关系：被DetectionAgent调用
"""
import os
import re
from typing import Dict, List, Any
from .pattern_matcher import PatternMatcher, MemoryPatternMatcher
from utils.logger import log_info, log_error


class BtopDetector:
    """btop项目专项检测器"""
    
    def __init__(self):
        self.matcher = PatternMatcher()
        self.memory_matcher = MemoryPatternMatcher()
        
        # btop核心模块
        self.core_modules = [
            'btop.cpp', 'btop_tools.cpp', 'btop_draw.cpp', 
            'btop_menu.cpp', 'btop_input.cpp', 'btop_theme.cpp'
        ]
        
        # 平台特定实现
        self.platform_files = {
            'linux': ['linux/btop_collect.cpp', 'linux/btop_linux.cpp'],
            'macos': ['osx/btop_collect.cpp', 'osx/sensors.cpp'],
            'freebsd': ['freebsd/btop_collect.cpp']
        }
        
        # 关键数据结构
        self.key_classes = [
            'cpu_info', 'mem_info', 'net_info', 'proc_info',
            'disk_info', 'gpu_info', 'Runner', 'Input'
        ]
    
    async def detect(self, project_path: str) -> Dict[str, Any]:
        """执行btop专项检测"""
        try:
            log_info("开始btop专项检测")
            
            issues = []
            files_analyzed = []
            
            # 1. 查找btop相关文件
            btop_files = self._find_btop_files(project_path)
            if not btop_files:
                return {
                    'success': True,
                    'message': '未找到btop相关代码',
                    'issues': [],
                    'files_analyzed': 0
                }
            
            # 2. 对每个文件执行专项检测
            for file_path in btop_files:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        code = f.read()
                    
                    file_issues = []
                    
                    # 检测1: 系统调用错误处理
                    file_issues.extend(self._detect_syscall_errors(code, file_path))
                    
                    # 检测2: 字符串格式化安全
                    file_issues.extend(self._detect_format_string_issues(code, file_path))
                    
                    # 检测3: 容器越界访问
                    file_issues.extend(self._detect_container_bounds(code, file_path))
                    
                    # 检测4: 动态库加载风险
                    file_issues.extend(self._detect_dynamic_loading_issues(code, file_path))
                    
                    # 检测5: 长时间运行的资源泄漏
                    file_issues.extend(self._detect_longrun_leaks(code, file_path))
                    
                    # 检测6: 多线程数据竞争
                    file_issues.extend(self._detect_data_races(code, file_path))
                    
                    issues.extend(file_issues)
                    if file_issues:
                        files_analyzed.append(os.path.basename(file_path))
                    
                except Exception as e:
                    log_error(f"分析文件失败 {file_path}: {str(e)}")
                    continue
            
            log_info(f"btop检测完成，分析{len(files_analyzed)}个文件，发现{len(issues)}个问题")
            
            return {
                'success': True,
                'tool': 'btop_detector',
                'project_type': 'system_monitor',
                'issues': issues,
                'files_analyzed': files_analyzed,
                'summary': {
                    'total_issues': len(issues),
                    'critical': len([i for i in issues if i['severity'] == 'critical']),
                    'high': len([i for i in issues if i['severity'] == 'high']),
                    'medium': len([i for i in issues if i['severity'] == 'medium'])
                }
            }
            
        except Exception as e:
            log_error(f"btop检测异常: {str(e)}")
            return {'success': False, 'error': str(e), 'issues': []}
    
    def _find_btop_files(self, project_path: str) -> List[str]:
        """查找btop相关文件"""
        btop_files = []
        target_patterns = ['btop*.cpp', 'btop*.hpp', 'btop*.h']
        
        for root, dirs, files in os.walk(project_path):
            for file in files:
                if file.endswith(('.cpp', '.hpp', '.h')):
                    # 检查是否包含btop关键字或在src目录
                    if 'btop' in file.lower() or 'src' in root:
                        btop_files.append(os.path.join(root, file))
        
        return btop_files
    
    def _detect_syscall_errors(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测系统调用错误处理（btop历史bug重点）"""
        issues = []
        lines = code.split('\n')
        
        # 危险系统调用列表
        syscalls = [
            'open', 'read', 'write', 'ioctl', 'sysctl',
            'readdir', 'opendir', 'fopen', 'popen'
        ]
        
        for line_num, line in enumerate(lines, 1):
            for syscall in syscalls:
                # 匹配系统调用但未检查返回值
                pattern = rf'\b{syscall}\s*\([^)]*\)'
                if re.search(pattern, line):
                    # 检查后续几行是否有错误检查
                    context = '\n'.join(lines[line_num:min(len(lines), line_num+3)])
                    
                    has_check = any(keyword in context for keyword in [
                        '== -1', '== NULL', '== nullptr', '!= 0', 
                        'if (', 'errno', 'perror', 'throw'
                    ])
                    
                    if not has_check and '//' not in line:
                        issues.append({
                            'type': 'syscall_error_handling',
                            'severity': 'high',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'code': line.strip(),
                            'message': f'系统调用 {syscall}() 可能未检查返回值',
                            'suggestion': f'检查{syscall}的返回值并处理错误（参考errno）'
                        })
        
        return issues
    
    def _detect_format_string_issues(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测字符串格式化安全问题"""
        issues = []
        lines = code.split('\n')
        
        # 危险的格式化函数
        dangerous_formats = ['sprintf', 'vsprintf', 'printf', 'fprintf']
        
        for line_num, line in enumerate(lines, 1):
            for func in dangerous_formats:
                pattern = rf'{func}\s*\([^)]*%[^"\']*\)'
                if re.search(pattern, line):
                    # 检查是否使用了变量作为格式字符串
                    if 'fmt' in line or 'format' in line:
                        issues.append({
                            'type': 'format_string_vulnerability',
                            'severity': 'high',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'code': line.strip(),
                            'message': f'{func}使用变量格式字符串，可能导致安全漏洞',
                            'suggestion': f'使用std::format或snprintf，确保格式字符串为常量'
                        })
        
        return issues
    
    def _detect_container_bounds(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测容器越界访问（btop常见crash原因）"""
        issues = []
        lines = code.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # 检测operator[]访问但未检查size
            if re.search(r'\w+\[\s*\w+\s*\]', line) and 'string' not in line:
                context_start = max(0, line_num - 5)
                context = '\n'.join(lines[context_start:line_num])
                
                # 检查是否有.size()或.empty()检查
                has_bounds_check = bool(re.search(r'\.size\(\)|\.empty\(\)|\.at\(', context))
                
                if not has_bounds_check and 'for' not in context:
                    issues.append({
                        'type': 'container_bounds',
                        'severity': 'high',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'code': line.strip(),
                        'message': '容器下标访问可能越界',
                        'suggestion': '使用.at()替代[]或先检查size()'
                    })
        
        # 检测vector/deque的back()/front()调用
        for line_num, line in enumerate(lines, 1):
            if re.search(r'\.(back|front)\(\)', line):
                context = '\n'.join(lines[max(0, line_num-3):line_num])
                
                if not re.search(r'\.empty\(\)|\.size\(\)', context):
                    issues.append({
                        'type': 'container_empty_access',
                        'severity': 'critical',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'code': line.strip(),
                        'message': '调用back()/front()前可能未检查容器是否为空',
                        'suggestion': '在调用前使用if (!container.empty())检查'
                    })
        
        return issues
    
    def _detect_dynamic_loading_issues(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测动态库加载问题（ROCm等）"""
        issues = []
        lines = code.split('\n')
        
        # 动态加载相关函数
        dl_functions = ['dlopen', 'dlsym', 'LoadLibrary', 'GetProcAddress']
        
        for line_num, line in enumerate(lines, 1):
            for func in dl_functions:
                if func in line:
                    context = '\n'.join(lines[line_num:min(len(lines), line_num+5)])
                    
                    # 检查是否有NULL/nullptr检查
                    has_null_check = 'nullptr' in context or 'NULL' in context or '== 0' in context
                    
                    if not has_null_check:
                        issues.append({
                            'type': 'dynamic_loading',
                            'severity': 'high',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'code': line.strip(),
                            'message': f'{func}返回值未检查，可能导致崩溃',
                            'suggestion': '检查dlopen/dlsym返回值，处理库不存在的情况'
                        })
        
        # 检测结构体版本不匹配（ROCm bug）
        if 'rocm' in file_path.lower() or 'rsmi' in code:
            for line_num, line in enumerate(lines, 1):
                if 'sizeof' in line and 'struct' in line:
                    issues.append({
                        'type': 'struct_version_mismatch',
                        'severity': 'medium',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'code': line.strip(),
                        'message': 'ROCm结构体可能存在版本不匹配',
                        'suggestion': '添加版本检查或使用rsmi_version_get()验证兼容性'
                    })
        
        return issues
    
    def _detect_longrun_leaks(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测长时间运行的资源泄漏（btop特有问题）"""
        issues = []
        lines = code.split('\n')
        
        # 检测循环中的资源分配
        in_loop = False
        loop_start = 0
        
        for line_num, line in enumerate(lines, 1):
            # 检测循环开始
            if re.search(r'\b(while|for)\s*\(', line):
                in_loop = True
                loop_start = line_num
            
            if in_loop:
                # 在循环中查找new/malloc但没有对应的delete/free
                if re.search(r'\bnew\s+\w+|malloc\s*\(', line):
                    # 查找后续是否有释放
                    context = '\n'.join(lines[line_num:min(len(lines), line_num+50)])
                    
                    has_delete = 'delete' in context or 'free(' in context
                    uses_smart_ptr = 'unique_ptr' in context or 'shared_ptr' in context
                    
                    if not (has_delete or uses_smart_ptr):
                        issues.append({
                            'type': 'loop_memory_leak',
                            'severity': 'critical',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'code': line.strip(),
                            'message': '循环中分配内存可能泄漏（长时间运行累积）',
                            'suggestion': '使用智能指针或确保在循环内释放'
                        })
                
                # 检测循环结束
                if line.strip() == '}':
                    in_loop = False
        
        # 检测文件描述符泄漏
        for line_num, line in enumerate(lines, 1):
            if re.search(r'\b(open|fopen|opendir)\s*\(', line):
                context = '\n'.join(lines[line_num:min(len(lines), line_num+30)])
                
                has_close = bool(re.search(r'\b(close|fclose|closedir)\s*\(', context))
                uses_raii = 'ifstream' in context or 'ofstream' in context
                
                if not (has_close or uses_raii):
                    issues.append({
                        'type': 'fd_leak',
                        'severity': 'high',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'code': line.strip(),
                        'message': '文件描述符可能泄漏',
                        'suggestion': '使用RAII（ifstream）或确保在所有路径close'
                    })
        
        return issues
    
    def _detect_data_races(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测多线程数据竞争"""
        issues = []
        lines = code.split('\n')
        
        # 检测全局/静态变量在多线程中访问
        global_vars = []
        for line_num, line in enumerate(lines, 1):
            if re.search(r'\b(static|extern)\s+\w+\s+\w+\s*[=;]', line):
                var_match = re.search(r'\b(static|extern)\s+\w+\s+(\w+)', line)
                if var_match:
                    global_vars.append((var_match.group(2), line_num))
        
        # 检测这些变量是否在没有锁保护的情况下被修改
        for var_name, def_line in global_vars:
            for line_num, line in enumerate(lines, 1):
                if var_name in line and '=' in line and line_num != def_line:
                    context = '\n'.join(lines[max(0, line_num-5):line_num+2])
                    
                    has_lock = bool(re.search(r'mutex|lock|atomic', context))
                    
                    if not has_lock and 'thread' in code.lower():
                        issues.append({
                            'type': 'data_race',
                            'severity': 'critical',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'code': line.strip(),
                            'message': f'全局变量{var_name}可能存在数据竞争',
                            'suggestion': '使用std::mutex或std::atomic保护共享数据'
                        })
        
        return issues
