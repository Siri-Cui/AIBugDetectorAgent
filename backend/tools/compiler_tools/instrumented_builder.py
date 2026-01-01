# -*- coding: utf-8 -*-
"""
插桩编译器
作用：为项目添加Sanitizer编译选项并重新编译
依赖：subprocess、build_detector、utils.logger
调用关系：被dynamic_workflow调用
"""
import os
import subprocess
import shutil
from typing import Dict, List, Any, Optional
from .build_detector import BuildDetector
from utils.logger import log_info, log_error, log_warning


class InstrumentedBuilder:
    """插桩编译器"""

    def __init__(self):
        self.build_detector = BuildDetector()
        self.supported_compilers = ['g++', 'gcc', 'clang++', 'clang']

    def _adapt_cpp_standard_for_compiler(self, detected_std: str) -> str:
        """
        适配编译器版本（GCC 9 及更早版本不支持 -std=c++20，需要使用 c++2a）
        """
        if not detected_std or not isinstance(detected_std, str):
            log_warning(f"⚠️  检测到无效的 C++ 标准: {detected_std}，使用默认 c++17")
            return "c++17"        
        if detected_std != "c++20":
            return detected_std  # 只处理 c++20 的情况
        
        try:
            import subprocess
            import re
            
            result = subprocess.run(
                ['g++', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return detected_std
            
            # 解析 GCC 版本号
            version_match = re.search(r'g\+\+.*?(\d+)\.(\d+)', result.stdout)
            if version_match:
                major = int(version_match.group(1))
                
                # GCC 10+ 支持 c++20，GCC 9 需要使用 c++2a
                if major < 10:
                    log_warning(f"⚠️  检测到 GCC {major}.x，不支持 -std=c++20，转换为 -std=c++2a")
                    return "c++2a"
                
                # GCC 8 及以下不支持任何 C++20 特性
                if major < 8:
                    log_error(f"❌ GCC {major}.x 不支持 C++20 特性，降级为 c++17")
                    return "c++17"
            
            return detected_std
            
        except Exception as e:
            log_warning(f"⚠️  编译器版本检测失败: {e}，保持原始标准: {detected_std}")
            return detected_std

    async def build_with_sanitizers(
        self,
        project_path: str,
        sanitizers: List[str],
        build_dir: str = None,
        clean_build: bool = True
    ) -> Dict[str, Any]:
        """使用Sanitizer重新编译项目（按不同sanitizer产出不同后缀的可执行文件）"""
        try:
            log_info(f"开始插桩编译，Sanitizers: {sanitizers}")

            # 检测构建系统
            build_info = self.build_detector.detect_build_system(project_path)

            if not build_info.get('build_system'):
                log_warning("未检测到标准构建系统，尝试自动生成Makefile")
                return await self._build_with_generated_makefile(
                    project_path, sanitizers, clean_build
                )

            build_system = build_info['build_system']

            # ✅ 使用 project_root（避免在 extracted 子目录内找不到文件）
            actual_project_path = build_info.get('project_root', project_path)
            build_dir = build_dir or build_info.get('build_dir') or os.path.join(actual_project_path, 'build_sanitized')

            # 生成Sanitizer编译标志
            sanitizer_flags = self._generate_sanitizer_flags(sanitizers)

            if build_system == 'cmake':
                result = await self._build_cmake_with_sanitizers(
                    actual_project_path, build_dir, sanitizer_flags, clean_build
                )
            elif build_system == 'make':
                # 对于已有 Makefile 的项目，我们尝试通过 EXTRA flags 注入
                result = await self._build_make_with_sanitizers(
                    actual_project_path, sanitizer_flags, clean_build
                )
            else:
                return {
                    'success': False,
                    'error': f'暂不支持的构建系统: {build_system}'
                }

            # 查找编译后的可执行文件
            if result.get('success'):
                if not result.get('executables'):
                    executables = self.build_detector._find_executables(actual_project_path, build_dir)
                    result['executables'] = executables
                    log_info(f"编译完成，找到 {len(executables)} 个可执行文件")
                else:
                    log_info(f"编译完成，找到 {len(result['executables'])} 个可执行文件（来自编译器）")

            return result

        except Exception as e:
            log_error(f"插桩编译失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _generate_sanitizer_flags(self, sanitizers: List[str]) -> str:
        """生成Sanitizer编译标志"""
        valid_sanitizers = []
        for san in sanitizers:
            if san in ['address', 'undefined', 'thread', 'leak', 'memory']:
                valid_sanitizers.append(san)

        if not valid_sanitizers:
            return ''

        # 注意：TSan 不能与 ASan/Leak 同时使用
        if 'thread' in valid_sanitizers and ('address' in valid_sanitizers or 'leak' in valid_sanitizers):
            log_warning("ThreadSanitizer不能与AddressSanitizer/LeakSanitizer同时使用，移除 thread")
            valid_sanitizers = [s for s in valid_sanitizers if s != 'thread']

        flags = f"-fsanitize={','.join(valid_sanitizers)} -fno-omit-frame-pointer -g -O1"
        log_info(f"生成编译标志: {flags}")
        return flags

    def _safe_decode_output(self, byte_output: bytes) -> str:
        """安全解码subprocess输出"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
        for encoding in encodings:
            try:
                return byte_output.decode(encoding)
            except (UnicodeDecodeError, AttributeError):
                continue
        return byte_output.decode('utf-8', errors='replace')

    async def _build_cmake_with_sanitizers(
        self,
        project_path: str,
        build_dir: str,
        sanitizer_flags: str,
        clean_build: bool
    ) -> Dict[str, Any]:
        """使用CMake编译（带Sanitizer）"""
        try:
            os.makedirs(build_dir, exist_ok=True)

            if clean_build and os.path.exists(os.path.join(build_dir, 'CMakeCache.txt')):
                log_info("清理旧的CMake构建")
                shutil.rmtree(build_dir)
                os.makedirs(build_dir)

            cmake_args = [
                'cmake', project_path,
                f'-DCMAKE_CXX_FLAGS={sanitizer_flags}',
                f'-DCMAKE_C_FLAGS={sanitizer_flags}',
                f'-DCMAKE_EXE_LINKER_FLAGS={sanitizer_flags}',
                '-DCMAKE_BUILD_TYPE=Debug'
            ]

            log_info(f"执行CMake配置: {' '.join(cmake_args)}")

            configure_result = subprocess.run(cmake_args, cwd=build_dir, capture_output=True, timeout=300)
            stdout = self._safe_decode_output(configure_result.stdout)
            stderr = self._safe_decode_output(configure_result.stderr)

            if configure_result.returncode != 0:
                log_error(f"CMake配置失败:\n{stderr}")
                return {'success': False, 'error': 'CMake配置失败', 'stdout': stdout, 'stderr': stderr}

            build_args = ['cmake', '--build', '.', '--', '-j4']
            log_info("开始编译...")

            build_result = subprocess.run(build_args, cwd=build_dir, capture_output=True, timeout=600)
            stdout = self._safe_decode_output(build_result.stdout)
            stderr = self._safe_decode_output(build_result.stderr)

            if build_result.returncode != 0:
                log_error(f"编译失败:\n{stderr}")
                return {'success': False, 'error': '编译失败', 'stdout': stdout, 'stderr': stderr}

            log_info("CMake编译成功")
            # CMake 产物位置不固定，交给 _find_executables 兜底
            return {'success': True, 'build_system': 'cmake', 'build_dir': build_dir, 'stdout': stdout, 'stderr': stderr}

        except subprocess.TimeoutExpired:
            log_error("CMake编译超时")
            return {'success': False, 'error': '编译超时'}
        except Exception as e:
            log_error(f"CMake编译异常: {e}")
            return {'success': False, 'error': str(e)}



    async def _build_make_with_sanitizers(
        self,
        project_path: str,
        sanitizer_flags: str,
        clean_build: bool
    ) -> Dict[str, Any]:
        """使用已有 Makefile 编译（若不支持多变体或硬编码sanitize则回退到生成Makefile）"""
        try:
            # ... (此方法开始部分的逻辑不变) ...

            # 读取 Makefile 内容判断是否需要回退
            with open(makefile_path, 'r', encoding='utf-8', errors='ignore') as mf:
                content = mf.read()
            
            # 🔥🔥🔥 修正点1: 检查是否是 Juliet 生成的 Makefile 🔥🔥🔥
            # 通过判断内容是否包含我们模板中的特定字符串
            is_juliet_generated_makefile = ('# Auto-generated Makefile for Juliet Test Case:' in content)

            hardcoded_sanitize = ('-fsanitize=' in content)
            
            # 原始逻辑是检查 'OUT_SUFFIX' 或 'test_dynamic$(OUT_SUFFIX)'
            # 但我们 Juliet 生成的 Makefile 现在是：
            # OUT_SUFFIX ?= 
            # BIN_NAME = test_dynamic$(OUT_SUFFIX)
            # 所以，判断它是否支持 OUT_SUFFIX 的最佳方式就是检测 BIN_NAME 和 OUT_SUFFIX 变量
            supports_out_suffix_vars = ('BIN_NAME ?=' in content) and ('OUT_SUFFIX ?=' in content)
            
            # 🔥🔥🔥 修正点2: 调整回退逻辑 🔥🔥🔥
            # 如果是 Juliet 生成的 Makefile (is_juliet_generated_makefile为True)，我们就直接使用它，不回退
            # 如果不是 Juliet 生成的，但它又硬编码了Sanitizer或者不支持OUT_SUFFIX，才回退
            if not is_juliet_generated_makefile and (hardcoded_sanitize or not supports_out_suffix_vars):
                log_warning("⚠️ 当前 Makefile 不适合注入多变体："
                            f"hardcoded_sanitize={hardcoded_sanitize}, supports_out_suffix_vars={supports_out_suffix_vars}")
                log_warning("↪ 回退到自动生成 Makefile.sanitizer（支持 OUT_SUFFIX）")
                sanitizers = []
                if '-fsanitize=' in sanitizer_flags:
                    san_str = sanitizer_flags.split('=')[1].split()[0]
                    sanitizers = san_str.split(',')
                return await self._build_with_generated_makefile(project_path, sanitizers, clean_build)

            # 🔥🔥🔥 修正点3: 如果是 Juliet 生成的 Makefile，或者是一个适配的 Makefile，那么直接在这里编译 🔥🔥🔥
            log_info("✅ 使用适配的 Makefile (或 Juliet 生成的 Makefile) 进行编译")

            if clean_build:
                log_info("执行 make clean")
                # 运行 make clean，确保清理掉旧的可执行文件
                subprocess.run(['make', 'clean'], cwd=project_path, capture_output=True, timeout=60)
            
            # 确定最终的可执行文件名称前缀
            # 从 Makefile 中提取原始的 {executable_name}，即不带 $(OUT_SUFFIX) 的部分
            juliet_base_executable_name = "test_dynamic" # 默认值，以防解析失败
            match = re.search(r'BIN_NAME\s*=\s*([^\s$]+)', content) # 匹配 BIN_NAME = xxx
            if match:
                juliet_base_executable_name = match.group(1).strip()
            
            # 根据 sanitizer 决定 OUT_SUFFIX 的值
            if not sanitizer_flags:
                out_suffix_val = '_vg'
            elif 'thread' in sanitizer_flags:
                out_suffix_val = '_tsan'
            else:
                out_suffix_val = '_asan' # 默认ASan/UBSan共用
            
            # 最终的产物文件名（例如：CWE121..._01_vg, test_dynamic_asan）
            final_exe_name = f"{juliet_base_executable_name}{out_suffix_val}"

            # 组装 make 命令
            make_cmd = [
                'make', '-j4',
                f'OUT_SUFFIX={out_suffix_val}', # 传递 OUT_SUFFIX
                f'CXXFLAGS_EXTRA={sanitizer_flags}', # 传递 Sanitizer 标志给 CXXFLAGS_EXTRA
                f'LDFLAGS_EXTRA={sanitizer_flags}', # 传递 Sanitizer 标志给 LDFLAGS_EXTRA
                f'BIN_NAME={final_exe_name}', # 🔥🔥🔥 修正点4: 传递 BIN_NAME，确保 Makefile 生成指定名称的二进制文件 🔥🔥🔥
                'CXX=g++', # 确保使用 g++ 编译
                'CC=gcc'   # 确保使用 gcc 编译 (C文件)
            ]

            log_info(f"执行编译命令: {' '.join(make_cmd)}")

            build_result = subprocess.run(
                make_cmd,
                cwd=project_path,
                capture_output=True,
                timeout=600 # 增加超时时间
            )

            stdout = self._safe_decode_output(build_result.stdout)
            stderr = self._safe_decode_output(build_result.stderr)

            if build_result.returncode != 0:
                log_error(f"Make编译失败:\n{stderr}")
                return {'success': False, 'error': 'Make编译失败', 'stdout': stdout, 'stderr': stderr}

            log_info("Make编译成功")
            
            # 🔥🔥🔥 修正点5: 明确返回刚刚编译出的可执行文件 🔥🔥🔥
            executables = [os.path.abspath(os.path.join(project_path, final_exe_name))]
            
            # 检查这个文件是否真的存在且可执行
            if not os.path.exists(executables[0]) or not os.access(executables[0], os.X_OK):
                log_error(f"编译成功但未找到预期的可执行文件：{executables[0]}。尝试通用查找。")
                executables = self._find_compiled_executables(project_path) # 兜底查找
            
            return {
                'success': True,
                'build_system': 'make',
                'build_dir': project_path,
                'executables': executables,
                'stdout': stdout,
                'stderr': stderr
            }

        except subprocess.TimeoutExpired:
            log_error("Make编译超时")
            return {'success': False, 'error': '编译超时'}
        except Exception as e:
            log_error(f"Make编译异常: {e}")
            import traceback
            log_error(traceback.format_exc())
            return {'success': False, 'error': str(e)}


    async def _build_with_generated_makefile(
        self,
        project_path: str,
        sanitizers: List[str],
        clean_build: bool
    ) -> Dict[str, Any]:
        """自动生成 Makefile 并编译（智能识别单一/多目标项目）"""
        try:
            log_info("自动生成Makefile...")
            cpp_standard = self.build_detector.detect_cpp_standard(project_path)
            cpp_standard = self._adapt_cpp_standard_for_compiler(cpp_standard)  # ← 新增这一行
            log_info(f"📌 将使用C++标准: {cpp_standard}")
             # 🆕 检查系统依赖
            missing_deps = self._check_system_dependencies(project_path)
            if missing_deps:
                log_warning(f"⚠️  缺少系统依赖: {', '.join(missing_deps)}")
                log_warning(f"   建议安装: sudo apt-get install {' '.join(missing_deps)}")


            # 🆕 新增:从原生Makefile提取依赖
            extra_flags = self._extract_dependencies_from_makefile(project_path)
            log_info(f"📦 从原Makefile提取依赖: {extra_flags}")
            source_files = self._find_source_files(project_path)

            if not source_files:
                return {'success': False, 'error': '未找到C/C++源文件'}

            log_info(f"找到 {len(source_files)} 个源文件")
            
            # ===== 🔍 核心修改1：检测多 main 情况 =====
            main_files = []
            for src in source_files:
                src_path = os.path.join(project_path, src)
                if self._has_main_function(src_path):
                    main_files.append(src_path)
                    log_info(f"   🎯 发现main函数: {src}")
            
            # 根据 main 函数数量选择生成策略
            if len(main_files) > 1:
                log_info(f"   📦 检测到 {len(main_files)} 个独立程序，生成多目标Makefile")
                return await self._build_multi_target_with_sanitizers(
                    project_path, main_files, sanitizers, clean_build, cpp_standard  
                )
            else:
                log_info("   📦 检测到单一程序，生成标准Makefile")
            # ===== 检测结束 =====
            sanitizer_flags = self._generate_sanitizer_flags(sanitizers)

            # 根据 sanitizer 决定输出后缀
            if not sanitizers:
                out_suffix = "_vg"
            elif len(sanitizers) == 1 and sanitizers[0] == 'thread':
                out_suffix = "_tsan"
            else:
                out_suffix = "_asan"

            makefile_path = os.path.join(project_path, 'Makefile.sanitizer')
            makefile_content = self._generate_makefile_template_with_suffix(source_files, cpp_standard, extra_flags)

            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(makefile_content)

            log_info(f"Makefile已生成: {makefile_path}")

            # 简单校验 Makefile（主要是 TAB）
            with open(makefile_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if '\t' not in content:
                    return {'success': False, 'error': 'Makefile生成错误：缺少TAB字符'}

            # 语法 dry-run
            validate_result = subprocess.run(
                ['make', '-n', '-f', makefile_path, f'OUT_SUFFIX={out_suffix}'],
                cwd=project_path, capture_output=True, timeout=10
            )
            if validate_result.returncode != 0:
                stderr = self._safe_decode_output(validate_result.stderr)
                log_error(f"Makefile语法错误:\n{stderr}")
                return {'success': False, 'error': 'Makefile语法错误', 'stderr': stderr}

            # 清理
            if clean_build:
                subprocess.run(
                    ['make', '-f', makefile_path, 'clean'],
                    cwd=project_path, capture_output=True, timeout=30
                )

            # 真正构建当前 sanitizer 对应的后缀版本
            build_cmd = [
                'make', '-f', makefile_path, '-j4', '-k',
                f'OUT_SUFFIX={out_suffix}',
                f'CXXFLAGS_EXTRA={sanitizer_flags}',
                f'LDFLAGS_EXTRA={sanitizer_flags}',
            ]
            log_info(f"执行编译命令: {' '.join(build_cmd)}")

            build_result = subprocess.run(build_cmd, cwd=project_path, capture_output=True, timeout=600)
            stdout = self._safe_decode_output(build_result.stdout)
            stderr = self._safe_decode_output(build_result.stderr)

            if build_result.returncode != 0:
                log_error(f"编译失败:\n{stderr}")
                return {'success': False, 'error': '编译失败', 'stdout': stdout, 'stderr': stderr}

            # 产物名与模板一致：test_dynamic{OUT_SUFFIX}
            exe_name = f"test_dynamic{out_suffix}"
            exe_path = os.path.join(project_path, exe_name)
        

            # ===== 新增：收集所有 test_dynamic* 可执行文件，返回绝对路径列表 =====
            executables = []
            try:
                for fname in os.listdir(project_path):
                    fpath = os.path.join(project_path, fname)
                    # 只收集文件且可执行且名字以 test_dynamic 开头
                    if os.path.isfile(fpath) and os.access(fpath, os.X_OK) and fname.startswith('test_dynamic'):
                        executables.append(os.path.abspath(fpath))
                        log_info(f"   🎯 找到可执行文件: {os.path.abspath(fpath)}")
            except Exception as e:
                log_warning(f"收集可执行文件失败: {e}")

            # 兜底：如果找不到上述模式，但 exe_path 存在则加入
            if not executables and exe_path and os.path.exists(exe_path) and os.access(exe_path, os.X_OK):
                executables.append(os.path.abspath(exe_path))
                log_info(f"   🎯 发现构建产物: {os.path.abspath(exe_path)}")

            # 仍然没有时，调用已有的兜底查找
            if not executables:
                executables = self._find_compiled_executables(project_path)

            return {
                'success': True,
                'build_system': 'generated_makefile',
                'build_dir': project_path,
                'makefile_path': makefile_path,
                'executables': executables,
                'stdout': stdout,
                'stderr': stderr
            }

        except Exception as e:
            log_error(f"生成Makefile编译失败: {e}")
            return {'success': False, 'error': str(e)}

    def _find_source_files(self, project_path: str) -> List[str]:
        """递归查找C/C++源文件"""
        source_files = []
        extensions = {'.cpp', '.cc', '.cxx', '.c'}
        exclude_dirs = {
            'build', 'Build', 'cmake-build-debug', 'cmake-build-release',
            '.git', '__pycache__', '.vs', 'Debug', 'Release', 'x64', 'Win32', 'obj', '.obj'
        }

        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if any(file.endswith(ext) for ext in extensions) and not file.endswith('.obj'):
                    source_files.append(os.path.relpath(os.path.join(root, file), project_path))

        return source_files



    async def _build_multi_target_with_sanitizers(
        self,
        project_path: str,
        main_files: List[str],
        sanitizers: List[str],
        clean_build: bool,
        cpp_standard: str = "c++17"  # 🆕 改动3c: 加参数
    ) -> Dict[str, Any]:
        """为多个独立程序生成支持 sanitizer 的 Makefile"""
        try:
            sanitizer_flags = self._generate_sanitizer_flags(sanitizers)
            
            # 决定输出后缀
            if not sanitizers:
                out_suffix = "_vg"
            elif 'thread' in sanitizers:
                out_suffix = "_tsan"
            else:
                out_suffix = "_asan"
            
            # ===== 🆕 核心修改：TSan 仅对多线程文件生成 =====
            files_to_compile = []
            if out_suffix == "_tsan":
                # TSan：仅编译包含多线程代码的文件
                for mf in main_files:
                    if self._file_needs_pthread(mf):
                        files_to_compile.append(mf)
                if not files_to_compile:
                    log_warning("⚠️ 未检测到多线程文件，跳过 TSan 编译")
                    return {
                        'success': True,
                        'build_system': 'generated_makefile_multi',
                        'build_dir': project_path,
                        'executables': [],
                        'stdout': '',
                        'stderr': 'No threading files for TSan'
                    }
            else:
                # Valgrind/ASan：编译所有文件
                files_to_compile = main_files
            
            log_info(f"📦 本次编译 {out_suffix} 版本，共 {len(files_to_compile)} 个文件")

            
            # 生成多目标 Makefile
            makefile_path = os.path.join(project_path, 'Makefile.sanitizer')
            makefile_content = self._generate_multi_target_makefile_with_suffix(
                files_to_compile,  # ← 改为仅编译筛选后的文件
                out_suffix,
                sanitizer_flags,
                project_path,
                cpp_standard  # 🆕 改动3d: 传递参数
            )
        

            
            with open(makefile_path, 'w', encoding='utf-8') as f:
                f.write(makefile_content)
            
            log_info(f"✅ 多目标Makefile已生成: {makefile_path}")
            
            # 清理
            if clean_build:
                subprocess.run(
                    ['make', '-f', makefile_path, 'clean'],
                    cwd=project_path,
                    capture_output=True,
                    timeout=30
                )
            
            # 编译
            build_cmd = [
                'make', '-f', makefile_path, '-j4', '-k',
                f'CXXFLAGS_EXTRA={sanitizer_flags}',
                f'LDFLAGS_EXTRA={sanitizer_flags}'
            ]
            
            log_info(f"🔨 执行编译命令: {' '.join(build_cmd)}")
            
            build_result = subprocess.run(
                build_cmd,
                cwd=project_path,
                capture_output=True,
                timeout=600
            )
            
            stdout = self._safe_decode_output(build_result.stdout)
            stderr = self._safe_decode_output(build_result.stderr)
            
            if build_result.returncode != 0:
                log_warning(f"⚠️  部分文件编译失败（继续收集成功的可执行文件）:\n{stderr}")
                # ✅ 不直接返回失败，而是继续查找成功编译的文件
            else:
                log_info("✅ 编译全部成功")

            # ===== 🔥 修改核心：无论成功失败都尝试收集可执行文件 =====
            executables = self._find_multi_target_executables(
                project_path, main_files, out_suffix
            )

            # ===== 🔥 只有在完全没有可执行文件时才返回失败 =====
            if not executables:
                log_error(f"❌ 所有 {len(main_files)} 个文件编译失败，未生成任何可执行文件")
                return {
                    'success': False, 
                    'error': '所有文件编译失败', 
                    'stderr': stderr,
                    'executables': []  # ← 明确返回空列表
                }

            # ===== 部分成功 =====
            log_info(f"✅ 编译完成，成功生成 {len(executables)}/{len(main_files)} 个可执行文件")

            return {
                'success': True,  # ← 只要有部分成功就返回True
                'build_system': 'generated_makefile_multi',
                'build_dir': project_path,
                'makefile_path': makefile_path,
                'executables': executables,
                'stdout': stdout,
                'stderr': stderr,
                'partial_failure': build_result.returncode != 0  # ← 新增字段，标记部分失败
            }
                        
        except subprocess.TimeoutExpired:
            log_error("多目标编译超时")
            return {'success': False, 'error': '编译超时'}
        except Exception as e:
            log_error(f"多目标编译失败: {e}")
            import traceback
            log_error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    # ===== 🆕 新增方法2：生成多目标Makefile =====
    def _generate_multi_target_makefile_with_suffix(
        self,
        main_files: List[str],
        out_suffix: str,
        sanitizer_flags: str,
        project_path: str,
        cpp_standard: str = "c++17"  # 🆕 改动3e: 加参数
    ) -> str:
        """生成多目标Makefile（每个main独立编译，支持后缀）"""
        TAB = '\t'
        
        targets = []
        rules = []
        
        # 为每个文件生成独立的编译规则
        for main_file in main_files:
            basename = os.path.splitext(os.path.basename(main_file))[0]
            target_name = f"{basename}{out_suffix}"
            main_rel = os.path.relpath(main_file, project_path)
            
            # 检测该文件是否使用多线程
            needs_pthread = self._file_needs_pthread(main_file)
            pthread_flag = '-pthread' if needs_pthread else ''
            
            targets.append(target_name)
            rules.append(f"""
# 目标: {target_name} (源文件: {main_rel})
{target_name}: {main_rel}
{TAB}$(CXX) $(CXXFLAGS_COMMON) {pthread_flag} $(CXXFLAGS_EXTRA) $< -o $@ $(LDFLAGS_COMMON) {pthread_flag} $(LDFLAGS_EXTRA)
""")
        
        all_targets = ' '.join(targets)
        
        makefile = f"""# Auto-generated Multi-Target Makefile (with Sanitizer support)
# Generated for {len(main_files)} independent programs
# C++ Standard: {cpp_standard}  # 🆕 改动3g: 显示标准

CXX ?= g++
CXXFLAGS_COMMON := -std={cpp_standard} -g -O1 -fno-omit-frame-pointer  # 🆕 改动3f: 使用变量
LDFLAGS_COMMON :=

# 外部追加的 Sanitizer 标志
CXXFLAGS_EXTRA ?=
LDFLAGS_EXTRA ?=

all: {all_targets}

{''.join(rules)}

.PHONY: clean
clean:
{TAB}rm -f {all_targets} *.o
"""
        return makefile

    # ===== 🆕 新增方法3：查找多目标可执行文件 =====
    def _find_multi_target_executables(
        self,
        project_path: str,
        main_files: List[str],
        out_suffix: str
    ) -> List[str]:
        """查找多目标编译生成的可执行文件（容错版本）"""
        executables = []
        found_count = 0
        failed_count = 0
        
        for main_file in main_files:
            basename = os.path.splitext(os.path.basename(main_file))[0]
            expected_exe = os.path.join(project_path, f"{basename}{out_suffix}")
            
            if os.path.exists(expected_exe) and os.access(expected_exe, os.X_OK):
                executables.append(os.path.abspath(expected_exe))
                found_count += 1
                log_info(f"   ✅ 找到: {os.path.basename(expected_exe)}")
            else:
                failed_count += 1
                log_warning(f"   ⚠️  未找到: {os.path.basename(expected_exe)}")
        
        # ✅ 关键改动：即使部分失败也继续
        if found_count > 0:
            log_info(f"✅ 成功编译 {found_count} 个文件，失败 {failed_count} 个")
            return executables
        else:
            log_error(f"❌ 所有 {len(main_files)} 个文件编译失败")
            return []
    

    def _generate_makefile_template_with_suffix(self, source_files: List[str], cpp_standard: str = "c++17", extra_flags: Dict[str, str] = None) -> str:
        """
        生成支持 OUT_SUFFIX 的 Makefile（模板B）
        - 产物名：test_dynamic$(OUT_SUFFIX)
        - 自动检测 pthread：遇到 pthread 或 std::thread 自动加 -pthread
        - 允许通过 CXXFLAGS_EXTRA / LDFLAGS_EXTRA 注入 sanitizer
        """
        has_cpp = any(f.endswith(('.cpp', '.cc', '.cxx')) for f in source_files)
        compiler = 'g++' if has_cpp else 'gcc'
        sources = ' '.join(source_files)
        objects = ' '.join(
            f.replace('.cpp', '.o').replace('.cc', '.o').replace('.cxx', '.o').replace('.c', '.o')
            for f in source_files
        )
        TAB = '\t'

        # 🆕 合并依赖
        extra_includes = extra_flags.get('includes', '')
        extra_libs = extra_flags.get('libs', '')
        extra_ldflags = extra_flags.get('ldflags', '')


        return f"""# Auto-generated Makefile (supports OUT_SUFFIX for multi-variant builds)
CXX ?= {compiler}
SRC ?= {sources}
OBJ ?= {objects}

CXXFLAGS_COMMON := -std={cpp_standard} -g -O1 -fno-omit-frame-pointer
LDFLAGS_COMMON :=

# 运行时通过 OUT_SUFFIX 控制输出文件名：_vg / _asan / _tsan
OUT_SUFFIX ?=
BIN_NAME ?= test_dynamic$(OUT_SUFFIX)

# 允许外部注入附加编译/链接参数（sanitizer等）
CXXFLAGS_EXTRA ?=
LDFLAGS_EXTRA ?=

# 自动检测 pthread / std::thread
NEED_PTHREAD := $(shell grep -E -q "pthread|<thread>|std::thread" -r . && echo 1 || echo 0)
ifeq ($(NEED_PTHREAD),1)
    PTHREAD_FLAGS := -pthread
else
    PTHREAD_FLAGS :=
endif

all: $(BIN_NAME)

$(BIN_NAME): $(OBJ)
{TAB}$(CXX) $(LDFLAGS_COMMON) $(PTHREAD_FLAGS) $(LDFLAGS_EXTRA) -o $@ $^

%.o: %.cpp
{TAB}$(CXX) $(CXXFLAGS_COMMON) $(PTHREAD_FLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

%.o: %.cc
{TAB}$(CXX) $(CXXFLAGS_COMMON) $(PTHREAD_FLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

%.o: %.cxx
{TAB}$(CXX) $(CXXFLAGS_COMMON) $(PTHREAD_FLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

%.o: %.c
{TAB}$(CXX) $(CXXFLAGS_COMMON) $(PTHREAD_FLAGS) $(CXXFLAGS_EXTRA) -c $< -o $@

.PHONY: clean
clean:
{TAB}rm -f $(OBJ) test_dynamic test_dynamic_* *.o
"""

    def check_compiler_support(self) -> Dict[str, Any]:
        """检查编译器是否支持Sanitizer"""
        supported = {}
        for compiler in self.supported_compilers:
            try:
                result = subprocess.run([compiler, '--version'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    supported[compiler] = {'available': True, 'version': result.stdout.split('\n')[0]}
            except Exception:
                supported[compiler] = {'available': False}
        return supported
    def _has_main_function(self, file_path: str) -> bool:
        """检查文件是否包含main函数（去除注释）"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 移除单行注释
            lines = [line.split('//')[0] for line in content.split('\n')]
            content_clean = '\n'.join(lines)
            
            # 移除多行注释（简单版）
            import re
            content_clean = re.sub(r'/\*.*?\*/', '', content_clean, flags=re.DOTALL)
            
            return ('int main(' in content_clean or 
                    'int main (' in content_clean or
                    'void main(' in content_clean)
        except:
            return False

    def _file_needs_pthread(self, file_path: str) -> bool:
        """检测单个文件是否需要 pthread"""
        threading_keywords = [
            '#include <pthread.h>',
            'pthread_create',
            '#include <thread>',
            'std::thread'
        ]
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return any(kw in content for kw in threading_keywords)
        except:
            return False

    def _find_compiled_executables(self, project_path: str) -> List[str]:
        """查找编译生成的可执行文件（支持多目标）"""
        executables = []

        # 优先识别 test_dynamic 家族
        preferred = []
        fallback = []

        for file in os.listdir(project_path):
            file_path = os.path.join(project_path, file)

            if not (os.path.isfile(file_path) and os.access(file_path, os.X_OK)):
                continue
            if file.endswith(('.o', '.a', '.so', '.dylib', '.sh')):
                continue

            if file.startswith('test_dynamic'):
                preferred.append(file_path)
                log_info(f"   🎯 找到可执行文件: {file}")
            elif file.startswith('test_') or file == 'test_dynamic':
                fallback.append(file_path)
                log_info(f"   🎯 找到可执行文件: {file}")

        executables = preferred or fallback

        # 如果仍然没有，最后全量兜底
        if not executables:
            log_warning("   ⚠️  未找到 test_dynamic* 可执行文件，搜索所有可执行文件...")
            for file in os.listdir(project_path):
                file_path = os.path.join(project_path, file)
                if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                    if not file.endswith(('.o', '.a', '.so', '.dylib', '.sh')):
                        executables.append(file_path)
                        log_info(f"   📎 找到可执行文件: {file}")

        return executables

    def _extract_dependencies_from_makefile(self, project_path: str) -> Dict[str, str]:
        """从原生Makefile提取include路径和链接库(智能展开变量)"""
        import re
        
        result = {
            'includes': '',
            'libs': '',
            'ldflags': ''
        }
        
        makefile_path = os.path.join(project_path, 'Makefile')
        if not os.path.exists(makefile_path):
            return result
        
        try:
            with open(makefile_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 🆕 第一步:提取变量定义
            variables = {}
            var_pattern = r'(\w+)\s*[:\+]?=\s*([^\n]+)'
            for match in re.finditer(var_pattern, content):
                var_name, var_value = match.groups()
                variables[var_name] = var_value.strip()
            
            # 🆕 第二步:展开常见变量
            def expand_vars(text):
                """递归展开Makefile变量"""
                max_iterations = 10
                for _ in range(max_iterations):
                    # 匹配 $(VAR) 或 ${VAR}
                    pattern = r'\$[\(\{](\w+)[\)\}]'
                    matches = re.findall(pattern, text)
                    if not matches:
                        break
                    for var in matches:
                        if var in variables:
                            text = text.replace(f'$({var})', variables[var])
                            text = text.replace(f'${{{var}}}', variables[var])
                        elif var == 'SRCDIR':
                            text = text.replace(f'$({var})', 'src')
                        elif var == 'BUILDDIR':
                            text = text.replace(f'$({var})', 'build')
                return text
            
            # 提取 -I 路径
            include_matches = re.findall(r'-I\s*([^\s]+)', content)
            if include_matches:
                expanded_includes = [expand_vars(inc) for inc in include_matches]
                result['includes'] = ' '.join(f'-I{inc}' for inc in expanded_includes)
            
            # 提取 -l 库
            lib_matches = re.findall(r'-l([^\s]+)', content)
            if lib_matches:
                # 🆕 过滤掉特定平台的库
                exclude_libs = {'kvm', 'devstat', 'prop', 'ibgcc', 'ibstdc++'}
                valid_libs = [lib for lib in lib_matches if lib not in exclude_libs]
                result['libs'] = ' '.join(f'-l{lib}' for lib in valid_libs)
            
            # 🆕 第三步:检测并添加fmt库
            if 'fmt::' in content or '#include <fmt/' in content:
                log_info("   🔍 检测到fmt库依赖,添加 -lfmt")
                result['libs'] += ' -lfmt'
            
            # 🆕 第四步:添加常见C++库
            common_libs = ['-lstdc++', '-lm', '-lpthread']
            for lib in common_libs:
                if lib not in result['libs']:
                    result['libs'] += f' {lib}'
            
            log_info(f"   提取到includes: {result['includes']}")
            log_info(f"   提取到libs: {result['libs']}")
            
        except Exception as e:
            log_warning(f"提取Makefile依赖失败: {e}")
        
        return result

    def _check_system_dependencies(self, project_path: str) -> List[str]:
        """检查并返回缺失的系统依赖"""
        missing = []
        
        # 检查fmt库
        result = subprocess.run(
            ['pkg-config', '--exists', 'fmt'],
            capture_output=True
        )
        if result.returncode != 0:
            missing.append('libfmt-dev')
        
        return missing



