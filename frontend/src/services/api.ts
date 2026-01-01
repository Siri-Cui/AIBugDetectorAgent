/**
 * API客户端封装
 */

import axios, { AxiosInstance, AxiosResponse, AxiosError } from 'axios';

// API基础配置
const API_BASE_URL = process.env.REACT_APP_API_URL || '';
const API_TIMEOUT = 30000; // 30秒超时

// 创建axios实例
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: API_TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 添加时间戳防止缓存
    if (config.method === 'get') {
      config.params = {
        ...config.params,
        _t: Date.now(),
      };
    }
    
    console.log(`🚀 API请求: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    console.error('❌ 请求拦截器错误:', error);
    return Promise.reject(error);
  }
);

// 响应拦截器
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    console.log(`✅ API响应: ${response.config.url} - ${response.status}`);
    return response;
  },
  (error: AxiosError) => {
    console.error(`❌ API错误: ${error.config?.url} -`, error.response?.status, error.message);
    
    // 统一错误处理
    if (error.response) {
      // 服务器响应错误
      const { status, data } = error.response;
      switch (status) {
        case 400:
          console.error('请求参数错误:', data);
          break;
        case 401:
          console.error('未授权访问');
          break;
        case 403:
          console.error('访问被禁止');
          break;
        case 404:
          console.error('资源不存在');
          break;
        case 500:
          console.error('服务器内部错误');
          break;
        default:
          console.error('未知错误:', status);
      }
    } else if (error.request) {
      // 网络错误
      console.error('网络连接错误');
    } else {
      // 其他错误
      console.error('请求配置错误:', error.message);
    }
    
    return Promise.reject(error);
  }
);

// API接口类型定义
export interface SystemInfo {
  name: string;
  version: string;
  status: string;
  uptime?: string;
  supported_agents: string[];
  workflow: string;
}

export interface HealthStatus {
  status: string;
  timestamp: string;
  version: string;
  services: Record<string, string>;
}

export interface FileInfo {
  filename: string;
  original_name: string;
  size: number;
  extension: string;
  upload_time: string;
  file_path: string;
  status: string;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  file_info: FileInfo;
  project_id: string;
}

// API方法封装
export const api = {
  // 系统相关
  async getSystemInfo(): Promise<SystemInfo> {
    const response = await apiClient.get('/');
    return response.data;
  },

  async getHealthStatus(): Promise<HealthStatus> {
    const response = await apiClient.get('/health');
    return response.data;
  },

  // 文件上传相关
  async uploadFile(
    file: File, 
    projectName?: string, 
    description?: string,
    onProgress?: (progress: number) => void
  ): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    
    if (projectName) {
      formData.append('project_name', projectName);
    }
    if (description) {
      formData.append('description', description);
    }

    const response = await apiClient.post('/api/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(progress);
        }
      },
    });

    return response.data;
  },

  // 项目管理相关
  async getProjects(): Promise<any> {
    const response = await apiClient.get('/api/projects');
    return response.data;
  },

  async deleteProject(projectId: string): Promise<any> {
    const response = await apiClient.delete(`/api/projects/${projectId}`);
    return response.data;
  },
};

export default api;
