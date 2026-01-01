import React, { useState } from 'react';
import {
  Card,
  Upload,
  Button,
  message,
  Typography,
  Space,
  Progress,
  Alert,
  List,
  Tag,
  Divider
} from 'antd';
import {
  UploadOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  DeleteOutlined
} from '@ant-design/icons';
import type { UploadProps, UploadFile } from 'antd/es/upload';

const { Title, Text, Paragraph } = Typography;
const { Dragger } = Upload;

// 文件信息接口
interface FileInfo {
  filename: string;
  original_name: string;
  size: number;
  extension: string;
  upload_time: string;
  file_path: string;
  status: string;
}

// 上传响应接口
interface UploadResponse {
  success: boolean;
  message: string;
  file_info: FileInfo;
  project_id: string;
}

const FileUpload: React.FC = () => {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedFiles, setUploadedFiles] = useState<(FileInfo & { project_id: string })[]>([]);

  // 支持的文件类型
const supportedExtensions = ['.cpp', '.hpp', '.h', '.c', '.cc', '.cxx', '.zip', '.tar.gz', '.tgz'];

  
  // 文件大小限制 (50MB)
  const maxFileSize = 50 * 1024 * 1024;

  // 文件上传前验证
  const beforeUpload = (file: File) => {
    // 检查文件扩展名
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!supportedExtensions.includes(fileExtension)) {
      message.error(`不支持的文件类型: ${fileExtension}。支持的类型: ${supportedExtensions.join(', ')}`);
      return false;
    }

    // 检查文件大小
    if (file.size > maxFileSize) {
      message.error(`文件大小不能超过 50MB`);
      return false;
    }

    return true;
  };

  // 自定义上传处理
  const customUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onProgress, onSuccess, onError } = options;
    
    setUploading(true);
    setUploadProgress(0);

    try {
      const formData = new FormData();
      formData.append('file', file as File);
      
      // 可选：添加项目名称和描述
      formData.append('project_name', `Project_${Date.now()}`);
      formData.append('description', 'C++项目代码分析');

      const xhr = new XMLHttpRequest();

      // 上传进度监听
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable) {
          const percent = Math.round((event.loaded / event.total) * 100);
          setUploadProgress(percent);
          onProgress?.({ percent });
        }
      });

      // 上传完成监听
      xhr.addEventListener('load', () => {
        if (xhr.status === 200) {
          try {
            const response: UploadResponse = JSON.parse(xhr.responseText);
            if (response.success) {
              message.success(response.message);
              
              // 添加到已上传文件列表
              setUploadedFiles(prev => [...prev, {
                ...response.file_info,
                project_id: response.project_id
              }]);
              
              onSuccess?.(response);
            } else {
              throw new Error(response.message);
            }
          } catch (parseError) {
            console.error('解析响应失败:', parseError);
            message.error('服务器响应格式错误');
            onError?.(parseError as Error);
          }
        } else {
          const errorMessage = `上传失败: HTTP ${xhr.status}`;
          message.error(errorMessage);
          onError?.(new Error(errorMessage));
        }
        
        setUploading(false);
        setUploadProgress(0);
      });

      // 上传错误监听
      xhr.addEventListener('error', () => {
        const errorMessage = '网络错误，上传失败';
        message.error(errorMessage);
        onError?.(new Error(errorMessage));
        setUploading(false);
        setUploadProgress(0);
      });

      // 发送请求
      xhr.open('POST', '/api/upload');
      xhr.send(formData);

    } catch (error) {
      console.error('上传异常:', error);
      message.error('上传过程中发生异常');
      onError?.(error as Error);
      setUploading(false);
      setUploadProgress(0);
    }
  };

  // 删除已上传文件
  const removeFile = (index: number) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index));
    message.success('文件已从列表中移除');
  };

  // 格式化文件大小
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="upload-container" style={{ padding: '20px' }}>
      <Title level={2}>
        <UploadOutlined /> 文件上传
      </Title>
      
      <Alert
        message="支持的文件类型"
        description={`C++源文件和头文件：${supportedExtensions.join(', ')}。单个文件最大50MB。`}
        type="info"
        showIcon
        style={{ marginBottom: '20px' }}
      />

      <Card title="选择文件上传" style={{ marginBottom: '20px' }}>
        <Dragger
          name="file"
          multiple={false}
          customRequest={customUpload}
          beforeUpload={beforeUpload}
          showUploadList={false}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <FileTextOutlined />
          </p>
          <p className="ant-upload-text">
            点击或拖拽文件到此区域上传
          </p>
          <p className="ant-upload-hint">
            支持C++源文件（.cpp, .cc, .cxx）和头文件（.h, .hpp）以及组成的压缩包(.zip, .tar, .tar.gz) 
          </p>
        </Dragger>

        {uploading && (
          <div style={{ marginTop: '20px' }}>
            <Text>上传中...</Text>
            <Progress 
              percent={uploadProgress} 
              status={uploadProgress === 100 ? 'success' : 'active'}
            />
          </div>
        )}
      </Card>

      {uploadedFiles.length > 0 && (
        <Card title={`已上传文件 (${uploadedFiles.length})`}>
          <List
            itemLayout="horizontal"
            dataSource={uploadedFiles}
            renderItem={(item, index) => (
              <List.Item
                actions={[
                  <Button 
                    type="link" 
                    danger 
                    icon={<DeleteOutlined />}
                    onClick={() => removeFile(index)}
                  >
                    移除
                  </Button>
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <FileTextOutlined 
                      style={{ 
                        fontSize: '24px', 
                        color: item.status === 'uploaded' ? '#52c41a' : '#faad14' 
                      }} 
                    />
                  }
                  title={
                    <Space>
                      <Text strong>{item.original_name}</Text>
                      <Tag color={item.status === 'uploaded' ? 'green' : 'orange'}>
                        {item.status === 'uploaded' ? '上传成功' : '处理中'}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size="small">
                      <Text type="secondary">
                        文件大小: {formatFileSize(item.size)} | 
                        类型: {item.extension} | 
                        项目ID: {item.project_id}
                      </Text>
                      <Text type="secondary">
                        上传时间: {new Date(item.upload_time).toLocaleString()}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />

          <Divider />
          
          <Alert
            message="下一步操作"
            description={
              <div>
                <Paragraph>
                  文件上传成功！在后续迭代中，您将能够：
                </Paragraph>
                <ul>
                  <li>📊 启动静态代码分析（迭代2）</li>
                  <li>🔄 执行动态运行时分析（迭代5）</li>
                  <li>🤖 获取AI增强的分析报告（迭代3）</li>
                  <li>🛠️ 查看智能修复建议（迭代7）</li>
                </ul>
              </div>
            }
            type="success"
            showIcon
          />
        </Card>
      )}

      <Card title="开发进度" style={{ marginTop: '20px' }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: '8px' }} />
            <Text>✅ 迭代1：基础框架搭建（当前）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#faad14', marginRight: '8px' }} />
            <Text type="secondary">⏳ 迭代2：静态分析Agent架构（开发中）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#d9d9d9', marginRight: '8px' }} />
            <Text type="secondary">📋 迭代3：多Agent协作系统（计划中）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#d9d9d9', marginRight: '8px' }} />
            <Text type="secondary">🔧 迭代4：编译系统集成（计划中）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#d9d9d9', marginRight: '8px' }} />
            <Text type="secondary">🚀 迭代5：动态分析系统（计划中）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#d9d9d9', marginRight: '8px' }} />
            <Text type="secondary">🤖 迭代6：智能修复系统（计划中）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#d9d9d9', marginRight: '8px' }} />
            <Text type="secondary">🔬 迭代7：系统集成优化（计划中）</Text>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ExclamationCircleOutlined style={{ color: '#d9d9d9', marginRight: '8px' }} />
            <Text type="secondary">🚢 迭代8：部署与文档（计划中）</Text>
          </div>
        </Space>
      </Card>

      <Card title="技术特性" style={{ marginTop: '20px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
          <div>
            <Title level={5}>🎯 多Agent架构</Title>
            <Text type="secondary">
              5个专业Agent协作：文件分析、缺陷检测、上下文分析、修复生成、验证代理
            </Text>
          </div>
          <div>
            <Title level={5}>🔍 双重分析</Title>
            <Text type="secondary">
              静态分析优先，动态分析验证，确保检测的全面性和准确性
            </Text>
          </div>
          <div>
            <Title level={5}>🤖 AI增强</Title>
            <Text type="secondary">
              集成GLM-4大语言模型，提供智能化的代码分析和修复建议
            </Text>
          </div>
          <div>
            <Title level={5}>⚡ 自动化流程</Title>
            <Text type="secondary">
              从代码上传到缺陷修复的全自动化工作流，提升开发效率
            </Text>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default FileUpload;
