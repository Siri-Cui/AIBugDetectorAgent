"""
高并发内存池专项检测器
针对ThreadCache->CentralCache->PageCache三层架构的缺陷检测
"""
import os
import re
from typing import Dict, List, Any
from .pattern_matcher import PatternMatcher
from utils.logger import log_info, log_error


class MemoryPoolDetector:
    """内存池专项检测器 - 针对高并发内存池项目"""
    
    def __init__(self):
        self.matcher = PatternMatcher()
        
        # 核心类和方法
        self.core_classes = ['ThreadCache', 'CentralCache', 'PageCache']
        self.critical_methods = {
            'ThreadCache': ['Allocate', 'Deallocate', 'FetchFromCentralCache', 'ListTooLong'],
            'CentralCache': ['FetchRangeObj', 'ReleaseListToSpans', 'GetOneSpan'],
            'PageCache': ['NewSpan', 'ReleaseSpanToPageCache', 'MapObjectToSpan']
        }
        
        # 关键数据结构
        self.data_structures = ['Span', 'FreeList', 'SpanList']
    
    async def detect(self, project_path: str) -> Dict[str, Any]:
        """执行专项检测"""
        try:
            log_info("开始内存池专项检测")
            
            issues = []
            files_analyzed = []
            
            # 1. 查找内存池相关文件
            pool_files = self._find_pool_files(project_path)
            if not pool_files:
                return {
                    'success': True,
                    'message': '未找到内存池相关代码',
                    'issues': [],
                    'files_analyzed': 0
                }
            
            # 2. 对每个文件执行检测
            for file_path in pool_files:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        code = f.read()
                    
                    file_issues = []
                    
                    # 检测1: Span使用计数问题
                    file_issues.extend(self._detect_span_usecount_errors(code, file_path))
                    
                    # 检测2: 锁的粒度问题
                    file_issues.extend(self._detect_lock_granularity(code, file_path))
                    
                    # 检测3: PageCache合并逻辑
                    file_issues.extend(self._detect_page_merge_issues(code, file_path))
                    
                    # 检测4: FreeList操作安全性
                    file_issues.extend(self._detect_freelist_issues(code, file_path))
                    
                    # 检测5: 内存泄漏风险点
                    file_issues.extend(self._detect_memory_leak_risks(code, file_path))
                    
                    issues.extend(file_issues)
                    files_analyzed.append(os.path.basename(file_path))
                    
                except Exception as e:
                    log_error(f"分析文件失败 {file_path}: {str(e)}")
                    continue
            
            log_info(f"内存池检测完成，分析{len(files_analyzed)}个文件，发现{len(issues)}个问题")
            
            return {
                'success': True,
                'tool': 'memory_pool_detector',
                'project_type': 'concurrent_memory_pool',
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
            log_error(f"内存池检测异常: {str(e)}")
            return {'success': False, 'error': str(e), 'issues': []}
    
    def _find_pool_files(self, project_path: str) -> List[str]:
        """查找内存池相关文件"""
        pool_files = []
        target_files = [
            'ThreadCache.cpp', 'ThreadCache.h',
            'CentralCache.cpp', 'CentralCache.h',
            'PageCache.cpp', 'PageCache.h',
            'Common.h', 'ConcurrentAlloc.h'
        ]
        
        for root, dirs, files in os.walk(project_path):
            for file in files:
                if file in target_files or any(cls in file for cls in self.core_classes):
                    pool_files.append(os.path.join(root, file))
        
        return pool_files
    
    def _detect_span_usecount_errors(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测Span使用计数管理错误"""
        issues = []
        lines = code.split('\n')
        
        # 查找 _useCount 的修改
        usecount_pattern = r'span->_useCount\s*([+\-]=|\+\+|--)'
        
        for line_num, line in enumerate(lines, 1):
            if re.search(usecount_pattern, line):
                # 检查是否在锁保护内
                context_start = max(0, line_num - 15)
                context_end = min(len(lines), line_num + 5)
                context = '\n'.join(lines[context_start:context_end])
                
                # 查找是否有mutex.lock()
                has_lock = bool(re.search(r'\._mtx\.lock\(\)', context))
                
                if not has_lock and 'CentralCache' in file_path:
                    issues.append({
                        'type': 'thread_safety',
                        'severity': 'critical',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'code': line.strip(),
                        'message': 'Span._useCount修改可能缺少锁保护',
                        'suggestion': '确保在_spanLists[index]._mtx保护下修改_useCount'
                    })
        
        # 检测 _useCount == 0 判断后是否正确处理
        release_pattern = r'if\s*\(\s*span->_useCount\s*==\s*0\s*\)'
        for line_num, line in enumerate(lines, 1):
            if re.search(release_pattern, line):
                # 检查后续是否有Erase和ReleaseSpanToPageCache
                context = '\n'.join(lines[line_num:min(len(lines), line_num+20)])
                
                has_erase = 'Erase(span)' in context
                has_release = 'ReleaseSpanToPageCache' in context
                
                if not (has_erase and has_release):
                    issues.append({
                        'type': 'resource_leak',
                        'severity': 'high',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'message': 'Span._useCount==0时可能未正确回收到PageCache',
                        'suggestion': '应该调用_spanLists[index].Erase()和PageCache::ReleaseSpanToPageCache()'
                    })
        
        return issues
    
    def _detect_lock_granularity(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测锁粒度问题"""
        issues = []
        lines = code.split('\n')
        
        # 检测跨层调用时的锁顺序
        if 'CentralCache' in file_path:
            for line_num, line in enumerate(lines, 1):
                # 查找CentralCache持锁时调用PageCache
                if '_spanLists[' in line and '_mtx.lock()' in line:
                    # 查找后续是否直接调用PageCache（可能死锁）
                    context = '\n'.join(lines[line_num:min(len(lines), line_num+30)])
                    
                    if 'PageCache::GetInstance()' in context and '_pageMtx.lock()' in context:
                        # 正确做法：先unlock central cache锁
                        if 'list._mtx.unlock()' not in context.split('PageCache')[0]:
                            issues.append({
                                'type': 'deadlock_risk',
                                'severity': 'critical',
                                'file': os.path.basename(file_path),
                                'line': line_num,
                                'message': '可能的死锁：CentralCache持锁时获取PageCache锁',
                                'suggestion': '参考GetOneSpan()，先unlock再获取PageCache锁'
                            })
        
        return issues
    
    def _detect_page_merge_issues(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测PageCache页面合并逻辑"""
        issues = []
        
        if 'PageCache' not in file_path:
            return issues
        
        lines = code.split('\n')
        
        # 查找ReleaseSpanToPageCache函数
        in_release_func = False
        func_start = 0
        
        for line_num, line in enumerate(lines, 1):
            if 'ReleaseSpanToPageCache' in line and '::' in line:
                in_release_func = True
                func_start = line_num
            
            if in_release_func:
                # 检查合并前是否检查_isUse标志
                if 'prevSpan' in line or 'nextSpan' in line:
                    context = '\n'.join(lines[max(0, line_num-5):line_num+5])
                    
                    if '->_isUse' not in context and 'if' in line:
                        issues.append({
                            'type': 'logic_error',
                            'severity': 'high',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'message': '页面合并前可能未检查_isUse标志',
                            'suggestion': '合并前必须确认相邻Span的_isUse == false'
                        })
                
                # 检查是否有128页限制检查
                if 'span->_n' in line and '+' in line:
                    if 'NPAGES' not in '\n'.join(lines[line_num-3:line_num+3]):
                        issues.append({
                            'type': 'boundary_check',
                            'severity': 'medium',
                            'file': os.path.basename(file_path),
                            'line': line_num,
                            'message': '合并Span时可能未检查NPAGES边界',
                            'suggestion': '确保合并后的Span不超过NPAGES-1'
                        })
                
                if line.strip() == '}' and in_release_func:
                    in_release_func = False
        
        return issues
    
    def _detect_freelist_issues(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测FreeList操作安全性"""
        issues = []
        lines = code.split('\n')
        
        # 检测PopRange和PushRange的边界
        for line_num, line in enumerate(lines, 1):
            if 'PopRange' in line:
                # 检查是否有Size()检查
                context = '\n'.join(lines[max(0, line_num-5):line_num])
                
                if 'assert' not in context and 'if' not in context:
                    issues.append({
                        'type': 'boundary_check',
                        'severity': 'medium',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'message': 'PopRange前可能未检查FreeList大小',
                        'suggestion': '调用PopRange前应检查n <= _size'
                    })
            
            # 检测NextObj空指针解引用
            if 'NextObj(end)' in line and '=' in line and 'nullptr' not in line:
                context = '\n'.join(lines[max(0, line_num-3):line_num+1])
                
                if 'while' not in context and 'if' not in context:
                    issues.append({
                        'type': 'null_pointer',
                        'severity': 'high',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'message': '可能的空指针解引用：NextObj(end)未检查end是否为nullptr',
                        'suggestion': '在循环中应检查end != nullptr'
                    })
        
        return issues
    
    def _detect_memory_leak_risks(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检测内存泄漏风险点"""
        issues = []
        lines = code.split('\n')
        
        # 检测SystemAlloc后是否正确映射
        for line_num, line in enumerate(lines, 1):
            if 'SystemAlloc' in line:
                context = '\n'.join(lines[line_num:min(len(lines), line_num+10)])
                
                # 检查是否建立了_idSpanMap映射
                if '_idSpanMap' not in context and 'PageCache' in file_path:
                    issues.append({
                        'type': 'resource_leak',
                        'severity': 'high',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'message': 'SystemAlloc后可能未建立页ID到Span的映射',
                        'suggestion': '调用_idSpanMap.set()建立映射关系'
                    })
        
        # 检测new Span后是否正确管理
        for line_num, line in enumerate(lines, 1):
            if re.search(r'new\s+Span', line):
                context = '\n'.join(lines[line_num:min(len(lines), line_num+20)])
                
                # 检查是否加入到SpanList或_idSpanMap
                if 'PushFront' not in context and '_idSpanMap' not in context:
                    issues.append({
                        'type': 'resource_leak',
                        'severity': 'high',
                        'file': os.path.basename(file_path),
                        'line': line_num,
                        'message': 'new Span后可能未正确管理（未加入SpanList）',
                        'suggestion': '确保Span被加入到_spanLists或建立映射'
                    })
        
        return issues
