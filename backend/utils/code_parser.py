"""代码解析工具
作用：解析C++代码，提取语法结构信息
依赖：re、utils.logger
调用关系：被FileAnalyzerAgent调用
"""
import re
from typing import Dict, List, Any, Optional
from utils.logger import log_info, log_error


class CodeParser:
    """代码解析工具"""
    
    def __init__(self):
        # C++关键字
        self.cpp_keywords = [
            'class', 'struct', 'namespace', 'template', 'typedef',
            'public', 'private', 'protected', 'virtual', 'static',
            'const', 'inline', 'friend', 'operator'
        ]
    
    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """解析单个文件
        输入：文件路径
        输出：文件解析结果
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            return {
                'file_path': file_path,
                'lines_of_code': len(content.splitlines()),
                'includes': self.extract_includes(content),
                'classes': self.extract_classes(content),
                'functions': self.extract_functions(content),
                'namespaces': self.extract_namespaces(content),
                'complexity_score': self.calculate_complexity(content)
            }
            
        except Exception as e:
            log_error(f"解析文件失败 {file_path}: {str(e)}")
            return {
                'file_path': file_path,
                'error': str(e)
            }
    def extract_includes(self, content: str) -> List[str]:
        """提取include语句"""
        include_pattern = r'#include\s*[<"](.*?)[>"]'
        return re.findall(include_pattern, content)
    
    def extract_classes(self, content: str) -> List[Dict[str, Any]]:
        """提取类定义"""
        classes = []
        class_pattern = r'class\s+(\w+)(?:\s*:\s*(?:public|private|protected)\s+\w+)?'
        
        for match in re.finditer(class_pattern, content):
            class_name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            classes.append({
                'name': class_name,
                'line': line_num,
                'type': 'class'
            })
        
        return classes
    
    def extract_functions(self, content: str) -> List[Dict[str, Any]]:
        """提取函数定义"""
        functions = []
        # 简化的函数匹配模式
        func_pattern = r'(\w+)\s+(\w+)\s*\([^)]*\)\s*{'
        
        for match in re.finditer(func_pattern, content):
            return_type = match.group(1)
            func_name = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            # 跳过一些C++关键字
            if return_type not in self.cpp_keywords:
                functions.append({
                    'name': func_name,
                    'return_type': return_type,
                    'line': line_num
                })
        
        return functions
    
    def extract_namespaces(self, content: str) -> List[str]:
        """提取命名空间"""
        namespace_pattern = r'namespace\s+(\w+)'
        return re.findall(namespace_pattern, content)
    
    def calculate_complexity(self, content: str) -> int:
        """计算代码复杂度"""
        complexity = 0
        
        # 控制流关键字
        control_keywords = ['if', 'else', 'while', 'for', 'switch', 'case', 'catch']
        
        for keyword in control_keywords:
            complexity += len(re.findall(rf'\b{keyword}\b', content))
        
        return complexity
    
    def get_file_metrics(self, file_path: str) -> Dict[str, Any]:
        """获取文件度量信息"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            total_lines = len(lines)
            code_lines = 0
            comment_lines = 0
            blank_lines = 0
            
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    blank_lines += 1
                elif stripped.startswith('//') or stripped.startswith('/*'):
                    comment_lines += 1
                else:
                    code_lines += 1
            
            return {
                'total_lines': total_lines,
                'code_lines': code_lines,
                'comment_lines': comment_lines,
                'blank_lines': blank_lines,
                'comment_ratio': comment_lines / total_lines if total_lines > 0 else 0
            }
            
        except Exception as e:
            log_error(f"获取文件度量失败 {file_path}: {str(e)}")
            return {
                'total_lines': 0,
                'code_lines': 0,
                'comment_lines': 0,
                'blank_lines': 0,
                'comment_ratio': 0,
                'error': str(e)
            }  