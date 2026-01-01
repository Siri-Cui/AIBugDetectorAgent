"""数据验证器
作用：验证分析相关的数据格式和内容
依赖：typing、utils.logger
调用关系：被各个Agent和服务调用
"""
import os
import re
from typing import Dict, List, Any, Optional, Union
from utils.logger import log_info, log_error


class ProjectValidator:
    """项目验证器"""
    
    def __init__(self):
        self.supported_extensions = ['.cpp', '.h', '.hpp', '.cc', '.cxx', '.c']
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        
    def validate_project_path(self, project_path: str) -> Dict[str, Any]:
        """验证项目路径
        输入：项目路径
        输出：验证结果
        """
        result = {
            'valid': False,
            'errors': [],
            'warnings': []
        }
        
        # 检查路径是否存在
        if not os.path.exists(project_path):
            result['errors'].append('项目路径不存在')
            return result
        
        # 检查是否为目录
        if not os.path.isdir(project_path):
            result['errors'].append('项目路径不是目录')
            return result
        
        # 检查是否包含C++文件
        cpp_files = self._find_cpp_files(project_path)
        if not cpp_files:
            result['warnings'].append('未找到C++源文件')
        
        # 检查文件大小
        large_files = self._check_file_sizes(project_path)
        if large_files:
            result['warnings'].append(f'发现{len(large_files)}个大文件，可能影响分析性能')
        
        result['valid'] = len(result['errors']) == 0
        return result
    
    def validate_analysis_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """验证分析配置"""
        result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # 检查必需配置项
        if 'project_path' not in config:
            result['errors'].append('缺少project_path配置')
        
        # 检查工具配置
        if 'enable_cppcheck' in config and not isinstance(config['enable_cppcheck'], bool):
            result['errors'].append('enable_cppcheck必须是布尔值')
        
        result['valid'] = len(result['errors']) == 0
        return result
    
    def _find_cpp_files(self, project_path: str) -> List[str]:
        """查找C++文件"""
        cpp_files = []
        
        for root, dirs, files in os.walk(project_path):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                if any(file.endswith(ext) for ext in self.supported_extensions):
                    cpp_files.append(os.path.join(root, file))
        
        return cpp_files
    
    def _check_file_sizes(self, project_path: str) -> List[str]:
        """检查大文件"""
        large_files = []
        
        for root, dirs, files in os.walk(project_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    if os.path.getsize(file_path) > self.max_file_size:
                        large_files.append(file_path)
                except:
                    continue
        
        return large_files


class AnalysisResultValidator:
    """分析结果验证器"""
    
    def validate_agent_response(self, response: Dict[str, Any]) -> bool:
        """验证Agent响应格式"""
        required_fields = ['success', 'message']
        
        for field in required_fields:
            if field not in response:
                log_error(f"Agent响应缺少字段: {field}")
                return False
        
        if not isinstance(response['success'], bool):
            log_error("Agent响应success字段必须是布尔值")
            return False
        
        return True
    
    def validate_issue_format(self, issue: Dict[str, Any]) -> bool:
        """验证问题格式"""
        required_fields = ['file', 'line', 'severity', 'message', 'tool']
        
        for field in required_fields:
            if field not in issue:
                log_error(f"问题记录缺少字段: {field}")
                return False
        
        # 验证严重程度
        valid_severities = ['high', 'medium', 'low', 'info']
        if issue['severity'] not in valid_severities:
            log_error(f"无效的严重程度: {issue['severity']}")
            return False
        
        return True
    
    def validate_analysis_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """验证分析报告"""
        result = {
            'valid': True,
            'errors': []
        }
        
        # 检查必需字段
        required_sections = ['summary', 'file_analysis', 'issues']
        
        for section in required_sections:
            if section not in report:
                result['errors'].append(f'报告缺少{section}部分')
        
        # 验证摘要部分
        if 'summary' in report:
            summary = report['summary']
            if 'total_issues' not in summary:
                result['errors'].append('摘要缺少total_issues')
            elif not isinstance(summary['total_issues'], int):
                result['errors'].append('total_issues必须是整数')
        
        # 验证问题列表
        if 'issues' in report:
            issues = report['issues']
            if not isinstance(issues, list):
                result['errors'].append('issues必须是列表')
            else:
                for i, issue in enumerate(issues):
                    if not self.validate_issue_format(issue):
                        result['errors'].append(f'第{i+1}个问题格式无效')
        
        result['valid'] = len(result['errors']) == 0
        return result


class ConfigValidator:
    """配置验证器"""
    
    def validate_api_key(self, api_key: str) -> bool:
        """验证API密钥格式"""
        if not api_key:
            return False
        
        # GLM-4 API密钥格式验证
        if not re.match(r'^[a-f0-9]{32}\.[a-zA-Z0-9]{16}$', api_key):
            log_error("GLM-4 API密钥格式无效")
            return False
        
        return True
    
    def validate_paths(self, paths: Dict[str, str]) -> Dict[str, Any]:
        """验证路径配置"""
        result = {
            'valid': True,
            'errors': []
        }
        
        for path_name, path_value in paths.items():
            if not path_value:
                result['errors'].append(f'{path_name}路径为空')
                continue
            
            # 检查目录路径
            if path_name.endswith('_DIR'):
                parent_dir = os.path.dirname(path_value)
                if parent_dir and not os.path.exists(parent_dir):
                    result['errors'].append(f'{path_name}的父目录不存在: {parent_dir}')
        
        result['valid'] = len(result['errors']) == 0
        return result