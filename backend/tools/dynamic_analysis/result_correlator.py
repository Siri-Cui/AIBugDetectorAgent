# -*- coding: utf-8 -*-
"""
静动态结果关联器
作用：关联静态和动态分析结果，计算置信度
依赖：utils.logger
调用关系：被validation_agent调用
"""
from typing import Dict, List, Any, Optional, Tuple
from utils.logger import log_info, log_error, log_warning


class ResultCorrelator:
    """静态和动态分析结果关联器"""
    
    def __init__(self):
        self.confidence_weights = {
            'dynamic_confirmed': 1.0,      # 动态确认 = 100%
            'static_only': 0.6,            # 仅静态 = 60%
            'dynamic_only': 0.8,           # 仅动态 = 80%
            'both_confirmed': 1.0          # 双重确认 = 100%
        }
    
    def correlate_results(
        self,
        static_issues: List[Dict[str, Any]],
        dynamic_issues: List[Dict[str, Any]],
        tolerance: int = 5
    ) -> Dict[str, Any]:
        """
        关联静态和动态分析结果
        
        Args:
            static_issues: 静态分析问题列表
            dynamic_issues: 动态分析问题列表
            tolerance: 行号容差（允许±N行的匹配）
            
        Returns:
            关联结果
        """
        try:
            log_info(f"开始关联结果：静态 {len(static_issues)} 个，动态 {len(dynamic_issues)} 个")
            
            # 分类结果
            confirmed_issues = []      # 静动态都发现
            static_only_issues = []    # 仅静态发现
            dynamic_only_issues = []   # 仅动态发现
            
            # 用于跟踪已匹配的动态问题
            matched_dynamic_indices = set()
            
            # 遍历静态问题，尝试匹配动态问题
            for static_issue in static_issues:
                matched_dynamic = self._find_matching_dynamic_issue(
                    static_issue,
                    dynamic_issues,
                    matched_dynamic_indices,
                    tolerance
                )
                
                if matched_dynamic:
                    # 找到匹配，合并信息
                    confirmed_issue = self._merge_issues(
                        static_issue,
                        matched_dynamic,
                        'both_confirmed'
                    )
                    confirmed_issues.append(confirmed_issue)
                    matched_dynamic_indices.add(dynamic_issues.index(matched_dynamic))
                else:
                    # 仅静态发现
                    static_only = self._enhance_issue(
                        static_issue,
                        'static_only'
                    )
                    static_only_issues.append(static_only)
            
            # 找出仅动态发现的问题
            for idx, dynamic_issue in enumerate(dynamic_issues):
                if idx not in matched_dynamic_indices:
                    dynamic_only = self._enhance_issue(
                        dynamic_issue,
                        'dynamic_only'
                    )
                    dynamic_only_issues.append(dynamic_only)
            
            # 生成统计信息
            statistics = self._generate_statistics(
                confirmed_issues,
                static_only_issues,
                dynamic_only_issues
            )
            
            log_info(f"关联完成：确认 {len(confirmed_issues)}，仅静态 {len(static_only_issues)}，仅动态 {len(dynamic_only_issues)}")
            
            return {
                'success': True,
                'confirmed_issues': confirmed_issues,
                'static_only_issues': static_only_issues,
                'dynamic_only_issues': dynamic_only_issues,
                'statistics': statistics,
                'total_unique_issues': len(confirmed_issues) + len(static_only_issues) + len(dynamic_only_issues)
            }
            
        except Exception as e:
            log_error(f"结果关联失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _find_matching_dynamic_issue(
        self,
        static_issue: Dict[str, Any],
        dynamic_issues: List[Dict[str, Any]],
        matched_indices: set,
        tolerance: int
    ) -> Optional[Dict[str, Any]]:
        """查找匹配的动态问题"""
        static_file = static_issue.get('file', '')
        static_line = static_issue.get('line', -1)
        static_type = static_issue.get('type', '')
        
        if not static_file or static_line < 0:
            return None
        
        # 类型映射（静态检测器类型 -> 动态工具类型）
        type_mapping = {
            # Cppcheck -> Valgrind/Sanitizer
            'memleak': ['Leak_DefinitelyLost', 'Leak_IndirectlyLost', 'memory-leaks', 'heap-use-after-free'],
            'uninitvar': ['UninitCondition', 'UninitValue'],
            'bufferAccessOutOfBounds': ['heap-buffer-overflow', 'stack-buffer-overflow', 'InvalidRead', 'InvalidWrite'],
            'nullPointer': ['InvalidRead', 'InvalidWrite'],
            'doubleFree': ['InvalidFree', 'MismatchedFree'],
            # Clang-Tidy -> Sanitizer
            'bugprone-use-after-move': ['heap-use-after-free'],
            'bugprone-dangling-handle': ['stack-use-after-return'],
            'misc-misplaced-const': ['undefined_behavior'],
            # Infer -> Sanitizer
            'NULL_DEREFERENCE': ['InvalidRead', 'InvalidWrite'],
            'MEMORY_LEAK': ['memory-leaks', 'Leak_DefinitelyLost'],
            'RESOURCE_LEAK': ['Leak_DefinitelyLost'],
        }
        
        # 尝试匹配
        best_match = None
        best_score = 0
        
        for idx, dynamic_issue in enumerate(dynamic_issues):
            if idx in matched_indices:
                continue
            
            dynamic_file = dynamic_issue.get('file', '')
            dynamic_line = dynamic_issue.get('line', -1)
            dynamic_type = dynamic_issue.get('type', '')
            
            # 匹配文件名（支持相对路径和绝对路径）
            if not self._files_match(static_file, dynamic_file):
                continue
            
            # 匹配行号（允许容差）
            if abs(dynamic_line - static_line) > tolerance:
                continue
            
            # 计算匹配分数
            score = 0
            
            # 行号越接近，分数越高
            line_diff = abs(dynamic_line - static_line)
            score += (tolerance - line_diff) / tolerance * 50
            
            # 类型匹配
            if self._types_match(static_type, dynamic_type, type_mapping):
                score += 50
            
            if score > best_score:
                best_score = score
                best_match = dynamic_issue
        
        # 至少需要50分才认为匹配（基本行号匹配）
        if best_score >= 50:
            return best_match
        
        return None
    
    def _files_match(self, file1: str, file2: str) -> bool:
        """判断两个文件路径是否指向同一文件"""
        import os
        
        # 标准化路径
        file1_normalized = os.path.normpath(file1)
        file2_normalized = os.path.normpath(file2)
        
        # 完全匹配
        if file1_normalized == file2_normalized:
            return True
        
        # 文件名匹配（忽略路径）
        if os.path.basename(file1_normalized) == os.path.basename(file2_normalized):
            return True
        
        # 检查一个是否为另一个的后缀
        if file1_normalized.endswith(file2_normalized) or file2_normalized.endswith(file1_normalized):
            return True
        
        return False
    
    def _types_match(
        self,
        static_type: str,
        dynamic_type: str,
        type_mapping: Dict[str, List[str]]
    ) -> bool:
        """判断静态和动态问题类型是否匹配"""
        # 直接匹配
        if static_type == dynamic_type:
            return True
        
        # 通过映射表匹配
        if static_type in type_mapping:
            if dynamic_type in type_mapping[static_type]:
                return True
        
        # 部分字符串匹配（例如 "leak" 匹配 "memleak" 和 "Leak_DefinitelyLost"）
        static_lower = static_type.lower()
        dynamic_lower = dynamic_type.lower()
        
        keywords = ['leak', 'buffer', 'overflow', 'null', 'uninit', 'free', 'use-after']
        for keyword in keywords:
            if keyword in static_lower and keyword in dynamic_lower:
                return True
        
        return False
    
    def _merge_issues(
        self,
        static_issue: Dict[str, Any],
        dynamic_issue: Dict[str, Any],
        confirmation_type: str
    ) -> Dict[str, Any]:
        """合并静态和动态问题"""
        merged = static_issue.copy()
        
        # 更新置信度
        merged['confidence'] = self.confidence_weights[confirmation_type]
        merged['confirmation_type'] = confirmation_type
        merged['verified_by_dynamic'] = True
        
        # 添加动态分析信息
        merged['dynamic_tool'] = dynamic_issue.get('tool', 'unknown')
        merged['dynamic_type'] = dynamic_issue.get('type', '')
        merged['dynamic_severity'] = dynamic_issue.get('severity', '')
        
        # 如果动态分析有堆栈跟踪，添加进来
        if 'stack_trace' in dynamic_issue:
            merged['dynamic_stack_trace'] = dynamic_issue['stack_trace']
        
        # 提升严重性（动态确认的问题更严重）
        if merged.get('severity') == 'medium':
            merged['severity'] = 'high'
        elif merged.get('severity') == 'low':
            merged['severity'] = 'medium'
        
        # 提升优先级
        current_priority = merged.get('priority', 50)
        merged['priority'] = min(current_priority + 20, 100)
        
        return merged
    
    def _enhance_issue(
        self,
        issue: Dict[str, Any],
        confirmation_type: str
    ) -> Dict[str, Any]:
        """增强单个问题的信息"""
        enhanced = issue.copy()
        
        enhanced['confidence'] = self.confidence_weights[confirmation_type]
        enhanced['confirmation_type'] = confirmation_type
        
        if confirmation_type == 'static_only':
            enhanced['verified_by_dynamic'] = False
            enhanced['note'] = '仅静态分析发现，建议人工验证'
        elif confirmation_type == 'dynamic_only':
            enhanced['verified_by_dynamic'] = True
            enhanced['note'] = '动态分析发现，静态分析未检出'
            # 动态独有的问题可能是静态分析遗漏，提升优先级
            current_priority = enhanced.get('priority', 50)
            enhanced['priority'] = min(current_priority + 10, 100)
        
        return enhanced
    
    def _generate_statistics(
        self,
        confirmed: List[Dict],
        static_only: List[Dict],
        dynamic_only: List[Dict]
    ) -> Dict[str, Any]:
        """生成统计信息"""
        total = len(confirmed) + len(static_only) + len(dynamic_only)
        
        if total == 0:
            return {
                'total_issues': 0,
                'confirmation_rate': 0.0,
                'static_miss_rate': 0.0,
                'false_positive_rate': 0.0
            }
        
        return {
            'total_issues': total,
            'confirmed_count': len(confirmed),
            'static_only_count': len(static_only),
            'dynamic_only_count': len(dynamic_only),
            'confirmation_rate': len(confirmed) / (len(confirmed) + len(static_only)) if (len(confirmed) + len(static_only)) > 0 else 0.0,
            'static_miss_rate': len(dynamic_only) / total,
            'dynamic_verification_rate': len(confirmed) / total,
            'severity_distribution': self._count_by_severity(confirmed + static_only + dynamic_only),
            'category_distribution': self._count_by_category(confirmed + static_only + dynamic_only)
        }
    
    def _count_by_severity(self, issues: List[Dict]) -> Dict[str, int]:
        """按严重性统计"""
        counts = {}
        for issue in issues:
            severity = issue.get('severity', 'unknown')
            counts[severity] = counts.get(severity, 0) + 1
        return counts
    
    def _count_by_category(self, issues: List[Dict]) -> Dict[str, int]:
        """按类别统计"""
        counts = {}
        for issue in issues:
            category = issue.get('category', 'unknown')
            counts[category] = counts.get(category, 0) + 1
        return counts
    
    def generate_correlation_report(self, correlation_result: Dict[str, Any]) -> str:
        """生成关联报告（Markdown格式）"""
        if not correlation_result.get('success'):
            return "# 结果关联失败\n\n" + correlation_result.get('error', '')
        
        stats = correlation_result.get('statistics', {})
        confirmed = correlation_result.get('confirmed_issues', [])
        static_only = correlation_result.get('static_only_issues', [])
        dynamic_only = correlation_result.get('dynamic_only_issues', [])
        
        report = "# 静动态分析结果关联报告\n\n"
        
        # 总体统计
        report += "## 📊 总体统计\n\n"
        report += f"- **总问题数**: {stats.get('total_issues', 0)}\n"
        report += f"- **动态确认问题**: {stats.get('confirmed_count', 0)}\n"
        report += f"- **仅静态发现**: {stats.get('static_only_count', 0)}\n"
        report += f"- **仅动态发现**: {stats.get('dynamic_only_count', 0)}\n"
        report += f"- **确认率**: {stats.get('confirmation_rate', 0):.2%}\n"
        report += f"- **静态遗漏率**: {stats.get('static_miss_rate', 0):.2%}\n\n"
        
        # 严重性分布
        report += "## 🚨 严重性分布\n\n"
        severity_dist = stats.get('severity_distribution', {})
        for severity, count in sorted(severity_dist.items(), key=lambda x: x[1], reverse=True):
            report += f"- **{severity}**: {count}\n"
        report += "\n"
        
        # 高置信度问题（动态确认）
        report += "## ✅ 高置信度问题（动态确认）\n\n"
        if confirmed:
            for i, issue in enumerate(confirmed[:10], 1):  # 只显示前10个
                report += f"### {i}. {issue.get('type', 'Unknown')}\n"
                report += f"- **文件**: {issue.get('file', 'N/A')}\n"
                report += f"- **行号**: {issue.get('line', 'N/A')}\n"
                report += f"- **严重性**: {issue.get('severity', 'N/A')}\n"
                report += f"- **置信度**: {issue.get('confidence', 0):.0%}\n"
                report += f"- **静态工具**: {issue.get('tool', 'N/A')}\n"
                report += f"- **动态工具**: {issue.get('dynamic_tool', 'N/A')}\n"
                report += f"- **描述**: {issue.get('message', 'N/A')}\n\n"
        else:
            report += "无\n\n"
        
        # 需要人工验证的问题（仅静态）
        report += "## ⚠️ 需要人工验证（仅静态发现）\n\n"
        if static_only:
            report += f"共 {len(static_only)} 个问题，建议人工审查以确认是否为误报。\n\n"
        else:
            report += "无\n\n"
        
        # 静态分析遗漏（仅动态）
        report += "## 🔍 静态分析遗漏（仅动态发现）\n\n"
        if dynamic_only:
            report += f"共 {len(dynamic_only)} 个问题，建议优化静态分析规则。\n\n"
            for i, issue in enumerate(dynamic_only[:5], 1):  # 只显示前5个
                report += f"### {i}. {issue.get('type', 'Unknown')}\n"
                report += f"- **文件**: {issue.get('file', 'N/A')}\n"
                report += f"- **行号**: {issue.get('line', 'N/A')}\n"
                report += f"- **动态工具**: {issue.get('tool', 'N/A')}\n\n"
        else:
            report += "无（静态分析覆盖完整）\n\n"
        
        return report
