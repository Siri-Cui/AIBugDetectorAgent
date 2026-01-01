import React, { useState, useEffect } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import {
  Layout,
  Menu,
  Typography,
  Button,
  Space,
  message,
  Spin
} from 'antd';
import {
  HomeOutlined,
  UploadOutlined,
  FileSearchOutlined,
  SettingOutlined,
  GithubOutlined,
  LineChartOutlined as AnalysisOutlined,
} from '@ant-design/icons';

import FileUpload from './components/upload/FileUpload';
import './App.css';

const { Header, Sider, Content, Footer } = Layout;
const { Title, Text } = Typography;

interface SystemInfo {
  name: string;
  version: string;
  status: string;
  uptime?: string;
  supported_agents: string[];
  workflow: string;
}

const App: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();          // ✅ 改动1：读取当前路径
  const [collapsed, setCollapsed] = useState(false);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);

  // 菜单项配置（原样保留）
  const menuItems = [
    { key: '/', icon: <HomeOutlined />, label: '首页' },
    { key: '/upload', icon: <UploadOutlined />, label: '文件上传' },
    { key: '/analysis', icon: <AnalysisOutlined />, label: '分析中心', disabled: true },
    { key: '/results', icon: <FileSearchOutlined />, label: '结果查看', disabled: true },
    { key: '/settings', icon: <SettingOutlined />, label: '系统设置', disabled: true },
    { key: '/docs', icon: <FileSearchOutlined />, label: 'API文档' },
    { key: '/health', icon: <SettingOutlined />, label: '系统状态' },
  ];

  // 获取系统信息（原样保留）
  useEffect(() => {
    const fetchSystemInfo = async () => {
      try {
        const response = await fetch('http://101.43.50.74:8000/');
        const data = await response.json();
        setSystemInfo(data);
        message.success('系统连接正常');
      } catch (error) {
        console.error('获取系统信息失败:', error);
        message.error('无法连接到后端服务，请检查服务器状态');
      } finally {
        setLoading(false);
      }
    };
    fetchSystemInfo();
  }, []);

  // 菜单点击处理（原样保留）
  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
  };

  // 主页内容（原样保留）
  const HomePage: React.FC = () => (
    <div className="home-content">
      <div className="hero-section">
        <Title level={1}>🤖 AI Agent缺陷检测系统</Title>
        <Text type="secondary" style={{ fontSize: '18px' }}>
          基于多Agent协作的C++代码缺陷检测系统
        </Text>

        {systemInfo && (
          <div className="system-info" style={{ marginTop: '30px' }}>
            <Title level={3}>系统信息</Title>
            <div className="info-grid">
              <div className="info-item">
                <Text strong>系统版本：</Text>
                <Text>{systemInfo.version}</Text>
              </div>
              <div className="info-item">
                <Text strong>运行状态：</Text>
                <Text style={{ color: systemInfo.status === 'running' ? '#52c41a' : '#ff4d4f' }}>
                  {systemInfo.status === 'running' ? '正常运行' : '异常'}
                </Text>
              </div>
              {systemInfo.uptime && (
                <div className="info-item">
                  <Text strong>运行时间：</Text>
                  <Text>{systemInfo.uptime}</Text>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="features-section" style={{ marginTop: '40px' }}>
          <Title level={3}>核心特性</Title>
          <div className="features-grid">
            <div className="feature-card">
              <AnalysisOutlined style={{ fontSize: '32px', color: '#1890ff' }} />
              <Title level={4}>多Agent协作</Title>
              <Text>5个专业Agent分工协作，提供全面的代码分析</Text>
            </div>
            <div className="feature-card">
              <FileSearchOutlined style={{ fontSize: '32px', color: '#52c41a' }} />
              <Title level={4}>双重分析</Title>
              <Text>静态分析+动态分析，全方位检测代码缺陷</Text>
            </div>
            <div className="feature-card">
              <GithubOutlined style={{ fontSize: '32px', color: '#722ed1' }} />
              <Title level={4}>AI增强</Title>
              <Text>GLM-4大模型智能分析，提供修复建议</Text>
            </div>
          </div>
        </div>

        <div className="workflow-section" style={{ marginTop: '40px' }}>
          <Title level={3}>分析工作流</Title>
          {systemInfo && (
            <Text className="workflow-text">{systemInfo.workflow}</Text>
          )}
        </div>

        <div className="action-section" style={{ marginTop: '40px' }}>
          <Space size="large">
            <Button
              type="primary"
              size="large"
              icon={<UploadOutlined />}
              onClick={() => navigate('/upload')}
            >
              开始上传文件
            </Button>
            <Button
              size="large"
              onClick={() => navigate('/docs')}
            >
              API文档
            </Button>
            <Button
              size="large"
              onClick={() => navigate('/health')}
            >
              系统状态
            </Button>
          </Space>
        </div>
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="loading-container">
        <Spin size="large" />
        <div style={{ marginTop: '20px' }}>正在连接系统...</div>
      </div>
    );
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
      >
        <div className="logo">
          <Title level={4} style={{ color: 'white', margin: '16px' }}>
            {collapsed ? 'AI' : 'AI Agent'}
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}   // ✅ 改动2：高亮跟随路由
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Sider>

      <Layout>
        <Header className="site-layout-header">
          <div className="header-content">
            <Title level={3} style={{ margin: 0, color: 'white' }}>
              AI Agent缺陷检测系统
            </Title>
            <div className="header-actions">
              <Space>
                <Button
                  type="link"
                  style={{ color: 'white' }}
                  onClick={() => navigate('/docs')}
                >
                  API文档
                </Button>
                <Button
                  type="link"
                  style={{ color: 'white' }}
                  onClick={() => navigate('/health')}
                >
                  系统状态
                </Button>
              </Space>
            </div>
          </div>
        </Header>

        <Content className="site-layout-content">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/upload" element={<FileUpload />} />
            {/* ✅ 改动3-4：新增两条内嵌路由 */}
            <Route path="/docs" element={
              <iframe
                src="http://101.43.50.74:8000/docs"
                style={{ width: '100%', height: 'calc(100vh - 120px)', border: 0 }}
              />
            } />
            <Route path="/health" element={
              <iframe
                src="http://101.43.50.74:8000/health"
                style={{ width: '100%', height: 'calc(100vh - 120px)', border: 0 }}
              />
            } />
            <Route path="/analysis" element={
              <div style={{ padding: '50px', textAlign: 'center' }}>
                <Title level={3}>分析功能开发中</Title>
                <Text>此功能将在迭代2中实现</Text>
              </div>
            } />
            <Route path="/results" element={
              <div style={{ padding: '50px', textAlign: 'center' }}>
                <Title level={3}>结果查看功能开发中</Title>
                <Text>此功能将在迭代3中实现</Text>
              </div>
            } />
          </Routes>
        </Content>

        <Footer className="site-footer">
          <div style={{ textAlign: 'center' }}>
            <Text type="secondary">
              AI Agent缺陷检测系统 ©2024 - 迭代1：基础框架
            </Text>
            <br />
            <Text type="secondary" style={{ fontSize: '12px' }}>
              当前版本：{systemInfo?.version || '1.0.0'} |
              状态：{systemInfo?.status === 'running' ? '正常运行' : '异常'} |
              支持的文件类型：.cpp, .hpp, .h, .c, .cc, .cxx, .zip, .tar, .tar.gz
            </Text>
          </div>
        </Footer>
      </Layout>
    </Layout>
  );
};

export default App;
