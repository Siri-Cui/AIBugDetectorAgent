import os
from zhipuai import ZhipuAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_zhipu_api():
    """测试智谱AI API是否正常工作"""
    
    # 初始化客户端
    client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
    
    try:
        # 发送测试请求
        response = client.chat.completions.create(
            model="glm-4",  # 使用GLM-4模型
            messages=[
                {"role": "user", "content": "你好，请简单介绍一下你自己"}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        # 输出响应
        print("API调用成功！")
        print("回复内容：", response.choices[0].message.content)
        
    except Exception as e:
        print(f"API调用失败：{str(e)}")
        print("请检查：")
        print("1. API密钥是否正确")
        print("2. 网络连接是否正常")
        print("3. API账户是否有余额")

if __name__ == "__main__":
    test_zhipu_api()
