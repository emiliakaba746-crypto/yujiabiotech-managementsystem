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
    """调用 Gemini API 生成测试安排与方法提示 (适配最新模型)"""
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        if not available_models:
            return "AI 建议生成失败：您的 API Key 没有访问任何文本生成模型的权限。请确认 Key 是否有效或欠费。"

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
                
        if not target_model_name:
            target_model_name = available_models[-1]

        target_model_name = target_model_name.replace('models/', '')

        model = genai.GenerativeModel(target_model_name)
        prompt = f"""
        作为玉佳生物科技的资深实验员，请根据以下样品信息提供测试建议：
        - 样品名称：{sample_name}
        - 客户测试要求：{requirements}
        请提供：1.推荐的测试方法 2.具体的测试流程 3.样品的保存条件及注意事项。
        """
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        debug_info = f"\n\n[排错信息] 尝试调用的模型: {target_model_name if 'target_model_name' in locals() else '未知'}\n当前 Key 支持的模型有: {available_models}" if 'available_models' in locals() else ""
        return f"AI 建议生成失败：{str(e)} {debug_info}"

def send_wxpusher_message(client, sample, requirements, advice):
    """调用 WxPusher 给您的微信发送完整、带排版的消息"""
    url = "https://wxpusher.zjiecode.com/api/send/message"
    
    content = f"""🔔 **【新样品到达】**
**客户：** {client}
**样品：** {sample}
**要求：** {requirements}

---

🤖 **【AI 测试方案建议】**

{advice}
"""
    
    payload = {
        "appToken": WXPUSHER_APP_TOKEN,
        "content": content,
        "summary": f"新订单: {sample}",
        "contentType": 3,  
        "uids": [WXPUSHER_UID]
    }
    
    try:
        response = requests.post(url, json=payload)
        result = response.json()
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
                ai_advice = get_gemini_testing_advice(sample_name, requirements)
                
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
                    supabase.table("orders").insert(order_data).execute()
                    wx_success, wx_msg = send_wxpusher_message(client_name, sample_name, requirements, ai_advice)
                    
                    if wx_success:
                        st.success("✅ 订单创建成功！数据已入库，并已成功推送到您的微信。")
                    else:
                        st.warning(f"⚠️ 订单数据已入库，但微信推送失败。WxPusher提示：{wx_msg}")
                        
                    with st.expander("查看 AI 生成的初始测试方案", expanded=True):
                        st.write(ai_advice)
                except Exception as e:
                    st.error(f"❌ 数据库保存失败: {str(e)}")

# --- 模块 2：实验室检测看板 ---
elif menu == "实验室检测看板":
    st.header("🔬 实验室样品处理看板")
    
    try:
        response = supabase.table("orders").select("*").neq("status", "Completed").order("id", desc=True).execute()
        orders = response.data
        
        if not orders:
            st.success("🎉 太棒了！目前没有积压的待处理样品。")
        else:
            pending_count = sum(1 for o in orders if o['status'] == 'Pending')
            processing_count = sum(1 for o in orders if o['status'] == 'Processing')
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("总待办任务", len(orders))
            col2.metric("🟡 待处理 (Pending)", pending_count)
            col3.metric("🔵 检测中 (Processing)", processing_count)
            
            st.divider()
            
            search_query = st.text_input("🔍 搜索样品名称或客户名称快速定位...", "")
            tab1, tab2, tab3 = st.tabs(["🟡 待处理任务", "🔵 检测中任务", "📋 全部待办总览"])
            
            def render_order_card(order, unique_key_suffix):
                if search_query:
                    if search_query.lower() not in order['sample_name'].lower() and search_query.lower() not in order['client_name'].lower():
                        return
                        
                with st.container(border=True):
                    col_a, col_b, col_c = st.columns([2.5, 4, 2])
                    
                    with col_a:
                        st.markdown(f"**🧪 {order['sample_name']}**")
                        st.caption(f"**客户：** {order['client_name']}")
                        st.caption(f"**到样日期：** {order.get('arrival_date', '未知')}")
                        
                    with col_b:
                        st.markdown("**测试要求：**")
                        st.info(order['requirements'])
                        
                    with col_c:
                        status_options = ["Pending", "Processing", "Completed"]
                        current_idx = status_options.index(order['status']) if order['status'] in status_options else 0
                        
                        new_status = st.selectbox(
                            "阶段变更", 
                            status_options, 
                            index=current_idx, 
                            key=f"status_{order['id']}_{unique_key_suffix}", 
                            label_visibility="collapsed" 
                        )
                        
                        if new_status != order['status']:
                            supabase.table("orders").update({"status": new_status}).eq("id", order['id']).execute()
                            st.toast(f"✅ {order['sample_name']} 的状态已更新为 {new_status}！") 
                            st.rerun()
                            
                    with st.expander("🤖 查看 AI 测试方案与注意事项"):
                        st.markdown(order.get('ai_advice', '暂无 AI 建议'))
                        
                    # 【核心新增】：数据上传与备注折叠面板
                    with st.expander("📤 上传检测结果 & 填写实验备注"):
                        col_u1, col_u2 = st.columns(2)
                        with col_u1:
                            lab_remarks = st.text_area(
                                "📝 实验结论 / 数据备注", 
                                value=order.get('lab_remarks', '') if order.get('lab_remarks') else '', 
                                placeholder="例如：A260/280比值为1.85，纯度合格...",
                                key=f"remark_{order['id']}_{unique_key_suffix}"
                            )
                        with col_u2:
                            uploaded_file = st.file_uploader(
                                "📁 上传原始数据 / 报告文件", 
                                type=['xlsx', 'csv', 'pdf', 'doc', 'docx', 'jpg'], 
                                key=f"file_{order['id']}_{unique_key_suffix}"
                            )
                            if order.get('data_file_name'):
                                st.caption(f"上次已登记文件: `{order['data_file_name']}`")

                        if st.button("💾 保存实验数据与备注", key=f"save_{order['id']}_{unique_key_suffix}"):
                            try:
                                update_data = {"lab_remarks": lab_remarks}
                                if uploaded_file:
                                    update_data["data_file_name"] = uploaded_file.name
                                    
                                supabase.table("orders").update(update_data).eq("id", order['id']).execute()
                                st.success("✅ 实验记录保存成功！")
                            except Exception as e:
                                st.error(f"❌ 保存失败，详细报错：{str(e)}")

            with tab1:
                for order in orders:
                    if order['status'] == 'Pending':
                        render_order_card(order, "tab1")
                        
            with tab2:
                for order in orders:
                    if order['status'] == 'Processing':
                        render_order_card(order, "tab2")
                        
            with tab3:
                for order in orders:
                    render_order_card(order, "tab3")
                    
    except Exception as e:
        st.error(f"加载实验室数据失败，请检查网络或数据库配置: {str(e)}")

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
