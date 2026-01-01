# -*- coding: utf-8 -*-
"""结果解析器
作用：统一处理不同工具的输出，标准化结果格式，过滤噪音
依赖：utils.logger
调用关系：被DetectionAgent调用
"""
import re
from typing import Dict, List, Any, Optional
from utils.logger import log_info, log_error


class ResultParser:
    def __init__(self):
        self.severity_map = {
            'error': 'high',
            'warning': 'medium',
            'info': 'low',
            'style': 'low',
            'performance': 'medium',
            'portability': 'low',
            'information': 'info',
            'high': 'high',
            'medium': 'medium',
            'low': 'low',
            'critical': 'high',
            'note': 'info'
        }
        
        # 🆕 新增：定义需要过滤的噪音模式 (针对Qt和编译中间文件)
        self.ignore_patterns = [
            r'moc_.*\.cpp',      # Qt元对象编译器生成文件
            r'qrc_.*\.cpp',      # Qt资源编译器生成文件
            r'ui_.*\.h',         # Qt界面生成文件
            r'build/',           # 构建目录
            r'cmake-build',      # CMake构建目录
            r'CMakeFiles/',
            r'\.g\.',            # Go生成文件(如果有)
            r'CMakeLists\.txt',  # 构建脚本
            r'Makefile'
        ]
        
        # 🆕 新增：定义需要忽略的特定错误消息 (环境配置相关噪音)
        self.ignore_messages = [
            "file not found",           # 缺少头文件导致的错误
            "unknown type",             # 类型推导失败
            "ConfigurationNotChecked",  # Cppcheck配置跳过警告
            "clang-diagnostic-error",   # Clang编译环境错误
            "too many errors emitted"   # 错误过多提示
        ]

    def parse_and_merge(
        self, 
        tool_results: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """解析并合并多个工具的结果"""
        try:
            all_issues = []
            tool_summaries = {}
            
            for tool_name, result in tool_results.items():
                if not isinstance(result, dict) or not result.get('success', False):
                    # 容错处理：如果是Exception对象或者success=False
                    error_msg = str(result.get('error', 'Unknown error')) if isinstance(result, dict) else str(result)
                    log_error(f"工具 {tool_name} 分析失败或跳过: {error_msg}")
                    tool_summaries[tool_name] = {
                        'success': False,
                        'issues_count': 0,
                        'error': error_msg
                    }
                    continue
                
                issues = result.get('issues', [])
                # 🆕 在解析时直接过滤噪音
                parsed_issues = self._parse_tool_issues(tool_name, issues)
                
                # 如果有上下文信息，进行进一步的业务逻辑过滤 (保留原有逻辑)
                if context:
                    parsed_issues = self._filter_issues_by_context(parsed_issues, context)
                
                all_issues.extend(parsed_issues)
                
                tool_summaries[tool_name] = {
                    'success': True,
                    'issues_count': len(parsed_issues)
                }
                
                log_info(f"解析 {tool_name} 结果: {len(issues)} -> {len(parsed_issues)} (过滤后)")
            
            # 去重和排序
            deduplicated_issues = self._deduplicate_issues(all_issues)
            sorted_issues = self._sort_issues_by_priority(deduplicated_issues)
            
            # 生成统计信息
            statistics = self._generate_statistics(sorted_issues)
            
            return {
                'total_issues': len(sorted_issues),
                'issues': sorted_issues,
                'statistics': statistics,
                'tool_summaries': tool_summaries
            }
            
        except Exception as e:
            log_error(f"结果解析失败: {str(e)}")
            import traceback
            log_error(traceback.format_exc())
            return {
                'total_issues': 0,
                'issues': [],
                'statistics': {},
                'tool_summaries': {},
                'error': str(e)
            }
    
    def _is_noise(self, file_path: str, message: str) -> bool:
        """🆕 判断是否为噪音数据"""
        # 1. 检查文件路径黑名单
        for pattern in self.ignore_patterns:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
                
        # 2. 检查错误消息黑名单
        msg_lower = message.lower()
        for ignore_msg in self.ignore_messages:
            if ignore_msg.lower() in msg_lower:
                return True
                
        # 3. 过滤系统绝对路径报错 (如 /usr/include, /opt)
        # 我们只关心用户上传目录下的代码
        if file_path.startswith('/') and 'uploads' not in file_path:
             # 这里做一个简单的判断，如果不是包含在我们的工作目录里，可能是系统库
             if file_path.startswith('/usr/') or file_path.startswith('/opt/'):
                 return True
            
        return False

    def _parse_tool_issues(self, tool_name: str, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """解析特定工具的问题列表"""
        parsed_issues = []
        
        for i, issue_data in enumerate(issues):
            try:
                file_path = issue_data.get('file', 'unknown')
                message = issue_data.get('message', '')
                
                # 🆕 过滤逻辑入口
                if self._is_noise(file_path, message):
                    continue

                # 处理 Flawfinder 的数值型 severity
                raw_severity = issue_data.get('severity', 'info')
                
                parsed_issue = {
                    'id': f"{tool_name}_{i}_{hash(str(issue_data)) % 10000}",
                    'file': file_path,
                    'line': issue_data.get('line', 0),
                    'column': issue_data.get('column'),
                    'severity': self._normalize_severity(raw_severity),
                    'category': issue_data.get('category', 'code_quality'), # 默认类别
                    'message': message,
                    'tool': tool_name
                }
                parsed_issues.append(parsed_issue)
                
            except Exception as e:
                log_error(f"解析问题失败 {tool_name}: {str(e)}")
                continue
        
        return parsed_issues
    
    def _filter_issues_by_context(
        self, 
        issues: List[Dict[str, Any]], 
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """根据上下文过滤误报（保留原有逻辑）"""
        platform_info = context.get('platform_info', {})
        detected_platforms = platform_info.get('detected_platforms', [])
        
        filtered_issues = []
        for issue in issues:
            message_lower = issue.get('message', '').lower()
            
            if 'windows' in detected_platforms:
                # 跳过Linux特定的警告
                if any(keyword in message_lower for keyword in ['pthread', 'fork', 'sbrk']):
                    continue
            
            filtered_issues.append(issue)
        
        return filtered_issues
    
    def _normalize_severity(self, severity: Any) -> str:
        """标准化严重程度 (增强版，支持数字)"""
        # 处理 Flawfinder 的数字等级 (1-5)
        if isinstance(severity, int) or (isinstance(severity, str) and severity.isdigit()):
            level = int(severity)
            if level >= 4: return 'critical'
            if level == 3: return 'high'
            if level == 2: return 'medium'
            return 'low'
            
        severity_lower = str(severity).lower()
        return self.severity_map.get(severity_lower, 'medium')
    
    def _deduplicate_issues(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去除重复的问题 (增强版：允许不同工具报同一行，但去除完全重复项)"""
        seen = set()
        deduplicated = []
        
        for issue in issues:
            # Key: 文件 + 行号 + 工具 + 消息摘要
            # 这样如果两个工具都报了同一行，我们都保留（因为视角不同）
            # 但如果同一个工具对同一行报了两次一样的，就去重
            key = (issue['file'], issue['line'], issue['tool'], issue['message'][:50])
            
            if key not in seen:
                seen.add(key)
                deduplicated.append(issue)
        
        return deduplicated
    
    def _sort_issues_by_priority(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按优先级排序问题"""
        severity_priority = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
        
        return sorted(issues, key=lambda x: (
            severity_priority.get(x['severity'], 4),
            x['file'],
            x['line']
        ))
    
    def _generate_statistics(self, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成统计信息"""
        stats = {
            'severity_distribution': {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0},
            'category_distribution': {},
            'file_distribution': {},
            'tool_distribution': {}
        }
        
        for issue in issues:
            sev = issue['severity']
            # 容错：如果sev不在默认key里，设为medium
            if sev not in stats['severity_distribution']:
                sev = 'medium'
            stats['severity_distribution'][sev] += 1
            
            category = issue['category']
            stats['category_distribution'][category] = stats['category_distribution'].get(category, 0) + 1
            
            file_path = issue['file']
            stats['file_distribution'][file_path] = stats['file_distribution'].get(file_path, 0) + 1
            
            tool = issue['tool']
            stats['tool_distribution'][tool] = stats['tool_distribution'].get(tool, 0) + 1
        
        return stats
