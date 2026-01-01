/**
 * 通用类型定义
 */

// 基础响应类型
export type BaseResponse = {
  success: boolean;
  message: string;
  timestamp: string;
};

// 错误响应类型
export type ErrorResponse = BaseResponse & {
  success: false;
  error_code?: string;
  details?: Record<string, any>;
};

// 文件状态枚举
export type FileStatus = 'uploaded' | 'processing' | 'completed' | 'failed';

// 分析状态枚举
export type AnalysisStatus = 'pending' | 'running' | 'completed' | 'failed';

// 缺陷严重程度枚举
export type DefectSeverity = 'low' | 'medium' | 'high' | 'critical';

// 系统信息类型
export type SystemInfo = {
  name: string;
  version: string;
  status: string;
  uptime?: string;
  supported_agents: string[];
  workflow: string;
};

// 健康状态类型
export type HealthStatus = {
  status: string;
  timestamp: string;
  version: string;
  services: Record<string, string>;
};

// 文件信息类型
export type FileInfo = {
  filename: string;
  original_name: string;
  size: number;
  extension: string;
  upload_time: string;
  file_path: string;
  status: FileStatus;
};

// 项目信息类型
export type ProjectInfo = {
  id: string;
  name: string;
  description?: string;
  created_time: string;
  file_count: number;
  status: AnalysisStatus;
};

// 缺陷信息类型
export type DefectInfo = {
  id: string;
  type: string;
  severity: DefectSeverity;
  description: string;
  file_path: string;
  line_number: number;
  column_number?: number;
  code_snippet?: string;
  suggestion?: string;
};

// 分析结果类型
export type AnalysisResult = {
  project_id: string;
  analysis_type: string;
  start_time: string;
  end_time?: string;
  status: AnalysisStatus;
  defects: DefectInfo[];
  statistics: Record<string, any>;
};

// 上传响应类型
export type UploadResponse = BaseResponse & {
  file_info: FileInfo;
  project_id: string;
};

// 项目列表响应类型
export type ProjectListResponse = BaseResponse & {
  projects: ProjectInfo[];
  total: number;
};

// 分析响应类型
export type AnalysisResponse = BaseResponse & {
  analysis_id: string;
  result?: AnalysisResult;
};

// 进度信息类型
export type ProgressInfo = {
  current: number;
  total: number;
  stage: string;
  message: string;
};

// 配置类型
export type AppConfig = {
  apiUrl: string;
  maxFileSize: number;
  supportedExtensions: string[];
  features: {
    staticAnalysis: boolean;
    dynamicAnalysis: boolean;
    aiRepair: boolean;
  };
};

// 工具提示信息类型
export type TooltipInfo = {
  title: string;
  content: string;
  type: 'info' | 'warning' | 'error' | 'success';
};


