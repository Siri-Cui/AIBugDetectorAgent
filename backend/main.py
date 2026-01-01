"""FastAPI应用入口 - 迭代八：指标计算与可视化报告"""

import os
import uvicorn
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from config import settings
from api.routes import upload, analysis, repair, metrics, websocket
from api.models import SystemInfo, HealthResponse, ErrorResponse
from utils.logger import logger, log_info, log_error
from utils.exceptions import AIBugDetectorException


# 应用启动和关闭处理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    log_info("=" * 60)
    log_info("🚀 AI Agent缺陷检测系统启动中...")
    log_info(f"📦 版本: v0.8.0 - 迭代八（指标计算与可视化报告）")
    log_info(f"🌐 API文档: http://localhost:8000/docs")
    log_info(f"💾 数据库: {settings.DATABASE_URL}")
    log_info("=" * 60)

    yield

    # 关闭时执行
    log_info("AI Agent缺陷检测系统正在关闭...")


# 创建FastAPI应用
app = FastAPI(
    title="AI Agent缺陷检测系统",
    description="""
    基于多Agent协作的C++代码缺陷检测系统
    
    ## 主要功能
    - 项目文件上传和管理
    - 多Agent协作静态分析（FileAnalyzer + ContextAnalyzer + DetectionAgent）
    - 智能缺陷检测（Cppcheck + Clang-tidy + 专项检测器）
    - 真实代码修复建议（基于LLM + 代码上下文提取）
    - 可应用的Diff补丁生成
    - 动态运行时验证（Valgrind + Sanitizer）
    - 静动态交叉验证与结果关联
    - 📊 综合指标计算与质量评分 ✅ [当前迭代]
    - 📈 多格式可视化报告（HTML/Markdown/JSON + 图表）✅ [当前迭代]
    
    ## 分析流程
    1. 文件上传 ✅
    2. 文件分析Agent（识别项目类型、提取代码结构）✅
    3. 上下文分析Agent（平台检测、宏定义、编译器信息）✅
    4. 静态检测Agent（多工具协作 + 专项检测）✅
    5. 修复建议Agent（真实代码 + LLM增强）✅
    6. 动态分析Agent（Valgrind + Sanitizer）✅
    7. 静动态结果关联与交叉验证 ✅
    8. 📊 综合指标计算 + 质量评分（0-100分）✅ [当前迭代]
    9. 📈 可视化报告生成（HTML/MD/图表）✅ [当前迭代]
    10. 智能误报过滤优化（下一迭代）
    
    ## 开发进度（学校大作业）
    - [x] 迭代1：基础框架搭建
    - [x] 迭代2：静态分析工具集成
    - [x] 迭代3：多Agent协作系统 + 专项检测器
    - [x] 迭代4：真实代码上下文的AI修复建议
    - [~] 迭代5：跨文件函数调用链分析（部分完成）
    - [~] 迭代6：智能误报过滤 + 优先级排序（部分完成）
    - [x] 迭代7：动态分析验证（Valgrind + Sanitizer）
    - [x] 迭代8：指标计算 + 可视化报告 [当前]
    - [ ] 迭代9：前端Dashboard + 实时监控
    
    ## 已完成的核心能力
    ✅ 多Agent协作架构（6个Agent协同工作）
    ✅ 文件级静态分析（扫描所有C/C++文件）
    ✅ 项目类型识别（内存池、btop等专项检测）
    ✅ 平台和编译器上下文感知
    ✅ 真实代码提取 + LLM增强修复建议
    ✅ 可应用的Diff补丁生成
    ✅ Valgrind内存检测集成
    ✅ AddressSanitizer/ThreadSanitizer集成
    ✅ 静动态结果交叉验证
    ✅ 综合指标计算（误报率、覆盖率、性能统计）
    ✅ 代码质量评分系统（0-100分 + A-F等级）
    ✅ 多格式报告生成（HTML + Markdown + JSON）
    ✅ 可视化图表（严重度分布、工具对比、文件热力图）
    
    ## 当前迭代8重点
    ⭐ 综合指标计算系统
       - 检测指标：总问题数、文件数、严重度分布、误报率估算
       - 修复指标：建议生成数、代码上下文覆盖率、可自动应用率
       - 性能指标：静态耗时、动态耗时、时间分布
       - 质量评分：0-100分 + A-F等级
    
    ⭐ 多格式可视化报告
       - HTML报告：带CSS样式、响应式布局、完整数据展示
       - Markdown报告：纯文本、适合服务器查看、可粘贴到文档
       - JSON报告：机器可读、包含完整原始数据
    
    ⭐ 统计图表生成
       - 严重度分布饼图（高/中/低危占比）
       - 工具对比柱状图（各工具检测效果）
       - 文件热力图（Top 15问题文件）
    
    ⭐ 项目趋势分析
       - 同一项目多次分析对比
       - 质量评分变化趋势
       - 问题数量演变
    
    ## 新增API端点（迭代8）
    - GET  /api/metrics/summary/{analysis_id}          # 综合指标摘要
    - GET  /api/metrics/quality-score/{analysis_id}    # 质量评分
    - POST /api/reports/generate/{analysis_id}         # 生成所有报告
    - GET  /api/reports/download/{analysis_id}/{format} # 下载报告
    - GET  /api/metrics/comparison/{project_id}        # 项目趋势对比
    """,
    version="0.8.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 应用启动时间
app_start_time = datetime.now()

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """请求日志记录中间件"""
    start_time = datetime.now()

    # 执行请求
    response = await call_next(request)

    # 计算处理时间
    process_time = (datetime.now() - start_time).total_seconds()

    # 记录请求日志
    log_info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Time: {process_time:.3f}s"
    )

    return response


