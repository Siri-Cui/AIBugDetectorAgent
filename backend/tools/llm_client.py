# -*- coding: utf-8 -*-
"""
GLM-4 API 客户端（迭代5增强版：支持动态分析后处理）
作用：集成智谱 AI GLM-4 大模型，提供 AI 分析能力（支持长上下文、专项模板、动态分析去重）
依赖：zhipuai、config.settings、utils.logger
调用关系：
  1. 被 repair_generator_agent 调用（静态分析修复建议）
  2. 被 ai_postprocessor 调用（动态分析智能去重+分析）
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from zhipuai import ZhipuAI

from utils.logger import log_info, log_error
from config import settings


class LLMClient:
    """GLM-4 大语言模型客户端（迭代5增强版）"""

    def __init__(self) -> None:
        self.client: Optional[ZhipuAI] = None
        self.model_name: str = getattr(settings, "MODEL_NAME", "glm-4-plus")  # 🔥 推荐用 glm-4-plus
        self.api_key: Optional[str] = getattr(settings, "ZHIPU_API_KEY", None)
        self._initialize_client()

    def _initialize_client(self) -> None:
        """初始化客户端"""
        try:
            if self.api_key:
                self.client = ZhipuAI(api_key=self.api_key)
                log_info(f"GLM-4 客户端初始化成功（模型: {self.model_name}）")
            else:
                log_error("GLM-4 API 密钥未配置（ZHIPU_API_KEY 为空）")
        except Exception as e:
            log_error(f"GLM-4 客户端初始化失败: {e!s}")

    # ========== 原有方法1: 静态分析的批量修复建议（保持不变）==========
    async def analyze_code_issues(
        self,
        issues: List[Dict[str, Any]],
        project_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        分析代码问题并生成智能建议（保留原有功能，用于批量分析）

        :param issues: 标准化问题列表（含字段：category/message/line/severity 等）
        :param project_context: 项目上下文（可选）
        :return: { success: bool, analysis?: {...}, raw_response?: str, error?: str }
        """
        try:
            if not self.client:
                return {"success": False, "error": "GLM-4 client not initialized"}

            # 仅取高/中危问题，最多 6 条
            critical_issues = [
                it for it in (issues or []) if it.get("severity") in {"high", "medium"}
            ][:6]

            if not critical_issues:
                return {
                    "success": True,
                    "analysis": {
                        "recommendations": ["未发现高/中危问题，无需 AI 修复建议。"],
                        "summary": "无高/中危问题",
                    },
                    "raw_response": "",
                }

            prompt = self._build_code_fix_prompt(critical_issues)

            log_info(f"向 GLM-4 发送代码修复请求，问题数量: {len(critical_issues)}")

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2500,
            )

            content = (response.choices[0].message.content or "").strip()

            log_info("GLM-4 代码修复分析完成")

            return {
                "success": True,
                "analysis": {
                    "recommendations": [content],
                    "summary": "已生成具体的代码修复方案",
                },
                "raw_response": content,
            }

        except Exception as e:
            log_error(f"GLM-4 分析异常: {e!s}")
            return {"success": False, "error": str(e)}

    def _build_code_fix_prompt(self, issues: List[Dict[str, Any]]) -> str:
        """
        构建代码修复专用提示词（包含格式化输出要求与示例）
        """
        header = (
            "你是一位 C++ 代码安全修复专家。请为以下代码问题提供具体的修复方案，"
            "必须包含可直接使用的修复代码。\n\n## 需要修复的问题：\n"
        )

        parts: List[str] = [header]
        for i, issue in enumerate(issues[:6], 1):
            category = issue.get("category", "unknown")
            message = issue.get("message", "")
            line = issue.get("line", 0)
            severity = (issue.get("severity") or "unknown").upper()

            parts.append(
                f"\n**问题 {i}: {category}**\n"
                f"- 位置：第 {line} 行\n"
                f"- 严重程度：{severity}\n"
                f"- 问题描述：{message}\n"
            )

        tail = (
            "\n## 输出要求：\n\n"
            "请严格按照以下格式逐条提供修复方案（问题编号需与上方一致）：\n\n"
            "### 问题1: [问题类型] (第X行)\n\n"
            "**原始代码问题：**\n"
            "```cpp\n"
            "// 在此展示有问题的代码（必要时可伪代码还原场景）\n"
            "```\n\n"
            "**修复后的代码：**\n\n"
            "```cpp\n"
            "// 提供完整可编译的修复代码，包含必要的头文件与边界检查\n"
            "```\n\n"
            "**修复说明：**\n"
            "简要解释修复原理、边界条件与注意事项（中文说明，代码英文注释）。\n\n"
            "------\n\n"
            "### 问题2: [问题类型] (第Y行)\n\n"
            "**原始代码问题：**\n"
            "```cpp\n"
            "// 在此展示有问题的代码\n"
            "```\n\n"
            "**修复后的代码：**\n"
            "```cpp\n"
            "// 提供完整可用的修复代码\n"
            "```\n\n"
            "**修复说明：**\n"
            "详细解释修复原理。\n\n"
            "------\n\n"
            "## 总体建议：\n\n"
            "1. 修复优先级排序\n"
            "2. 代码质量改进建议\n"
            "3. 预防类似问题的最佳实践\n\n"
            "**重要要求：**\n\n"
            "- 必须提供完整可编译的 C++ 代码\n"
            "- 每个修复方案都要包含具体的代码示例\n"
            "- 解释修复原理和注意事项\n"
            "- 用中文回答，代码用英文注释\n"
            "- 仅输出修复所需的内容，不要额外发挥无关内容\n"
        )

        parts.append(tail)
        return "".join(parts)

    # ========== 原有方法2: 长上下文分析（保持兼容，稍作增强）==========
    async def analyze_with_long_context(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        支持长上下文的LLM分析（用于传入完整函数体）
        
        :param prompt: 完整的提示词（包含真实代码）
        :param max_tokens: 最大输出token数
        :param temperature: 温度参数
        :return: { success: bool, content?: str, error?: str }
        """
        try:
            if not self.client:
                return {"success": False, "error": "GLM-4 client not initialized"}

            log_info("调用 GLM-4 进行长上下文分析")

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = (response.choices[0].message.content or "").strip()

            log_info(f"GLM-4 长上下文分析完成，返回长度: {len(content)}")

            return {
                "success": True,
                "content": content
            }

        except Exception as e:
            log_error(f"GLM-4 长上下文分析失败: {e!s}")
            return {"success": False, "error": str(e)}

    # 🆕🆕🆕 ========== 新增方法: 动态分析智能后处理专用 ==========
    async def analyze_with_context(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 8000
    ) -> str:
        """
        🆕 动态分析智能后处理专用方法（用于去重+分析+修复建议）
        
        与 analyze_with_long_context 的区别:
          - 直接返回 str (不包装成 dict)
          - 默认更高的 max_tokens (8000)
          - 专用于 ai_postprocessor 的 JSON 响应解析
        
        :param prompt: 完整的分析提示词（包含issues+源码）
        :param temperature: 温度参数(0.0-1.0,越低越稳定)
        :param max_tokens: 最大返回token数
        :return: AI返回的原始文本（通常是JSON字符串）
        :raises Exception: 调用失败时抛出异常
        """
        try:
            if not self.client:
                raise RuntimeError("GLM-4 客户端未初始化")

            log_info(f"📡 调用智谱AI进行动态分析后处理 (temperature={temperature}, max_tokens={max_tokens})")

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的C/C++静态分析专家,擅长识别安全漏洞并提供修复建议。"
                            "你的回答必须是严格的JSON格式,不要包含任何额外的解释文字。"
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=0.7
            )

            result = (response.choices[0].message.content or "").strip()

            log_info(f"✅ AI返回了 {len(result)} 个字符")

            return result

        except Exception as e:
            log_error(f"❌ GLM-4 动态分析后处理失败: {e}")
            raise

    # ========== 兼容性检查方法（可选）==========
    def is_available(self) -> bool:
        """检查客户端是否可用"""
        return self.client is not None
