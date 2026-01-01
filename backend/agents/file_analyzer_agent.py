"""文件结构分析Agent
作用：分析C++项目的文件结构，识别源文件、头文件等
依赖：base_agent、utils.code_parser、utils.logger
调用关系：被orchestrator调用，是分析流程的第一步
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Any
from .base_agent import BaseAgent, AgentResponse, AgentStatus
from utils.logger import log_info, log_error
from utils.code_parser import CodeParser


class FileAnalyzerAgent(BaseAgent):
    """文件结构分析Agent"""
    
    def __init__(self):
        super().__init__(
            agent_id="file_analyzer_001",
            name="FileAnalyzerAgent"
        )
        self.supported_extensions = ['.cpp', '.h', '.hpp', '.cc', '.cxx', '.c']
        self.code_parser = CodeParser()
    
    def get_capabilities(self) -> List[str]:
        """返回Agent能力列表"""
        return [
            "cpp_project_structure_analysis",  # C++项目结构分析
            "source_file_classification",     # 源文件分类
            "dependency_detection",           # 依赖检测
            "code_complexity_analysis"        # 代码复杂度分析
        ]
    
    async def process(self, task_data: Dict[str, Any]) -> AgentResponse:
        """处理文件分析任务
        输入：task_data包含project_path（项目路径）
        输出：项目结构分析结果
        """
        try:
            self.set_status(AgentStatus.WORKING)
            log_info(f"{self.name} 开始分析项目结构")
            
            project_path = task_data.get('project_path')
            if not project_path or not os.path.exists(project_path):
                return AgentResponse(
                    success=False,
                    message="项目路径无效",
                    errors=["项目路径不存在或无效"]
                )
            
            # 执行分析
            analysis_result = {
                'project_structure': await self._analyze_project_structure(project_path),
                'source_files': await self._classify_source_files(project_path),
                'dependencies': await self._detect_dependencies(project_path),
                'complexity_metrics': await self._analyze_complexity(project_path)
            }
            
            self.set_status(AgentStatus.COMPLETED)
            log_info(f"{self.name} 完成项目结构分析")
            
            return AgentResponse(
                success=True,
                message="项目结构分析完成",
                data=analysis_result
            )
            
        except Exception as e:
            self.set_status(AgentStatus.FAILED)
            log_error(f"{self.name} 分析失败: {str(e)}")
            return AgentResponse(
                success=False,
                message="项目结构分析失败",
                errors=[str(e)]
            )
    
    async def _analyze_project_structure(self, project_path: str) -> Dict[str, Any]:
        """分析项目目录结构"""
        structure = {
            'root_directory': project_path,
            'directories': [],
            'total_files': 0,
            'cpp_files': 0,
            'header_files': 0,
            'other_files': 0
        }
        
        for root, dirs, files in os.walk(project_path):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            rel_root = os.path.relpath(root, project_path)
            if rel_root != '.':
                structure['directories'].append(rel_root)
            
            for file in files:
                structure['total_files'] += 1
                ext = os.path.splitext(file)[1].lower()
                
                if ext in ['.cpp', '.cc', '.cxx', '.c']:
                    structure['cpp_files'] += 1
                elif ext in ['.h', '.hpp']:
                    structure['header_files'] += 1
                else:
                    structure['other_files'] += 1
        
        return structure
    
    async def _classify_source_files(self, project_path: str) -> List[Dict[str, Any]]:
        """分类源文件"""
        source_files = []
        
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.supported_extensions:
                    file_path = os.path.join(root, file)
                    file_info = {
                        'path': file_path,
                        'name': file,
                        'extension': ext,
                        'size': os.path.getsize(file_path),
                        'type': self._classify_file_type(file, ext),
                        'relative_path': os.path.relpath(file_path, project_path)
                    }
                    
                    # 分析文件内容
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            file_info.update({
                                'lines_of_code': len(content.splitlines()),
                                'includes': self._extract_includes(content),
                                'classes': self._extract_classes(content),
                                'functions': self._extract_functions(content)
                            })
                    except Exception:
                        log_error(f"读取文件失败: {file_path}")
                    
                    source_files.append(file_info)
        
        return source_files
    
    def _classify_file_type(self, filename: str, extension: str) -> str:
        """分类文件类型"""
        filename_lower = filename.lower()
        
        if extension in ['.h', '.hpp']:
            return 'header'
        elif extension in ['.cpp', '.cc', '.cxx']:
            if 'test' in filename_lower:
                return 'test'
            elif 'main' in filename_lower:
                return 'main'
            else:
                return 'implementation'
        elif extension == '.c':
            return 'c_source'
        else:
            return 'unknown'
    
    def _extract_includes(self, content: str) -> List[str]:
        """提取include语句"""
        include_pattern = r'#include\s*[<"](.*?)[>"]'
        return re.findall(include_pattern, content)
    
    def _extract_classes(self, content: str) -> List[str]:
        """提取类名"""
        class_pattern = r'class\s+(\w+)'
        return re.findall(class_pattern, content)
    
    def _extract_functions(self, content: str) -> List[str]:
        """提取函数名"""
        func_pattern = r'(\w+)\s*\([^)]*\)\s*{'
        return re.findall(func_pattern, content)
    
    async def _detect_dependencies(self, project_path: str) -> Dict[str, List[str]]:
        """检测项目依赖"""
        dependencies = {
            'system_includes': set(),
            'local_includes': set()
        }
        
        for root, dirs, files in os.walk(project_path):
            for file in files:
                if os.path.splitext(file)[1].lower() in self.supported_extensions:
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            
                        # 系统包含
                        system_includes = re.findall(r'#include\s*<(.*?)>', content)
                        dependencies['system_includes'].update(system_includes)
                        
                        # 本地包含
                        local_includes = re.findall(r'#include\s*"(.*?)"', content)
                        dependencies['local_includes'].update(local_includes)
                        
                    except Exception:
                        continue
        
        return {k: list(v) for k, v in dependencies.items()}
    
    async def _analyze_complexity(self, project_path: str) -> Dict[str, Any]:
        """分析代码复杂度"""
        metrics = {
            'total_lines': 0,
            'code_lines': 0,
            'comment_lines': 0,
            'blank_lines': 0,
            'cyclomatic_complexity': 0
        }
        
        for root, dirs, files in os.walk(project_path):
            for file in files:
                if os.path.splitext(file)[1].lower() in ['.cpp', '.cc', '.cxx', '.c']:
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()
                        
                        metrics['total_lines'] += len(lines)
                        
                        for line in lines:
                            stripped = line.strip()
                            if not stripped:
                                metrics['blank_lines'] += 1
                            elif stripped.startswith('//') or stripped.startswith('/*'):
                                metrics['comment_lines'] += 1
                            else:
                                metrics['code_lines'] += 1
                                
                                # 简化的圈复杂度计算
                                if any(keyword in stripped for keyword in ['if', 'while', 'for', 'switch', 'case']):
                                    metrics['cyclomatic_complexity'] += 1
                        
                    except Exception:
                        continue
        
        return metrics