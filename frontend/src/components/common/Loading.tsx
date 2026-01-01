import React from 'react';
import { Spin, Typography } from 'antd';

const { Text } = Typography;

interface LoadingProps {
  message?: string;
  size?: 'small' | 'default' | 'large';
}

const Loading: React.FC<LoadingProps> = ({ 
  message = '加载中...', 
  size = 'default' 
}) => {
  return (
    <div style={{ 
      display: 'flex', 
      flexDirection: 'column', 
      alignItems: 'center', 
      justifyContent: 'center',
      padding: '50px' 
    }}>
      <Spin size={size} />
      <Text style={{ marginTop: '16px', color: '#666' }}>
        {message}
      </Text>
    </div>
  );
};

export default Loading;
