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

genai.configure(api_key=GEMINI_API_KEY)

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# ==========================================
# 2. 核心功能函数
# ==========================================
def get_gemini_testing_advice(sample_name, requirements):
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not available_models:
            return "AI 建议生成失败：API Key 权限异常。"

        target_model_name = ""
        preferred_models = ['models/gemini-flash-latest', 'models/gemini-3.6-flash', 'models/gemini-3.5-flash']
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
        return f"AI 建议生成失败：{str(e)}"

def send_wxpusher_message(client, sample, requirements, advice, amount):
    url = "https://wxpusher.zjiecode.com/api/send/message"
    content = f"""🔔 **【新样品到达】**
**客户：** {client}
**样品：** {sample}
**金额：** ¥{amount}
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
        return response.json().get("code") == 1000, response.json().get("msg")
    except Exception as e:
        return False, str(e)

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
            amount = st.number_input("订单金额 (元)", min_value=0.0, value=0.0, step=100.0) # 【新增】金额录入
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
                    "status": "Pending",
                    "amount": amount,              # 【新增】存入金额
                    "is_paid": False,              # 【新增】默认未收款
                    "has_test_list": False,        # 【新增】默认未开清单
                    "has_invoice": False           # 【新增】默认未开发票
                }
                
                try:
                    supabase.table("orders").insert(order_data).execute()
                    wx_success, wx_msg = send_wxpusher_message(client_name, sample_name, requirements, ai_advice, amount)
                    
                    if wx_success:
                        st.success("✅ 订单创建成功！数据已入库，并已成功推送到您的微信。")
                    else:
                        st.warning(f"⚠️ 订单已入库，但微信推送失败。WxPusher提示：{wx_msg}")
                        
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
            col2.metric("🟡 待处理", pending_count)
            col3.metric("🔵 检测中", processing_count)
            st.divider()
            
            search_query = st.text_input("🔍 搜索快速定位...", "")
            tab1, tab2, tab3 = st.tabs(["🟡 待处理", "🔵 检测中", "📋 全部待办"])
            
            def render_order_card(order, unique_key_suffix):
                if search_query and search_query.lower() not in order['sample_name'].lower() and search_query.lower() not in order['client_name'].lower():
                    return
                with st.container(border=True):
                    col_a, col_b, col_c = st.columns([2.5, 4, 2])
                    with col_a:
                        st.markdown(f"**🧪 {order['sample_name']}**")
                        st.caption(f"客户：{order['client_name']} | 金额: ¥{order.get('amount', 0)}")
                        st.caption(f"到样：{order.get('arrival_date', '未知')}")
                    with col_b:
                        st.markdown("**测试要求：**")
                        st.info(order['requirements'])
                    with col_c:
                        status_opts = ["Pending", "Processing", "Completed"]
                        cur_idx = status_opts.index(order['status']) if order['status'] in status_opts else 0
                        new_status = st.selectbox("阶段变更", status_opts, index=cur_idx, key=f"status_{order['id']}_{unique_key_suffix}", label_visibility="collapsed")
                        if new_status != order['status']:
                            supabase.table("orders").update({"status": new_status}).eq("id", order['id']).execute()
                            st.rerun()
                            
                    with st.expander("📤 上传检测结果 & 填写实验备注"):
                        col_u1, col_u2 = st.columns(2)
                        with col_u1:
                            lab_remarks = st.text_area("📝 实验备注", value=order.get('lab_remarks', ''), key=f"remark_{order['id']}_{unique_key_suffix}")
                        with col_u2:
                            uploaded_file = st.file_uploader("📁 上传文件", key=f"file_{order['id']}_{unique_key_suffix}")
                            if order.get('data_file_name'): st.caption(f"已存文件: `{order['data_file_name']}`")
                        if st.button("💾 保存实验数据", key=f"save_{order['id']}_{unique_key_suffix}"):
                            update_data = {"lab_remarks": lab_remarks}
                            if uploaded_file: update_data["data_file_name"] = uploaded_file.name
                            supabase.table("orders").update(update_data).eq("id", order['id']).execute()
                            st.success("✅ 保存成功！")

            with tab1:
                for o in [o for o in orders if o['status'] == 'Pending']: render_order_card(o, "tab1")
            with tab2:
                for o in [o for o in orders if o['status'] == 'Processing']: render_order_card(o, "tab2")
            with tab3:
                for o in orders: render_order_card(o, "tab3")
    except Exception as e:
        st.error(f"加载失败: {str(e)}")

# --- 模块 3：财务核对中心 ---
elif menu == "财务核对中心":
    st.header("💰 账单与开票管理")
    
    try:
        # 获取所有订单用于计算总额
        response = supabase.table("orders").select("*").order("id", desc=True).execute()
        all_orders = response.data
        
        # 【新增】计算各项财务指标
        total_revenue = sum(o.get('amount', 0) or 0 for o in all_orders)
        collected_revenue = sum(o.get('amount', 0) or 0 for o in all_orders if o.get('is_paid'))
        uncollected_revenue = total_revenue - collected_revenue
        
        # 【新增】顶部财务指标看板
        col1, col2, col3 = st.columns(3)
        col1.metric("📊 累计订单总额", f"¥ {total_revenue:,.2f}")
        col2.metric("✅ 已收账款", f"¥ {collected_revenue:,.2f}")
        col3.metric("⏳ 待收账款", f"¥ {uncollected_revenue:,.2f}")
        
        st.divider()
        st.write("### 待结算 / 已完工订单清单")
        
        # 过滤出已完成的订单在下方展示
        completed_orders = [o for o in all_orders if o.get('status') == 'Completed']
        
        if not completed_orders:
            st.info("目前没有已完工的订单。")
        else:
            for order in completed_orders:
                with st.container(border=True):
                    st.markdown(f"**订单号：YJ-2026-{order['id']}** | 客户：{order['client_name']} | 样品：{order['sample_name']}")
                    st.markdown(f"**订单金额：** <font color='red'>**¥ {order.get('amount', 0)}**</font>", unsafe_allow_html=True)
                    
                    # 【新增】财务勾选状态同步
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        new_is_paid = st.checkbox("✅ 确认已收款", value=order.get('is_paid', False), key=f"paid_{order['id']}")
                    with c2:
                        new_has_test_list = st.checkbox("📑 已开测试清单", value=order.get('has_test_list', False), key=f"testlist_{order['id']}")
                    with c3:
                        new_has_invoice = st.checkbox("🧾 已开发票", value=order.get('has_invoice', False), key=f"invoice_{order['id']}")
                    
                    # 如果状态有任何改变，自动更新数据库并刷新页面
                    if new_is_paid != order.get('is_paid', False) or \
                       new_has_test_list != order.get('has_test_list', False) or \
                       new_has_invoice != order.get('has_invoice', False):
                        
                        supabase.table("orders").update({
                            "is_paid": new_is_paid,
                            "has_test_list": new_has_test_list,
                            "has_invoice": new_has_invoice
                        }).eq("id", order['id']).execute()
                        
                        st.rerun() # 触发页面刷新，更新顶部的总金额统计
                        
    except Exception as e:
        st.error(f"加载数据失败: {str(e)}")
