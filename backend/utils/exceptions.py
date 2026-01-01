"""自定义异常定义"""

class AIBugDetectorException(Exception):
    """基础异常类"""
    
    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

class FileUploadError(AIBugDetectorException):
    """文件上传相关异常"""
    pass

class FileValidationError(FileUploadError):
    """文件验证异常"""
    pass

class FileSizeError(FileUploadError):
    """文件大小异常"""
    pass

class FileExtensionError(FileUploadError):
    """文件扩展名异常"""
    pass

class AnalysisError(AIBugDetectorException):
    """分析相关异常"""
    pass

class AgentError(AnalysisError):
    """Agent执行异常"""
    pass

class ToolError(AnalysisError):
    """工具执行异常"""
    pass

class DatabaseError(AIBugDetectorException):
    """数据库相关异常"""
    pass

class ConfigurationError(AIBugDetectorException):
    """配置相关异常"""
    pass

class APIError(AIBugDetectorException):
    """API相关异常"""
    
    def __init__(self, message: str, status_code: int = 500, error_code: str = None):
        super().__init__(message, error_code)
        self.status_code = status_code

class ExternalServiceError(AIBugDetectorException):
    """外部服务异常"""
    pass