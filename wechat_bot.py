import os
import requests
import google.generativeai as genai
from supabase import create_client, Client
from datetime import datetime

# ==========================================
# 1. 读取环境变量 (GitHub Actions 会注入这些变量)
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 初始化客户端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

def summarize_with_gemini(sample_name, requirements, ai_advice):
    """使用 Gemini 提取简述和注意事项 (动态适配模型)"""
    try:
        # 1. 自动探测当前 API Key 支持的模型列表
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # 2. 智能选择最新可用模型
        target_model_name = ""
        preferred_models = [
            'models/gemini-flash-latest', 
            'models/gemini-3.6-flash',
            'models/gemini-3.5-flash'
        ]
        
        for pref in preferred_models:
            if pref in available_models:
                target_model_name = pref
                break
                
        if not target_model_name and available_models:
            target_model_name = available_models[-1]

        if not target_model_name:
            raise Exception("No available models found")

        target_model_name = target_model_name.replace('models/', '')
        
        # 3. 发送请求
        model = genai.GenerativeModel(target_model_name)
        prompt = f"""
        你是一个实验室主管。请根据以下信息，用极其简短的语言（限50字以内）总结检测方法和最关键的安全注意事项：
        样品：{sample_name}
        要求：{requirements}
        已有方案参考：{ai_advice}
        
        格式要求（必须严格遵守以下格式，不要多余废话）：
        - 方法简述：xxx
        - 注意事项：xxx
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        # 打印错误到后台日志方便排查
        print(f"AI 生成失败: {e}")
        return f"- 方法简述：详见系统原方案\n- 注意事项：请遵循标准实验室规范"

def send_daily_report():
    # 1. 从 Supabase 获取未完成的订单
    try:
        response = supabase.table("orders").select("*").neq("status", "Completed").execute()
        orders = response.data
    except Exception as e:
        print(f"获取数据失败: {e}")
        return

    if not orders:
        content = "🎉 早上好！目前实验室没有积压的待测样品，大家辛苦了！"
    else:
        content = f"🌅 **【玉佳生物 - 实验室早报】**\n> 日期：<font color=\"info\">{datetime.now().strftime('%Y-%m-%d')}</font>\n> 待办任务总数：<font color=\"warning\">{len(orders)}批次</font>\n\n"
        
        # 2. 遍历订单，生成报告内容
        for order in orders:
            print(f"正在处理样品: {order['sample_name']}")
            # 获取 AI 简述
            brief = summarize_with_gemini(order['sample_name'], order['requirements'], order.get('ai_advice', '无'))
            
            # 企业微信 Markdown 格式拼接
            content += f"**🧪 样品编号/名称：** {order['sample_name']}\n"
            content += f"**⏱️ 到样日期：** {order.get('arrival_date', '未知')}\n"
            content += f"**🎯 检测指标：** {order['requirements']}\n"
            content += f"<font color=\"comment\">{brief}</font>\n\n---\n"
            
        content += "\n💡 *具体详细流程，请登录 OMS 系统实验室看板查看。*"

    # 3. 发送到企业微信机器人
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": content
        }
    }
    
    headers = {'Content-Type': 'application/json'}
    res = requests.post(WECHAT_WEBHOOK, json=payload, headers=headers)
    print("推送结果:", res.text)

if __name__ == "__main__":
    send_daily_report()
