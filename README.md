起名困难组：汪诗涵 关显艾 彭小芳 崔思睿 余博文

# AI Bug Detector

## 项目简介

AI Bug Detector 是一款基于 Multi-Agent 架构的 C++ 静态代码分析工具，通过多引擎并行扫描和 AI 智能分析，实现代码缺陷的自动化检测与辅助修复。

## 核心功能

- **多引擎矩阵扫描**：并行调用 Cppcheck（内存/变量检测）、Clang-Tidy（现代规范检查）、Flawfinder（漏洞审计）三大静态分析引擎
- **智能降噪过滤**：自动过滤 Qt 框架自动生成代码（如 moc_*.cpp、qrc_*.cpp）等噪音干扰
- **AI 辅助修复**：基于大语言模型（LLM）生成修复建议和代码补丁
- **结构化报告输出**：支持 JSON 和 Markdown 格式的详细测试报告

## 技术架构

采用 Multi-Agent 并行架构，包含以下核心组件：

- **Orchestrator 编排器**：协调整个分析流程
- **Detection Agent**：并行调度底层检测引擎
- **Result Parser**：结果解析与降噪聚合
- **Repair Agent**：AI 辅助修复生成

## 主要特性

- ✅ 多引擎融合：Clang-Tidy + Cppcheck + Flawfinder 双层检测
- ✅ 高效并行：基于 asyncio 实现多引擎并行扫描，大幅提升分析速度
- ✅ 智能降噪：自动过滤框架生成代码，聚焦真实业务逻辑
- ✅ AI 增强：利用 LLM 进行上下文感知的修复建议生成
- ✅ 数据持久化：基于 SQLite 存储审计任务与结果

## 使用方式

系统采用 FastAPI 提供 RESTful API 接口，支持通过 Swagger 文档进行交互式操作。扫描结果可直接输出为结构化 JSON 或 Markdown 报告，便于在 IDE 中对照修改。

## 应用场景

适用于 C++ 项目的代码质量检测，特别针对 Qt 框架项目进行了优化。在实战测试中，200 秒内完成 24,110 行代码的全量扫描，相比传统人工审计效率提升显著。