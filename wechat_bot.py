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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WXPUSHER_APP_TOKEN = os.environ.get("WXPUSHER_APP_TOKEN")
WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK")  # 保留企业微信Webhook

# 在这里直接填入您需要推送的 WxPusher UID 列表
TARGET_UIDS = [
    "UID_oOEfN5KNrbssY3INfSrtCJyNbJA1"
]

# 初始化客户端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

def summarize_with_gemini(sample_name, requirements, ai_advice):
    """使用 Gemini 提取简述和注意事项 (动态适配模型)"""
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
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

    # 2. 生成报告文本
    if not orders:
        content = "🎉 早上好！目前实验室没有积压的待测样品，大家辛苦了！"
        summary_title = "早报: 暂无待办任务"
    else:
        # 为了兼容 WxPusher 和 企业微信，使用标准的 Markdown 语法和通用颜色标签
        content = f"🌅 **【玉佳生物 - 实验室早报】**\n> 日期：<font color=\"info\">{datetime.now().strftime('%Y-%m-%d')}</font>\n> 待办任务总数：<font color=\"warning\">{len(orders)}批次</font>\n\n"
        summary_title = f"早报: 待办任务 {len(orders)} 批次"
        
        for order in orders:
            print(f"正在处理样品: {order['sample_name']}")
            brief = summarize_with_gemini(order['sample_name'], order['requirements'], order.get('ai_advice', '无'))
            
            content += f"**🧪 样品编号/名称：** {order['sample_name']}\n"
            content += f"**⏱️ 到样日期：** {order.get('arrival_date', '未知')}\n"
            content += f"**🎯 检测指标：** {order['requirements']}\n"
            content += f"<font color=\"comment\">{brief}</font>\n\n---\n"
            
        content += "\n💡 *具体详细流程，请登录 OMS 系统实验室看板查看。*"

    # ==========================================
    # 3. 双路发送模块
    # ==========================================

    # 路径 A: 推送到 WxPusher
    if WXPUSHER_APP_TOKEN:
        url_wx = "https://wxpusher.zjiecode.com/api/send/message"
        payload_wx = {
            "appToken": WXPUSHER_APP_TOKEN,
            "content": content,
            "summary": summary_title,
            "contentType": 3,
            "uids": TARGET_UIDS
        }
        try:
            res_wx = requests.post(url_wx, json=payload_wx)
            print("WxPusher 推送结果:", res_wx.text)
        except Exception as e:
            print(f"WxPusher 推送报错: {e}")

    # 路径 B: 推送到 企业微信
    if WECHAT_WEBHOOK:
        payload_wecom = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        headers = {'Content-Type': 'application/json'}
        try:
            res_wecom = requests.post(WECHAT_WEBHOOK, json=payload_wecom, headers=headers)
            print("企业微信 推送结果:", res_wecom.text)
        except Exception as e:
            print(f"企业微信 推送报错: {e}")

if __name__ == "__main__":
    send_daily_report()
