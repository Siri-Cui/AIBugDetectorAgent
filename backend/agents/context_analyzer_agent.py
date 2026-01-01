# -*- coding: utf-8 -*-
"""上下文分析Agent
作用：分析C++代码的编译上下文，提供宏定义、条件编译、平台相关信息
依赖：base_agent、utils.logger、utils.code_parser
调用关系：被orchestrator调用，在文件分析后执行，为其他Agent提供上下文增强
"""
import sys, os
# 获取当前文件的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# backend 目录的上级路径（即项目根目录）
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import os
import re
from typing import Dict, List, Any, Set
from collections import defaultdict
from .base_agent import BaseAgent, AgentResponse, AgentStatus
from utils.logger import log_info, log_error



class ContextAnalyzerAgent(BaseAgent):
    """上下文分析Agent - 分析代码编译上下文和环境依赖"""
    
    def __init__(self):
        super().__init__(
            agent_id="context_001",
            name="ContextAnalyzerAgent"
        )
        
        # 常见平台宏定义
        self.platform_macros = {
            'windows': ['_WIN32', '_WIN64', 'WIN32', 'WIN64', '_WINDOWS'],
            'linux': ['__linux__', '__linux', 'linux', '__gnu_linux__'],
            'macos': ['__APPLE__', '__MACH__', '__OSX__'],
            'unix': ['__unix__', '__unix', 'unix'],
            'android': ['__ANDROID__', 'ANDROID']
        }
        
        # 常见编译器宏
        self.compiler_macros = {
            'gcc': ['__GNUC__', '__GNUG__'],
            'clang': ['__clang__'],
            'msvc': ['_MSC_VER', '_MSVC'],
            'mingw': ['__MINGW32__', '__MINGW64__']
        }
    
    def get_capabilities(self) -> List[str]:
        """返回Agent能力列表"""
        return [
            "macro_extraction",              # 宏定义提取
            "conditional_compilation_analysis",  # 条件编译分析
            "platform_detection",            # 平台检测
            "dependency_graph_building",     # 依赖图构建
            "compilation_context_analysis"   # 编译上下文分析
        ]
    
    async def process(self, task_data: Dict[str, Any]) -> AgentResponse:
        """处理上下文分析任务
        输入：task_data包含file_analysis结果（source_files、dependencies等）
        输出：编译上下文分析结果
        """
        try:
            self.set_status(AgentStatus.WORKING)
            log_info(f"{self.name} 开始分析代码上下文")
            
            file_analysis = task_data.get('file_analysis', {})
            source_files = file_analysis.get('source_files', [])
            dependencies = file_analysis.get('dependencies', {})
            
            if not source_files:
                return AgentResponse(
                    success=False,
                    message="未找到源文件",
                    errors=["source_files为空"]
                )
            
            # 执行上下文分析
            context_result = {
                # 1. 提取宏定义
                'macros': await self._extract_macros(source_files),
                
                # 2. 分析条件编译分支
                'conditional_branches': await self._analyze_conditional_branches(source_files),
                
                # 3. 识别平台相关代码
                'platform_info': await self._detect_platform_code(source_files),
                
                # 4. 分析编译器依赖
                'compiler_info': await self._detect_compiler_dependencies(source_files),
                
                # 5. 构建依赖关系图
                'dependency_graph': await self._build_dependency_graph(dependencies, source_files),
                
                # 6. 构建跨文件调用图（Iteration 5 需求）
                'call_graph': None,

                # 7. 统计信息
                'statistics': await self._generate_statistics(source_files)
            }
            
            self.set_status(AgentStatus.COMPLETED)
            log_info(f"{self.name} 完成上下文分析")
            
            # --- Iteration 5: 构建跨文件调用图并保存到 analysis 文件夹 ---
            try:
                from backend.tools.call_graph_builder import build_call_graph
                project_root = os.path.dirname(source_files[0]['path']) if source_files else None
                # 如果路径中包含 extracted，取其上级作为项目根目录
                if project_root and 'extracted' in project_root:
                    root_idx = project_root.find('extracted')
                    project_root = project_root[:root_idx + len('extracted')]
                call_graph_path = None
                if project_root:
                    outdir = os.path.join(project_root, 'analysis')
                    os.makedirs(outdir, exist_ok=True)
                    call_graph_path = os.path.join(outdir, 'call_graph.json')
                    graph = build_call_graph(project_root, out_path=call_graph_path)
                    context_result['call_graph'] = {
                        'path': call_graph_path,
                        'summary': {
                            'functions': len(graph.get('functions', {})),
                            'edges': len(graph.get('call_edges', []))
                        }
                    }
            except Exception as _e:
                log_error(f"构建调用图失败: {_e}")
            
            # --- Iteration 5: 数据流分析 ---
            try:
                from backend.tools.dataflow_analyzer import DataflowAnalyzer
                analyzer = DataflowAnalyzer(project_root)
                dataflow_result = analyzer.analyze_project()
                context_result['dataflow'] = {
                    "variables": list(dataflow_result["variables"].keys())[:10],  # 示例前10个变量名
                    "resource_warnings": dataflow_result["resources"]
                }
            except Exception as e:
                log_error(f"数据流分析失败: {e}")


            return AgentResponse(
                success=True,
                message="上下文分析完成",
                data=context_result
            )
            
        except Exception as e:
            self.set_status(AgentStatus.FAILED)
            log_error(f"{self.name} 分析失败: {str(e)}")
            return AgentResponse(
                success=False,
                message="上下文分析失败",
                errors=[str(e)]
            )
    
    async def _extract_macros(self, source_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """提取宏定义"""
        macros = {
            'defined': {},      # 定义的宏及其值
            'undefined': set(), # 未定义的宏
            'conditional': []   # 条件宏
        }
        
        # 宏定义正则表达式
        define_pattern = r'#define\s+(\w+)(?:\s+(.+))?'
        undef_pattern = r'#undef\s+(\w+)'
        ifdef_pattern = r'#ifdef\s+(\w+)'
        ifndef_pattern = r'#ifndef\s+(\w+)'
        
        for file in source_files:
            try:
                with open(file['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # 提取 #define
                for match in re.finditer(define_pattern, content):
                    macro_name = match.group(1)
                    macro_value = match.group(2).strip() if match.group(2) else ''
                    macros['defined'][macro_name] = macro_value
                
                # 提取 #undef
                for match in re.finditer(undef_pattern, content):
                    macros['undefined'].add(match.group(1))
                
                # 提取条件宏 (#ifdef, #ifndef)
                for match in re.finditer(ifdef_pattern, content):
                    macros['conditional'].append({
                        'macro': match.group(1),
                        'type': 'ifdef',
                        'file': file['name']
                    })
                
                for match in re.finditer(ifndef_pattern, content):
                    macros['conditional'].append({
                        'macro': match.group(1),
                        'type': 'ifndef',
                        'file': file['name']
                    })
                
            except Exception as e:
                log_error(f"提取宏定义失败 {file['path']}: {str(e)}")
        
        # 转换set为list用于JSON序列化
        macros['undefined'] = list(macros['undefined'])
        
        return macros
    
    async def _analyze_conditional_branches(self, source_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分析条件编译分支"""
        branches = []
        
        # 匹配 #if、#ifdef、#ifndef、#elif、#else、#endif
        conditional_pattern = r'#(if|ifdef|ifndef|elif|else|endif)(?:\s+(.+))?'
        
        for file in source_files:
            try:
                with open(file['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                
                branch_stack = []
                
                for line_num, line in enumerate(lines, 1):
                    match = re.search(conditional_pattern, line)
                    if match:
                        directive = match.group(1)
                        condition = match.group(2).strip() if match.group(2) else ''
                        
                        if directive in ['if', 'ifdef', 'ifndef']:
                            # 新的条件分支开始
                            branch_stack.append({
                                'file': file['name'],
                                'line': line_num,
                                'directive': directive,
                                'condition': condition,
                                'nested_level': len(branch_stack)
                            })
                        elif directive == 'endif':
                            # 条件分支结束
                            if branch_stack:
                                branch_info = branch_stack.pop()
                                branch_info['end_line'] = line_num
                                branches.append(branch_info)
                
            except Exception as e:
                log_error(f"分析条件编译失败 {file['path']}: {str(e)}")
        
        return branches
    
    async def _detect_platform_code(self, source_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """检测平台相关代码"""
        platform_info = {
            'detected_platforms': set(),
            'platform_specific_code': []
        }
        
        for file in source_files:
            try:
                with open(file['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # 检测每个平台的宏
                for platform, macros in self.platform_macros.items():
                    for macro in macros:
                        if re.search(rf'#ifdef\s+{macro}|#ifndef\s+{macro}|#if\s+defined\({macro}\)', content):
                            platform_info['detected_platforms'].add(platform)
                            platform_info['platform_specific_code'].append({
                                'file': file['name'],
                                'platform': platform,
                                'macro': macro
                            })
                
            except Exception as e:
                log_error(f"检测平台代码失败 {file['path']}: {str(e)}")
        
        platform_info['detected_platforms'] = list(platform_info['detected_platforms'])
        return platform_info
    
    async def _detect_compiler_dependencies(self, source_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """检测编译器依赖"""
        compiler_info = {
            'detected_compilers': set(),
            'compiler_specific_code': []
        }
        
        for file in source_files:
            try:
                with open(file['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # 检测编译器特定宏
                for compiler, macros in self.compiler_macros.items():
                    for macro in macros:
                        if re.search(rf'#ifdef\s+{macro}|#ifndef\s+{macro}|#if\s+defined\({macro}\)', content):
                            compiler_info['detected_compilers'].add(compiler)
                            compiler_info['compiler_specific_code'].append({
                                'file': file['name'],
                                'compiler': compiler,
                                'macro': macro
                            })
                
            except Exception as e:
                log_error(f"检测编译器依赖失败 {file['path']}: {str(e)}")
        
        compiler_info['detected_compilers'] = list(compiler_info['detected_compilers'])
        return compiler_info
    
    async def _build_dependency_graph(
        self, 
        dependencies: Dict[str, List[str]], 
        source_files: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """构建依赖关系图"""
        dependency_graph = {
            'nodes': [],        # 文件节点
            'edges': [],        # 依赖边
            'system_deps': dependencies.get('system_includes', []),
            'local_deps': dependencies.get('local_includes', [])
        }
        
        # 构建文件节点
        file_map = {}
        for idx, file in enumerate(source_files):
            node = {
                'id': idx,
                'name': file['name'],
                'path': file['relative_path'],
                'type': file.get('type', 'unknown')
            }
            dependency_graph['nodes'].append(node)
            file_map[file['name']] = idx
        
        # 构建依赖边
        for file in source_files:
            source_id = file_map.get(file['name'])
            if source_id is None:
                continue
            
            includes = file.get('includes', [])
            for include in includes:
                # 查找被包含的文件
                included_file = include.split('/')[-1]  # 取文件名
                target_id = file_map.get(included_file)
                
                if target_id is not None:
                    dependency_graph['edges'].append({
                        'source': source_id,
                        'target': target_id,
                        'include': include
                    })
        
        return dependency_graph
    
    async def _generate_statistics(self, source_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成统计信息"""
        stats = {
            'total_files': len(source_files),
            'file_types': defaultdict(int),
            'total_macro_usage': 0,
            'conditional_blocks': 0
        }
        
        for file in source_files:
            file_type = file.get('type', 'unknown')
            stats['file_types'][file_type] += 1
            
            try:
                with open(file['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # 统计宏使用
                stats['total_macro_usage'] += len(re.findall(r'#define', content))
                
                # 统计条件编译块
                stats['conditional_blocks'] += len(re.findall(r'#ifdef|#ifndef|#if', content))
                
            except Exception:
                pass
        
        stats['file_types'] = dict(stats['file_types'])
        return stats