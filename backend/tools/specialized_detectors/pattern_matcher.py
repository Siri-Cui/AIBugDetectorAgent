"""
代码模式匹配器
作用：提供基于正则表达式和AST的代码模式匹配能力
依赖：re, typing, utils.logger
调用关系：被specialized_detectors中的各专项检测器使用
"""
import re
from typing import List, Dict, Any, Optional, Callable
from utils.logger import log_info, log_error


class PatternMatcher:
    """代码模式匹配器基类"""
    
    def __init__(self):
        # 预定义常用模式
        self.patterns = {
            # 内存操作模式
            'malloc': r'\bmalloc\s*\(',
            'free': r'\bfree\s*\(',
            'new': r'\bnew\s+',
            'delete': r'\bdelete\s+',
            'memcpy': r'\bmemcpy\s*\(',
            'memset': r'\bmemset\s*\(',
            
            # 锁操作模式
            'mutex_lock': r'\b(lock|Lock|mutex\.lock)\s*\(',
            'mutex_unlock': r'\b(unlock|Unlock|mutex\.unlock)\s*\(',
            'thread_create': r'\bstd::thread\s*\(',
            
            # 函数调用模式
            'function_call': r'(\w+)\s*\([^)]*\)',
            
            # 指针操作
            'null_check': r'if\s*\(\s*(\w+)\s*==\s*NULL',
            'pointer_deref': r'\*\s*(\w+)',
            
            # 循环模式
            'for_loop': r'for\s*\([^)]+\)',
            'while_loop': r'while\s*\([^)]+\)',
        }
    
    def match_pattern(self, code: str, pattern_name: str) -> List[Dict[str, Any]]:
        """
        匹配指定模式
        
        Args:
            code: 源代码字符串
            pattern_name: 模式名称（从self.patterns中查找）
            
        Returns:
            匹配结果列表，每个元素包含{line, col, matched_text}
        """
        if pattern_name not in self.patterns:
            log_error(f"未知模式: {pattern_name}")
            return []
        
        pattern = self.patterns[pattern_name]
        return self._regex_match(code, pattern)
    
    def _regex_match(self, code: str, regex: str) -> List[Dict[str, Any]]:
        """
        执行正则匹配并返回位置信息
        """
        matches = []
        lines = code.split('\n')
        
        for line_num, line_content in enumerate(lines, 1):
            for match in re.finditer(regex, line_content):
                matches.append({
                    'line': line_num,
                    'col': match.start(),
                    'matched_text': match.group(),
                    'groups': match.groups()
                })
        
        return matches
    
    def find_function_calls(self, code: str, function_name: str) -> List[Dict[str, Any]]:
        """
        查找特定函数的所有调用
        
        Args:
            code: 源代码
            function_name: 函数名（支持正则）
            
        Returns:
            调用位置列表
        """
        pattern = rf'\b{function_name}\s*\([^)]*\)'
        return self._regex_match(code, pattern)
    
    def find_paired_calls(
        self, 
        code: str, 
        open_pattern: str, 
        close_pattern: str
    ) -> Dict[str, Any]:
        """
        查找成对出现的调用（如malloc/free, lock/unlock）
        
        Returns:
            {
                'open_calls': [...],
                'close_calls': [...],
                'unmatched_opens': [...],  # 可能的泄漏
                'unmatched_closes': [...]  # 可能的重复释放
            }
        """
        open_calls = self._regex_match(code, open_pattern)
        close_calls = self._regex_match(code, close_pattern)
        
        # 简单的配对检查（实际项目中需要更复杂的数据流分析）
        open_lines = {match['line'] for match in open_calls}
        close_lines = {match['line'] for match in close_calls}
        
        unmatched_opens = [m for m in open_calls if m['line'] not in close_lines]
        unmatched_closes = [m for m in close_calls if m['line'] not in open_lines]
        
        return {
            'open_calls': open_calls,
            'close_calls': close_calls,
            'unmatched_opens': unmatched_opens,
            'unmatched_closes': unmatched_closes
        }
    
    def add_custom_pattern(self, name: str, regex: str):
        """
        添加自定义匹配模式
        """
        self.patterns[name] = regex
        log_info(f"添加自定义模式: {name}")


class MemoryPatternMatcher(PatternMatcher):
    """内存操作专项模式匹配器"""
    
    def __init__(self):
        super().__init__()
        # 扩展内存相关模式
        self.patterns.update({
            # 内存池相关
            'thread_cache_alloc': r'ThreadCache\s*::\s*Allocate',
            'central_cache_fetch': r'CentralCache\s*::\s*FetchRangeObj',
            'page_cache_newspan': r'PageCache\s*::\s*NewSpan',
            'span_release': r'ReleaseSpanToPageCache',
            
            # 危险操作
            'double_free': r'(free|delete)\s*\([^)]*\).*?\1',  # 简化检测
            'use_after_free': r'(free|delete).*?(\w+).*?\2',  # 启发式
            'buffer_overflow': r'memcpy\s*\([^,]+,\s*[^,]+,\s*sizeof',
        })
    
    def detect_memory_leaks(self, code: str) -> List[Dict[str, Any]]:
        """
        检测潜在内存泄漏
        （实际需要结合数据流分析，这里仅做启发式检查）
        """
        issues = []
        
        # 查找malloc/new但没有对应free/delete的函数
        alloc_pattern = r'(malloc|new)\s*\('
        free_pattern = r'(free|delete)\s*\('
        
        paired_result = self.find_paired_calls(code, alloc_pattern, free_pattern)
        
        for unmatched in paired_result['unmatched_opens']:
            issues.append({
                'type': 'potential_memory_leak',
                'severity': 'medium',
                'line': unmatched['line'],
                'message': f"可能的内存泄漏：分配后未释放 - {unmatched['matched_text']}",
                'suggestion': '检查是否在所有执行路径上正确释放内存'
            })
        
        return issues


class ConcurrencyPatternMatcher(PatternMatcher):
    """并发问题专项模式匹配器"""
    
    def __init__(self):
        super().__init__()
        self.patterns.update({
            # 线程同步
            'static_var': r'static\s+\w+\s+\w+',
            'global_var': r'^(?!.*static)(\w+)\s+\w+;',  # 简化的全局变量检测
            'shared_ptr': r'std::shared_ptr',
            'atomic': r'std::atomic',
            'mutex': r'std::mutex',
        })
    
    def detect_data_races(self, code: str) -> List[Dict[str, Any]]:
        """
        检测潜在的数据竞争
        """
        issues = []
        
        # 查找静态变量但没有锁保护的情况（启发式）
        static_vars = self.match_pattern(code, 'static_var')
        mutex_locks = self.match_pattern(code, 'mutex_lock')
        
        # 简单判断：静态变量所在函数内是否有锁
        for var in static_vars:
            has_lock_nearby = any(
                abs(lock['line'] - var['line']) < 10  # 10行内有锁
                for lock in mutex_locks
            )
            if not has_lock_nearby:
                issues.append({
                    'type': 'potential_data_race',
                    'severity': 'high',
                    'line': var['line'],
                    'message': f"静态变量可能存在数据竞争：{var['matched_text']}",
                    'suggestion': '考虑使用std::mutex或std::atomic保护共享变量'
                })
        
        return issues
