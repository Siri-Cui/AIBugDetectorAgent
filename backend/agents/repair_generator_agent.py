# -*- coding: utf-8 -*-
"""修复建议生成Agent
作用：基于LLM（GLM-4）生成智能修复建议（增强版：基于真实代码）
依赖：base_agent、tools.llm_client、tools.code_extractor、tools.patch_generator、utils.logger
调用关系：被orchestrator调用，在静态检测后执行
"""
import re
from typing import Dict, List, Any
from .base_agent import BaseAgent, AgentResponse, AgentStatus
from tools.llm_client import LLMClient
from tools.code_extractor import CodeExtractor
from tools.patch_generator import PatchGenerator
from utils.logger import log_info, log_error, log_warning
import os


class RepairGeneratorAgent(BaseAgent):
    """修复建议生成Agent - 使用LLM生成智能修复方案（基于真实代码）"""

    def __init__(self):
        super().__init__(agent_id="repair_001", name="RepairGeneratorAgent")
        self.llm_client = LLMClient()
        self.code_extractor = CodeExtractor()  # ✅ 新增：代码提取器
        self.patch_generator = PatchGenerator()  # ✅ 新增：补丁生成器

    def get_capabilities(self) -> List[str]:
        """返回Agent能力列表"""
        return [
            "intelligent_repair_generation",  # 智能修复生成
            "code_fix_suggestion",  # 代码修复建议
            "best_practice_recommendation",  # 最佳实践推荐
            "vulnerability_mitigation",  # 漏洞缓解方案
            "real_code_context_repair",  # ✅ 新增：基于真实代码的修复
        ]

    async def process(self, task_data: Dict[str, Any]) -> AgentResponse:
        """处理修复建议生成任务（增强版：携带真实代码）
        输入：task_data包含detection_results、file_analysis、context和project_path
        输出：智能修复建议（包含可应用的diff补丁）
        """
        try:
            self.set_status(AgentStatus.WORKING)
            log_info(f"{self.name} 开始生成智能修复建议（基于真实代码）")

            # 提取输入数据
            detection_results = task_data.get("detection_results", {})
            file_analysis = task_data.get("file_analysis", {})
            context_data = task_data.get("context", {})
            project_path = task_data.get("project_path", "")  # ✅ 新增：项目路径

            # 获取问题列表
            parsed_results = detection_results.get("parsed_results", {})
            all_issues = parsed_results.get("issues", [])

            if not all_issues:
                log_info("未发现问题，无需生成修复建议")
                return AgentResponse(
                    success=True,
                    message="代码质量良好，无需修复",
                    data={
                        "repair_suggestions": [],
                        "summary": "没有发现需要修复的问题",
                    },
                )

            # ✅ 新增：筛选高危和中危问题（避免过多调用LLM）
            critical_issues = [
                issue
                for issue in all_issues
                if issue.get("severity") in ["high", "critical", "medium"]
                and self._is_repairable_file(
                    issue.get("file", "")
                )  # ✅ 新增：文件类型检查
            ][:10]

            log_info(
                f"从{len(all_issues)}个问题中选择{len(critical_issues)}个高危问题生成修复"
            )

            # ✅ 新增：批量提取代码上下文
            if not project_path:
                log_warning("未提供project_path，回退到描述性修复建议")
                issue_contexts = {}
            else:
                log_info(f"正在从项目路径提取真实代码: {project_path}")
                issue_contexts = self.code_extractor.extract_multiple_contexts(
                    critical_issues, project_path
                )
                log_info(f"成功提取{len(issue_contexts)}个问题的代码上下文")

            # 构建项目上下文（保留原有逻辑）
            project_context = self._build_project_context(file_analysis, context_data)

            # ✅ 新增：为每个问题生成带真实代码的修复建议
            repair_suggestions = []

            for issue in critical_issues:
                issue_id = issue.get("id")
                context = issue_contexts.get(issue_id, {})

                # 如果成功提取到函数体，调用LLM生成修复
                if context.get("function", {}).get("found"):
                    log_info(f"为问题 {issue_id} 生成基于真实代码的修复建议")
                    repair = self._generate_repair_with_real_code(
                        issue, context, project_context
                    )
                    repair_suggestions.append(repair)
                else:
                    # 回退到旧方法（基于问题描述）
                    log_warning(f"问题 {issue_id} 无法提取函数体，使用描述性修复")
                    repair = self._generate_descriptive_repair(issue, project_context)
                    repair_suggestions.append(repair)

            # 汇总修复建议
            summary = {
                "total_issues": len(all_issues),
                "repairs_generated": len(repair_suggestions),
                "with_real_code": len(
                    [
                        r
                        for r in repair_suggestions
                        if r.get("type") == "llm_generated_with_context"
                    ]
                ),
                "descriptive_only": len(
                    [r for r in repair_suggestions if r.get("type") == "llm_generated"]
                ),
                "context_aware": True,
            }

            self.set_status(AgentStatus.COMPLETED)
            log_info(f"{self.name} 完成修复建议生成，共{len(repair_suggestions)}条建议")

            return AgentResponse(
                success=True,
                message=f"成功生成{len(repair_suggestions)}个修复建议",
                data={"repair_suggestions": repair_suggestions, "summary": summary},
            )

        except Exception as e:
            self.set_status(AgentStatus.FAILED)
            log_error(f"{self.name} 生成修复建议失败: {str(e)}")
            import traceback

            log_error(f"详细错误: {traceback.format_exc()}")
            return AgentResponse(
                success=False, message="生成修复建议失败", errors=[str(e)]
            )

    def _generate_repair_with_real_code(
        self,
        issue: Dict[str, Any],
        context: Dict[str, Any],
        project_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """✅ 新增方法：基于真实代码生成修复建议"""
        try:
            function_info = context.get("function", {})
            function_body = function_info.get("body", "")
            defect_line_content = context.get("defect_line_content", "")
            class_info = context.get("class_context")

            # 构造包含真实代码的提示词
            prompt = f"""你是一个C++代码修复专家。请分析以下真实代码中的缺陷并提供修复方案。

## 缺陷信息
- 文件: {issue.get('file', 'unknown')}
- 行号: {issue.get('line', 0)}
- 类型: {issue.get('category', 'unknown')}
- 描述: {issue.get('message', '')}
- 严重度: {issue.get('severity', 'unknown')}

## 项目上下文
- 平台: {project_context.get('target_platform', 'unknown')}
- 编译器: {project_context.get('compiler_info', 'unknown')}
- 上下文说明: {project_context.get('context_notes', '')}

## 完整函数体
  ```cpp
  {function_body}
  ```

  ## 缺陷行（第 {issue.get('line', 0)} 行）

  ```cpp
  {defect_line_content}
  ```

  ## 函数上下文

  - 函数名: {function_info.get('name', 'unknown')}
  - 函数签名: {function_info.get('signature', '')}
  - 所在类: {(class_info or {}).get('name', 'N/A') if class_info else 'N/A'}

  请提供：

  1. 问题根因分析（不超过3行）
  2. 修复后的完整函数体（用```cpp包裹，保持原有缩进和代码风格）
  3. 测试建议（1-2条）

  重要要求：

  - 修复后的代码必须是完整的、可编译的
  - 严格保持原有的代码风格、缩进和命名规范
  - 只修改有问题的部分，不要改动无关代码
  - 不要添加过多的注释，保持代码简洁
     """
            # 调用LLM
            log_info(f"调用LLM生成真实代码修复（问题ID: {issue.get('id')}）")
            response = self.llm_client.client.chat.completions.create(
                model=self.llm_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=5000,
            )

            llm_response = response.choices[0].message.content.strip()

            # 解析LLM返回的修复代码
            fixed_code = self._extract_code_from_llm_response(llm_response)

            if not fixed_code:
                log_warning(f"LLM未返回有效代码，回退到描述性修复")
                return self._generate_descriptive_repair(issue, project_context)

            # 生成diff补丁
            diff_patch = self.patch_generator.create_diff_patch(
                original_code=function_body,
                fixed_code=fixed_code,
                file_path=issue.get("file", ""),
                start_line=function_info.get("start_line", 1),
            )

            return {
                "id": f'repair_{issue.get("id")}',
                "issue_id": issue.get("id"),
                "severity": issue.get("severity"),
                "file_path": issue.get("file"),
                "line": issue.get("line"),
                "root_cause": self._extract_root_cause(llm_response),
                "fixed_code": fixed_code,
                "diff_patch": diff_patch,
                "test_suggestions": self._extract_test_suggestions(llm_response),
                "type": "llm_generated_with_context",
                "can_auto_apply": True,
                "priority": self._calculate_priority(llm_response),
            }

        except Exception as e:
            log_error(f"生成真实代码修复失败: {str(e)}")
            # 回退到描述性修复
            return self._generate_descriptive_repair(issue, project_context)

    def _generate_descriptive_repair(
        self, issue: Dict[str, Any], project_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成描述性修复建议（回退方法）"""
        try:
            # 构造简化的提示词（闭合三引号与段落）
            prompt = f"""分析以下C++代码问题并提供修复建议：
问题：{issue.get('message', '')}
文件：{issue.get('file', '')}
行号：{issue.get('line', 0)}
严重度：{issue.get('severity', '')}

项目环境：{project_context.get('context_notes', '')}

请简要说明：
1. 问题原因
2. 修复方案
3. 如何测试
"""
            response = self.llm_client.client.chat.completions.create(
                model=self.llm_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )

            suggestion = response.choices[0].message.content.strip()

            return {
                "id": f'repair_{issue.get("id")}',
                "issue_id": issue.get("id"),
                "severity": issue.get("severity"),
                "file_path": issue.get("file"),
                "line": issue.get("line"),
                "suggestion": suggestion,
                "type": "llm_generated",
                "can_auto_apply": False,
                "priority": self._calculate_priority(suggestion),
            }

        except Exception as e:
            log_error(f"生成描述性修复失败: {str(e)}")
            return {
                "id": f'repair_{issue.get("id")}',
                "issue_id": issue.get("id"),
                "error": str(e),
                "type": "failed",
            }

    def _extract_code_from_llm_response(self, response: str) -> str:
        """从LLM响应中提取代码块"""
        # 优先查找cpp代码块
        m = re.search(
            r"```(?:cpp|c\+\+)\s*\n(.*?)\n```", response, re.DOTALL | re.IGNORECASE
        )
        if m:
            return m.group(1).strip()

        m = re.search(r"```\s*\n(.*?)\n```", response, re.DOTALL)
        if m:
            return m.group(1).strip()

        return ""

    def _extract_root_cause(self, response: str) -> str:
        """提取问题根因"""
        lines = response.split("\n")
        for i, line in enumerate(lines):
            if "问题根因" in line or "根因分析" in line or "root cause" in line.lower():
                # 取接下来的3行
                return "\n".join(lines[i + 1 : i + 4]).strip()
        return "未提取到根因分析"

    def _extract_test_suggestions(self, response: str) -> List[str]:
        """提取测试建议"""
        suggestions: List[str] = []
        lines = response.split("\n")
        in_test_section = False

        for raw in lines:
            line = raw.strip()
            low = line.lower()

            # 进入“测试建议”小节（中英文都尽量兼容）
            if ("测试建议" in line) or (
                ("test" in low)
                and ("建议" in line or "suggestion" in low or "strategy" in low)
            ):
                in_test_section = True
                continue

            if in_test_section:
                # 遇到空行视为段落结束
                if not line:
                    break

                # 支持无序(- * •)和常见有序(1. / 1) / 1、)项目符
                if line.startswith(("-", "*", "•")) or re.match(
                    r"^\d+[\.\)\u3001]\s*", line
                ):
                    cleaned = re.sub(r"^(\-|\*|•)\s*", "", line)  # 去掉无序符号
                    cleaned = re.sub(
                        r"^\d+[\.\)\u3001]\s*", "", cleaned
                    )  # 去掉有序编号
                    suggestions.append(cleaned.strip())

        return suggestions if suggestions else ["运行单元测试验证修复"]

    def _build_project_context(
        self, file_analysis: Dict[str, Any], context_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """构建项目上下文信息（包含ContextAnalyzerAgent的分析结果）"""
        # 提取平台信息
        platform_info = context_data.get("platform_info", {})
        detected_platforms = platform_info.get("detected_platforms", [])

        # 提取宏定义信息
        macros = context_data.get("macros", {})
        defined_macros = list(macros.get("defined", {}).keys())
        conditional_macros = [
            m.get("macro")
            for m in macros.get("conditional", [])
            if isinstance(m, dict) and m.get("macro")
        ]

        # 提取编译器信息
        compiler_info = context_data.get("compiler_info", {})
        detected_compilers = compiler_info.get("detected_compilers", [])

        context = {
            "project_type": "C++ Project",
            "file_count": len(file_analysis.get("source_files", [])),
            "total_lines": file_analysis.get("complexity_metrics", {}).get(
                "total_lines", 0
            ),
            "description": "代码缺陷检测与修复分析",
            # 加入ContextAnalyzerAgent提供的上下文信息
            "target_platform": (
                ", ".join(detected_platforms) if detected_platforms else "unknown"
            ),
            "defined_macros": defined_macros,
            "conditional_macros": list(set(conditional_macros)),  # 去重
            "compiler_info": (
                ", ".join(detected_compilers) if detected_compilers else "unknown"
            ),
            # 提供简要的上下文说明
            "context_notes": self._generate_context_notes(
                detected_platforms, conditional_macros
            ),
        }

        return context

    def _generate_context_notes(self, platforms: List[str], macros: List[str]) -> str:
        """生成上下文说明，帮助LLM理解代码环境"""
        notes = []
        if platforms:
            platform_str = "、".join(platforms)
            notes.append(f"代码包含{platform_str}平台特定实现")

        if macros:
            unique_macros = list(set(macros))
            if len(unique_macros) <= 3:
                macro_str = "、".join(unique_macros)
                notes.append(f"使用了条件编译宏: {macro_str}")
            else:
                notes.append(f"使用了{len(unique_macros)}个条件编译宏")

        return "；".join(notes) if notes else "通用C++代码"

    def _calculate_priority(self, suggestion: str) -> str:
        """计算修复建议的优先级"""
        suggestion_lower = suggestion.lower()

        # 高优先级关键词
        high_priority_keywords = [
            "memory leak",
            "内存泄漏",
            "buffer overflow",
            "缓冲区溢出",
            "null pointer",
            "空指针",
            "critical",
            "严重",
            "security",
            "安全",
            "crash",
            "崩溃",
        ]

        # 中优先级关键词
        medium_priority_keywords = [
            "warning",
            "警告",
            "potential",
            "潜在",
            "should",
            "应该",
            "recommend",
            "建议",
        ]

        for keyword in high_priority_keywords:
            if keyword in suggestion_lower:
                return "high"

        for keyword in medium_priority_keywords:
            if keyword in suggestion_lower:
                return "medium"

        return "low"

    def _is_repairable_file(self, file_path: str) -> bool:
        """检查文件是否可以生成修复建议（必须是源码文件）"""
        # 源代码文件扩展名
        source_extensions = {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx", ".c++"}

        # 排除的扩展名
        excluded_extensions = {
            ".obj",
            ".exe",
            ".dll",
            ".so",
            ".a",
            ".o",
            ".lib",
            ".pdb",
        }

        ext = os.path.splitext(file_path)[1].lower()

        # 明确排除编译产物
        if ext in excluded_extensions:
            log_info(f"跳过编译产物文件: {file_path}")
            return False

        # 只处理源码文件
        if ext not in source_extensions:
            log_info(f"跳过非源码文件: {file_path}")
            return False

        return True
