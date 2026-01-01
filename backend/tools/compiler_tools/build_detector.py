# -*- coding: utf-8 -*-
"""
构建系统检测器
作用：识别项目使用的构建系统（CMake、Make等）
依赖：os、pathlib、utils.logger
调用关系：被dynamic_workflow和instrumented_builder调用
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from utils.logger import log_info, log_error, log_warning


class BuildDetector:
    """构建系统检测器"""
    def detect_cpp_standard(self, project_path: str) -> str:
        """
        智能检测项目所需的C++标准
        优先级: Makefile/CMakeLists.txt > 代码特征 > 默认c++17
        """
        project_path = Path(project_path)
        
        # 步骤1: 从构建文件提取
        for build_file in ['Makefile', 'makefile', 'CMakeLists.txt']:
            build_path = project_path / build_file
            if build_path.exists():
                try:
                    with open(build_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # 匹配 -std=c++20 或 CMAKE_CXX_STANDARD 20
                        patterns = [
                            r'-std=(?:gnu\+\+|c\+\+)(\d+)',
                            r'CMAKE_CXX_STANDARD\s+(\d+)',
                            r'set\(CMAKE_CXX_STANDARD\s+(\d+)\)'
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, content)
                            if match:
                                detected = f"c++{match.group(1)}"
                                log_info(f"✅ 从 {build_file} 检测到: {detected}")
                                return detected
                except:
                    pass
        
        # 步骤2: 代码特征推断
        cpp20_keywords = ['std::span', 'std::ranges', '<ranges>', '<span>']
        cpp17_keywords = ['std::optional', 'std::filesystem', '<optional>']
        
        try:
            source_files = list(project_path.rglob("*.cpp"))[:20] + list(project_path.rglob("*.hpp"))[:20]
            
            for src in source_files:
                try:
                    code = src.read_text(encoding='utf-8', errors='ignore')
                    if any(kw in code for kw in cpp20_keywords):
                        log_info(f"✅ 检测到C++20特性 in {src.name}")
                        return "c++20"
                    if any(kw in code for kw in cpp17_keywords):
                        return "c++17"
                except:
                    continue
        except:
            pass
        
        log_info("📌 使用默认: c++17")
        return "c++17"


    def detect_build_system(self, project_path: str) -> Dict[str, any]:
        """检测项目使用的构建系统"""
        project_path = Path(project_path)
        
        # ✅ 递归查找真正的项目根目录（有构建文件的目录）
        actual_project = self._find_project_root(project_path)
        if actual_project != project_path:
            log_info(f"🔍 找到实际项目根目录: {actual_project.relative_to(project_path)}")
            project_path = actual_project
        # 检测 Make
        for makefile in ['Makefile', 'makefile', 'GNUmakefile']:
            if (project_path / makefile).exists():
                log_info(f"✅ 检测到 make 构建系统: {makefile}")
                return {
                    'build_system': 'make',
                    'build_dir': None,
                    'config_files': [makefile],
                    'project_root': str(project_path)
                }
        # 检测 CMake
        if (project_path / 'CMakeLists.txt').exists():
            log_info("✅ 检测到 CMake 构建系统")
            return {
                'build_system': 'cmake',
                'build_dir': str(project_path / 'build'),
                'config_files': ['CMakeLists.txt'],
                'project_root': str(project_path)
            }
        
        # 未检测到
        log_warning("⚠️ 未检测到已知的构建系统")

        # 尝试自动生成 Makefile
        if self._can_auto_generate_makefile(project_path):
            makefile_path = self._auto_generate_makefile_wrapper(project_path)
            if makefile_path:
                return {
                    'build_system': 'make',
                    'build_dir': None,
                    'config_files': ['Makefile']
                }
        
        return {
            'build_system': None,
            'build_dir': None,
            'config_files': []
        }

    def _find_project_root(self, start_path: Path) -> Path:
        """递归查找包含构建文件的项目根目录"""
    
        # 排除的目录
        exclude_dirs = {'analysis', 'results', '__pycache__', '.git', 'build', 'obj', 'bin'}
        
        # 在当前目录查找
        if (start_path / 'Makefile').exists() or (start_path / 'CMakeLists.txt').exists():
            return start_path
        
        # 在子目录中递归查找（最多2层）
        for subdir in start_path.iterdir():
            if subdir.is_dir() and subdir.name not in exclude_dirs:
                if (subdir / 'Makefile').exists() or (subdir / 'CMakeLists.txt').exists():
                    return subdir
                
                # 再深入一层
                for sub_subdir in subdir.iterdir():
                    if sub_subdir.is_dir() and sub_subdir.name not in exclude_dirs:
                        if (sub_subdir / 'Makefile').exists() or (sub_subdir / 'CMakeLists.txt').exists():
                            return sub_subdir
    
        # 没找到，返回原路径
        return start_path
    
    def _can_auto_generate_makefile(self, project_path: Path) -> bool:
        """检查是否可以自动生成Makefile（是否有C++源文件）"""
        cpp_extensions = {'.cpp', '.cc', '.cxx', '.c'}
        
        for root, _, files in os.walk(project_path):
            for file in files:
                if any(file.endswith(ext) for ext in cpp_extensions):
                    return True
        
        return False
    
    def _auto_generate_makefile_wrapper(self, project_path: Path) -> Optional[str]:
        """自动生成Makefile的包装方法"""
        try:
            # 查找所有C++源文件
            cpp_files = self._find_all_cpp_files(str(project_path))
            
            if not cpp_files:
                log_error("未找到C++源文件")
                return None
            
            log_info(f"✅ 检测到 {len(cpp_files)} 个C++源文件，自动生成Makefile")
            
            # 智能选择测试入口文件（主动解决main函数问题）
            test_file = self._auto_select_test_file(cpp_files, str(project_path))
            
            # 收集需要编译的源文件
            source_files = self._collect_source_files(cpp_files, test_file, str(project_path))
            
            # 生成Makefile
            makefile_path = os.path.join(str(project_path), 'Makefile')
            self._auto_generate_makefile(makefile_path, test_file, str(project_path))
            
            return makefile_path
            
        except Exception as e:
            log_error(f"自动生成Makefile失败: {e}")
            return None
    
    def _find_all_cpp_files(self, project_path: str) -> List[str]:
        """查找所有C++源文件"""
        cpp_files = []
        cpp_extensions = {'.cpp', '.cc', '.cxx', '.c'}
        exclude_dirs = {'build', 'Build', '.git', '__pycache__'}
        
        for root, dirs, files in os.walk(project_path):
            # 过滤排除目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if any(file.endswith(ext) for ext in cpp_extensions):
                    cpp_files.append(os.path.join(root, file))
        
        return cpp_files
    
    def _auto_select_test_file(self, cpp_files: List[str], project_path: str) -> str:
        """智能选择测试入口文件 - 主动解决main函数问题"""
        priority_keywords = ['unittest', 'test', 'benchmark', 'main']
        
        # 策略1：在优先文件中查找未注释的main
        for keyword in priority_keywords:
            for file_path in cpp_files:
                basename = os.path.basename(file_path).lower()
                if keyword in basename:
                    if self._has_active_main(file_path):
                        rel_path = os.path.relpath(file_path, project_path)
                        log_info(f"✅ 选择测试入口: {rel_path}")
                        return file_path
        
        # 策略2：在所有文件中查找未注释的main
        log_warning("⚠️ 在测试文件中未找到main函数，扩大搜索范围...")
        for file_path in cpp_files:
            if self._has_active_main(file_path):
                rel_path = os.path.relpath(file_path, project_path)
                log_info(f"✅ 找到包含main的文件: {rel_path}")
                return file_path
        
        # 策略3：查找被注释的main并尝试取消注释
        log_info("🔧 查找被注释的main函数...")
        for keyword in priority_keywords:
            for file_path in cpp_files:
                basename = os.path.basename(file_path).lower()
                if keyword in basename and self._has_commented_main(file_path):
                    rel_path = os.path.relpath(file_path, project_path)
                    log_info(f"🔧 检测到被注释的main，尝试取消注释: {rel_path}")
                    
                    if self._try_uncomment_main(file_path):
                        log_info(f"✅ 成功取消注释: {rel_path}")
                        return file_path
        
        # 策略4：生成一个最小的main wrapper
        log_warning("⚠️ 未找到可用的main函数，生成默认测试入口")
        wrapper_file = self._generate_minimal_main_wrapper(project_path)
        return wrapper_file
    
    def _has_active_main(self, file_path: str) -> bool:
        """检查文件是否包含未注释的main函数"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 移除单行注释
            lines_no_comment = [line.split('//')[0] for line in content.split('\n')]
            content_no_comment = '\n'.join(lines_no_comment)
            
            # 检测main函数
            return 'int main' in content_no_comment or 'void main' in content_no_comment
        except:
            return False
    
    def _has_commented_main(self, file_path: str) -> bool:
        """检查文件是否包含被注释的main函数"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            return '//int main' in content or '// int main' in content
        except:
            return False
    
    def _try_uncomment_main(self, file_path: str) -> bool:
        """尝试取消main函数的注释"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            modified_lines = []
            in_main_function = False
            brace_count = 0
            
            for line in lines:
                stripped = line.lstrip()
                
                # 检测main函数开始
                if '//int main' in stripped or '// int main' in stripped:
                    # 移除注释符号
                    modified_line = line.replace('//', '', 1)
                    modified_lines.append(modified_line)
                    in_main_function = True
                    brace_count = 0
                    continue
                
                if in_main_function:
                    # 统计大括号
                    brace_count += line.count('{') - line.count('}')
                    
                    # 如果是注释行且在main函数内，取消注释
                    if stripped.startswith('//'):
                        modified_lines.append(line.replace('//', '', 1))
                    else:
                        modified_lines.append(line)
                    
                    # main函数结束
                    if brace_count <= 0 and '}' in line:
                        in_main_function = False
                else:
                    modified_lines.append(line)
            
            # 写回文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(modified_lines)
            
            return True
        except Exception as e:
            log_error(f"取消注释失败: {e}")
            return False
    
    def _generate_minimal_main_wrapper(self, project_path: str) -> str:
        """生成最小化的main wrapper"""
        wrapper_path = os.path.join(project_path, '_auto_main.cpp')
        
        wrapper_content = """// Auto-generated by AI Bug Detector
#include <iostream>

int main() {
    std::cout << "Auto-generated test entry point" << std::endl;
    std::cout << "Note: No active main function found in project" << std::endl;
    std::cout << "This is a minimal wrapper to allow compilation" << std::endl;
    return 0;
}
"""
        
        with open(wrapper_path, 'w', encoding='utf-8') as f:
            f.write(wrapper_content)
        
        log_info(f"✅ 已生成main wrapper: {wrapper_path}")
        return wrapper_path
    
    def _collect_source_files(self, all_cpp_files: List[str], test_file: str, project_path: str) -> List[str]:
        """收集需要编译的源文件（排除冲突的main）"""
        source_files = []
        test_file_basename = os.path.basename(test_file).lower()
        
        for cpp_file in all_cpp_files:
            basename = os.path.basename(cpp_file).lower()
            rel_path = os.path.relpath(cpp_file, project_path)
            
            # 始终包含测试入口文件
            if cpp_file == test_file:
                log_info(f"  ✅ 测试入口: {rel_path}")
                source_files.append(cpp_file)
                continue
            
            # 排除其他可能包含main的文件（防止符号冲突）
            if any(keyword in basename for keyword in ['main.cpp', 'benchmark']):
                # 检查是否真的有main
                if self._has_active_main(cpp_file):
                    log_info(f"  ⏭️  跳过（多main冲突）: {rel_path}")
                    continue
            
            # 包含其他实现文件
            log_info(f"  ✅ 实现文件: {rel_path}")
            source_files.append(cpp_file)
        
        return source_files

    def _generate_multi_target_makefile(
        self,
        makefile_path: str,
        main_files: List[str],
        project_path: str
    ) -> str:
        """生成多目标 Makefile（每个main独立编译）"""
        
        # 生成相对路径
        main_files_rel = [os.path.relpath(f, project_path) for f in main_files]
        
        # 生成目标名称列表
        targets = []
        for main_file in main_files:
            basename = os.path.splitext(os.path.basename(main_file))[0]
            target = f"test_{basename}"
            targets.append(target)
        
        # 生成include路径
        include_dirs = set()
        for main_file in main_files:
            source_dir = os.path.dirname(main_file)
            if source_dir:
                rel_dir = os.path.relpath(source_dir, project_path)
                include_dirs.add(rel_dir)
        
        include_flags = ' '.join([f'-I{d}' for d in sorted(include_dirs)] + ['-I.', '-I..'])
        
        TAB = '\t'
        
        content = f"""# Auto-generated Multi-Target Makefile
# Generated for: {os.path.basename(project_path)}
# Total programs: {len(main_files)}

CXX = g++
CXXFLAGS = -std=c++11 -g -Wall -Wextra -pthread {include_flags}
LDFLAGS = -pthread

# 允许外部追加额外标志（用于Sanitizer）
CXXFLAGS_EXTRA ?=
LDFLAGS_EXTRA ?=

# 所有目标
TARGETS = {' '.join(targets)}

all: $(TARGETS)

"""
        
        # 为每个 main 文件生成独立的编译规则
        for i, (main_file, target) in enumerate(zip(main_files_rel, targets)):
            content += f"""# 目标 {i+1}: {main_file}
{target}: {main_file}
{TAB}$(CXX) $(CXXFLAGS) $(CXXFLAGS_EXTRA) {main_file} -o {target} $(LDFLAGS) $(LDFLAGS_EXTRA)

"""
        
        content += f"""clean:
{TAB}rm -f $(TARGETS) *.o

.PHONY: all clean
"""
        
        with open(makefile_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log_info(f"✅ 多目标Makefile已生成: {makefile_path}")
        log_info(f"   📦 包含 {len(targets)} 个独立程序")
        
        return makefile_path

    def _auto_generate_makefile(self, makefile_path: str, test_file: str, project_path: str):
        """生成自适应Makefile - 支持多main函数和CXXFLAGS_EXTRA"""
        
        # ===== ✅ 新增：多main检测 =====
        all_cpp_files = self._find_all_cpp_files(project_path)
        
        main_files = []
        for source_file in all_cpp_files:
            if self._has_active_main(source_file):
                main_files.append(source_file)
                log_info(f"   🎯 发现主程序: {os.path.basename(source_file)}")
        
        # 如果检测到多个 main 函数，生成多目标 Makefile
        if len(main_files) > 1:
            log_info(f"   📦 检测到 {len(main_files)} 个独立程序，生成多目标Makefile")
            return self._generate_multi_target_makefile(
                makefile_path, main_files, project_path
            )
        # ===== 新增部分结束 =====
        
        # ===== 以下是原有逻辑（保持不变）=====
        # 收集所有源文件
        source_files = self._collect_source_files(all_cpp_files, test_file, project_path)
        
        # 生成相对路径
        sources_list = [os.path.relpath(f, project_path) for f in source_files]
        objects_list = [f.replace('.cpp', '.o').replace('.cc', '.o').replace('.cxx', '.o').replace('.c', '.o') 
                    for f in sources_list]
        
        # 格式化为多行
        sources_str = ' \\\n\t'.join(sources_list)
        objects_str = ' \\\n\t'.join(objects_list)
        
        # 生成include路径
        include_dirs = set()
        for source_file in source_files:
            source_dir = os.path.dirname(source_file)
            if source_dir:
                rel_dir = os.path.relpath(source_dir, project_path)
                include_dirs.add(rel_dir)
        
        include_flags = ' '.join([f'-I{d}' for d in sorted(include_dirs)] + ['-I.'])
        
        # 使用TAB字符
        TAB = '\t'
        
        # ===== ✅ 修改：添加 CXXFLAGS_EXTRA 和 LDFLAGS_EXTRA =====
        content = f"""# Auto-generated by AI Bug Detector
# Generated for: {os.path.basename(project_path)}
# Entry point: {os.path.relpath(test_file, project_path)}
# Total sources: {len(source_files)}

CXX = g++
CXXFLAGS = -std=c++11 -g -pthread {include_flags}
LDFLAGS = -pthread
TARGET = test_dynamic

# 允许外部追加额外标志（用于Sanitizer）
CXXFLAGS_EXTRA ?=
LDFLAGS_EXTRA ?=

# Source files
SOURCES = {sources_str}

# Object files
OBJECTS = {objects_str}

all: $(TARGET)

# Link all object files
$(TARGET): $(OBJECTS)
{TAB}$(CXX) -o $(TARGET) $(OBJECTS) $(LDFLAGS) $(LDFLAGS_EXTRA)

# Compile rules
%.o: %.cpp
{TAB}$(CXX) $(CXXFLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

%.o: %.cc
{TAB}$(CXX) $(CXXFLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

%.o: %.cxx
{TAB}$(CXX) $(CXXFLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

clean:
{TAB}@rm -f $(OBJECTS) $(TARGET)

.PHONY: all clean
"""
        
        with open(makefile_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log_info(f"✅ Makefile已生成: {makefile_path}")
        log_info(f"   📁 包含 {len(source_files)} 个源文件")
        log_info(f"   📂 包含目录: {include_flags}")
        
        # ===== ✅ 新增：返回路径 =====
        return makefile_path
        
    def _find_executables(self, project_path: str, build_dir: str = None) -> List[str]:
        """查找编译生成的可执行文件"""
        executables = []
        search_dirs = [project_path]
        
        if build_dir and os.path.exists(build_dir):
            search_dirs.append(build_dir)
        
        for search_dir in search_dirs:
            for file in os.listdir(search_dir):
                file_path = os.path.join(search_dir, file)
                
                # 检查是否为可执行文件
                if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                    # 排除明显不是可执行程序的文件
                    if not file.endswith(('.o', '.so', '.a', '.sh', '.py')):
                        executables.append(file_path)
        
        return executables
