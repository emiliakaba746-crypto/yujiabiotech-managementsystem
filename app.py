import streamlit as st
import requests
import google.generativeai as genai
from supabase import create_client, Client

# ==========================================
# 1. 安全读取配置与初始化
# ==========================================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
WXPUSHER_UID = st.secrets["WXPUSHER_UID"]
WXPUSHER_APP_TOKEN = st.secrets["WXPUSHER_APP_TOKEN"]

# 初始化 Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# 初始化 Supabase 数据库连接
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# ==========================================
# 2. 核心功能函数
# ==========================================
def get_gemini_testing_advice(sample_name, requirements):
    """调用 Gemini API 生成测试安排与方法提示"""
    # 【修复】将模型从 gemini-1.5-flash 更改为最稳定兼容的 gemini-pro
    model = genai.GenerativeModel('gemini-pro')
    prompt = f"""
    作为玉佳生物科技的资深实验员，请根据以下样品信息提供测试建议：
    - 样品名称：{sample_name}
    - 客户测试要求：{requirements}
    请提供：1.推荐的测试方法 2.具体的测试流程 3.样品的保存条件及注意事项。
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 建议生成失败：{str(e)}"

def send_wxpusher_message(client, sample, requirements, advice):
    """调用 WxPusher 给您的微信发送消息，并返回发送结果状态"""
    url = "https://wxpusher.zjiecode.com/api/send/message"
    content = f"🔔【新样品到达】\n客户：{client}\n样品：{sample}\n要求：{requirements}\n\n🤖【AI建议提要】\n{advice[:150]}..."
    
    payload = {
        "appToken": WXPUSHER_APP_TOKEN,
        "content": content,
        "summary": f"新订单: {sample}",
        "contentType": 1,
        "uids": [WXPUSHER_UID]
    }
    
    try:
        response = requests.post(url, json=payload)
        result = response.json()
        # WxPusher 官方文档中，code为1000代表发送成功
        if result.get("code") == 1000:
            return True, "发送成功"
        else:
            return False, result.get("msg", "未知错误")
    except Exception as e:
        return False, f"网络请求错误: {str(e)}"

# ==========================================
# 3. Streamlit 界面路由
# ==========================================
st.set_page_config(page_title="玉佳生物订单系统", layout="wide")
st.sidebar.title("🧬 玉佳生物科技")
menu = st.sidebar.radio("工作台导航", ["业务接单大厅", "实验室检测看板", "财务核对中心"])

# --- 模块 1：业务接单大厅 ---
if menu == "业务接单大厅":
    st.header("📝 客户与样品录入")
    
    with st.form("order_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            client_name = st.text_input("客户名称 / 公司")
            contact_info = st.text_input("联系方式 (手机/微信)")
        with col2:
            sample_name = st.text_input("样品名称 / 编号")
            arrival_date = st.date_input("到样日期")
            
        requirements = st.text_area("详细测试要求")
        submitted = st.form_submit_button("生成订单 & 通知实验室")
        
        if submitted and client_name and sample_name:
            with st.spinner("正在呼叫 AI 助手并同步数据库..."):
                # 1. 获取 AI 建议
                ai_advice = get_gemini_testing_advice(sample_name, requirements)
                
                # 2. 存入数据库
                order_data = {
                    "client_name": client_name,
                    "contact_info": contact_info,
                    "sample_name": sample_name,
                    "arrival_date": str(arrival_date),
                    "requirements": requirements,
                    "ai_advice": ai_advice,
                    "status": "Pending"
                }
                
                try:
                    # 存入数据库
                    supabase.table("orders").insert(order_data).execute()
                    
                    # 3. 发送微信推送 (增加状态判断)
                    wx_success, wx_msg = send_wxpusher_message(client_name, sample_name, requirements, ai_advice)
                    
                    if wx_success:
                        st.success("✅ 订单创建成功！数据已入库，并已成功推送到您的微信。")
                    else:
                        st.warning(f"⚠️ 订单数据已入库，但微信推送失败。WxPusher提示：{wx_msg}（请确保您已微信扫码关注了 WxPusher 后台的'应用关注二维码'）")
                        
                    with st.expander("查看 AI 生成的初始测试方案"):
                        st.write(ai_advice)
                except Exception as e:
                    st.error(f"❌ 数据库保存失败: {str(e)}")

# --- 模块 2：实验室检测看板 ---
elif menu == "实验室检测看板":
    st.header("🔬 实验室样品处理")
    
    try:
        response = supabase.table("orders").select("*").neq("status", "Completed").order("id", desc=True).execute()
        orders = response.data
        
        if not orders:
            st.info("目前没有待处理的样品。")
        else:
            for order in orders:
                with st.container():
                    col_a, col_b, col_c = st.columns([2, 5, 2])
                    col_a.markdown(f"**样品：{order['sample_name']}**\n\n客户：{order['client_name']}")
                    col_b.markdown(f"**要求：** {order['requirements']}")
                    
                    status_options = ["Pending", "Processing", "Completed"]
                    current_idx = status_options.index(order['status']) if order['status'] in status_options else 0
                    new_status = col_c.selectbox("状态", status_options, index=current_idx, key=f"status_{order['id']}")
                    
                    if new_status != order['status']:
                        supabase.table("orders").update({"status": new_status}).eq("id", order['id']).execute()
                        st.rerun()
                    
                with st.expander("🤖 查看 AI 测试方案建议"):
                    st.markdown(order.get('ai_advice', '无'))
                st.divider()
    except Exception as e:
        st.error(f"加载数据失败: {str(e)}")

# --- 模块 3：财务核对中心 ---
elif menu == "财务核对中心":
    st.header("💰 账单与开票管理")
    st.write("此处显示已完工 (Completed) 的订单。")
    
    try:
        response = supabase.table("orders").select("*").eq("status", "Completed").order("id", desc=True).execute()
        orders = response.data
        
        if not orders:
            st.info("目前没有待结算的完工订单。")
        else:
            for order in orders:
                st.markdown(f"### 订单号：YJ-2026-{order['id']} (已完工)")
                st.markdown(f"**客户：** {order['client_name']} | **样品：** {order['sample_name']}")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.file_uploader(f"上传发票 (订单 {order['id']})", type=['pdf', 'jpg', 'png'], key=f"inv_{order['id']}")
                with col2:
                    st.file_uploader(f"上传测试清单 (订单 {order['id']})", type=['pdf', 'xlsx'], key=f"man_{order['id']}")
                st.divider()
    except Exception as e:
        st.error(f"加载数据失败: {str(e)}")
