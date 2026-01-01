import React from 'react';
import { Layout } from 'antd';

const { Content } = Layout;

interface LayoutProps {
  children: React.ReactNode;
}

const CommonLayout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Content style={{ padding: '24px' }}>
        {children}
      </Content>
    </Layout>
  );
};

export default CommonLayout;