# 全局异常处理
@app.exception_handler(AIBugDetectorException)
async def custom_exception_handler(request: Request, exc: AIBugDetectorException):
    """自定义异常处理器"""
    log_error(f"业务异常: {str(exc)}")

    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            message=str(exc), error_code=exc.error_code or "BUSINESS_ERROR"
        ).dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理器"""
    log_error(f"系统异常: {str(exc)}")

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            message="系统内部错误，请稍后重试", error_code="INTERNAL_SERVER_ERROR"
        ).dict(),
    )


# 注册路由
app.include_router(upload.router)
app.include_router(analysis.router)
app.include_router(repair.router)
app.include_router(metrics.router)  # ✅ 迭代8：指标和报告API
app.include_router(websocket.router)  # ✅ WebSocket实时进度


# 基础路由
@app.get("/", response_model=SystemInfo)
async def get_system_info():
    """系统信息"""
    uptime = datetime.now() - app_start_time
    uptime_str = f"{int(uptime.total_seconds() // 3600)}h {int((uptime.total_seconds() % 3600) // 60)}m"
    return {
        "name": "AI Agent缺陷检测系统",
        "version": "0.8.0",
        "status": "running",
        "uptime": uptime_str,
        "supported_agents": [
            "file_analyzer",  # 文件分析Agent
            "context_analyzer",  # 上下文分析Agent
            "detection",  # 静态检测Agent
            "repair_generator",  # 修复生成Agent
            "validation",  # 校验Agent（含动态分析）
            "metrics_calculator",  # ✅ 迭代8新增：指标计算Agent
        ],
        "current_iteration": "迭代8：指标计算与可视化报告",
        "workflow": "上传 → 文件分析 → 上下文感知 → 静态检测 → 动态验证 → 结果关联 → AI修复 → 📊 指标计算 ✅ → 📈 报告生成 ✅",
        "new_features": [
            "✅ 综合指标计算（误报率、覆盖率、性能统计）",
            "✅ 代码质量评分（0-100分 + A-F等级）",
            "✅ HTML可视化报告（带CSS样式）",
            "✅ Markdown纯文本报告（服务器友好）",
            "✅ 统计图表（3种：饼图/柱状图/热力图）",
            "✅ 项目趋势对比（多次分析）",
        ],
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """系统健康检查"""
    try:
        # 检查关键目录
        upload_ok = os.path.exists(settings.UPLOAD_DIR)
        results_ok = os.path.exists(settings.RESULTS_DIR)
        reports_ok = os.path.exists(os.path.join(settings.RESULTS_DIR, "..", "reports"))

        return HealthResponse(
            services={
                "application": "ok",
                "file_system": "ok" if upload_ok and results_ok else "error",
                "llm_client": "ok",
                "code_extractor": "ok",
                "patch_generator": "ok",
                "database": "ok",
                "valgrind": "ok",
                "sanitizer": "ok",
                "dynamic_executor": "ok",
                "metrics_service": "ok",  # ✅ 迭代8新增
                "report_generator": "ok",  # ✅ 迭代8新增
                "chart_generator": "ok",  # ✅ 迭代8新增
                "redis": "pending",
            }
        )
    except Exception as e:
        log_error(f"健康检查异常: {str(e)}")
        return HealthResponse(status="unhealthy", services={"application": "error"})


# 应用入口
if __name__ == "__main__":
    log_info("直接启动模式")
    log_info("=" * 60)
    log_info("🚀 AI Agent缺陷检测系统 - 迭代8")
    log_info("=" * 60)
    log_info("✅ 已完成：多Agent协作 + 静态分析 + 动态验证 + 真实代码修复")
    log_info("✅ 当前迭代8：综合指标计算 + 可视化报告生成")
    log_info("📊 核心能力：质量评分（0-100分）+ HTML/MD/图表报告")
    log_info("=" * 60)
    log_info("")
    log_info("📋 新增API端点：")
    log_info("  - GET  /api/metrics/summary/{analysis_id}")
    log_info("  - GET  /api/metrics/quality-score/{analysis_id}")
    log_info("  - POST /api/reports/generate/{analysis_id}")
    log_info("  - GET  /api/reports/download/{analysis_id}/{format}")
    log_info("  - GET  /api/metrics/comparison/{project_id}")
    log_info("=" * 60)

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
