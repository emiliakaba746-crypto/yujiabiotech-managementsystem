import streamlit as st
import requests
import google.generativeai as genai
from supabase import create_client, Client

# ==========================================
# 0. 页面基础配置 (必须放在第一行)
# ==========================================
st.set_page_config(page_title="玉佳生物订单系统", layout="wide")

# ==========================================
# 1. 安全读取配置与初始化
# ==========================================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
WECHAT_WEBHOOK = st.secrets.get("WECHAT_WEBHOOK", "")

genai.configure(api_key=GEMINI_API_KEY)

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# ==========================================
# 2. 员工账号与权限配置中心
# ==========================================
USERS = {
    "2500": {"name": "Kevin", "menus": ["业务接单大厅", "实验室检测看板", "财务核对中心"], "actions": ["create_order", "update_lab", "update_finance"]},
    "2501": {"name": "周翠莹", "menus": ["业务接单大厅", "实验室检测看板", "财务核对中心"], "actions": ["create_order", "update_finance"]},
    "2502": {"name": "汪孝亮", "menus": ["业务接单大厅", "实验室检测看板", "财务核对中心"], "actions": ["update_lab"]},
    "2601": {"name": "周海迪", "menus": ["业务接单大厅", "实验室检测看板", "财务核对中心"], "actions": ["create_order"]},
    "2602": {"name": "吴班坤", "menus": ["实验室检测看板"], "actions": ["update_lab"]},
    "2603": {"name": "林伟雄", "menus": ["业务接单大厅", "实验室检测看板", "财务核对中心"], "actions": ["create_order"]}
}

if "current_user" not in st.session_state:
    st.session_state.current_user = None

# ==========================================
# 3. 登录拦截页面
# ==========================================
if st.session_state.current_user is None:
    st.title("🔒 欢迎登录玉佳生物订单管理系统")
    st.divider()
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.container(border=True):
            st.subheader("👨‍💻 员工登录")
            emp_id = st.selectbox(
                "请选择员工账号:", 
                options=list(USERS.keys()), 
                format_func=lambda x: f"{USERS[x]['name']} (工号: {x})"
            )
            password = st.text_input("密码 (Password):", type="password", placeholder="首次登录输入的内容将自动设为永久密码")
            
            if st.button("登 录", type="primary", use_container_width=True):
                if emp_id in USERS:
                    try:
                        res = supabase.table("employees").select("*").eq("emp_id", emp_id).execute()
                        if not res.data:
                            if len(password) < 4:
                                st.warning("⚠️ 这是您的首次登录，请设置一个至少 4 位的密码！")
                            else:
                                supabase.table("employees").insert({"emp_id": emp_id, "password": password}).execute()
                                st.success("✅ 首次登录，密码已成功设置并绑定！")
                                st.session_state.current_user = USERS[emp_id]
                                st.rerun()
                        else:
                            db_password = res.data[0]["password"]
                            if password == db_password:
                                st.session_state.current_user = USERS[emp_id]
                                st.rerun()
                            else:
                                st.error("❌ 密码错误，请重新输入！")
                    except Exception as e:
                        st.error(f"数据库连接异常: {str(e)}")
                else:
                    st.error("❌ 工号不存在！")
    st.stop()

user = st.session_state.current_user

# ==========================================
# 4. 核心功能函数
# ==========================================
def get_gemini_testing_advice(sample_name, requirements):
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not available_models: return "AI 建议生成失败：API Key 权限异常。"
        target_model_name = ""
        preferred_models = ['models/gemini-flash-latest', 'models/gemini-3.6-flash', 'models/gemini-3.5-flash']
        for pref in preferred_models:
            if pref in available_models:
                target_model_name = pref; break
        if not target_model_name: target_model_name = available_models[-1]
        target_model_name = target_model_name.replace('models/', '')
        
        model = genai.GenerativeModel(target_model_name)
        prompt = f"""作为玉佳生物科技的资深实验员，请根据以下信息提供建议：样品：{sample_name} 要求：{requirements}。请提供：1.测试方法 2.测试流程 3.保存条件。"""
        response = model.generate_content(prompt, request_options={"timeout": 10})
        return response.text
    except Exception as e:
        return f"AI 建议生成因网络或限流已跳过。"

# 【更新】：推送消息加入定金和尾款显示
def send_new_order_notifications(order_no, client, sample, requirements, advice, amount, deposit, creator):
    balance = amount - deposit
    content = f"""🔔 **【新样品到达】**
> **订单编号：** <font color="info">{order_no}</font>
> **接单员：** {creator}
> **客户：** {client}
> **样品：** {sample}
> **财务状态：** 订单总额 ¥{amount} (已付定金 ¥{deposit} | 待收尾款 <font color="warning">¥{balance}</font>)
> **要求：** {requirements}

---
🤖 **【AI 测试方案建议】**
<font color="comment">{advice}</font>
"""
    results = []
    
    if WECHAT_WEBHOOK:
        payload_wecom = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
        headers = {'Content-Type': 'application/json'}
        try:
            res_wecom = requests.post(WECHAT_WEBHOOK, json=payload_wecom, headers=headers, timeout=5)
            if res_wecom.status_code == 200:
                results.append("✅ 企业微信群通知已发送")
            else:
                results.append(f"❌ 企微群失败(码:{res_wecom.status_code})")
        except Exception as e:
            results.append(f"❌ 企微网络超时")
    else:
        results.append("⚠️ 企业微信机器人未配置")

    return True, " | ".join(results)

# ==========================================
# 5. Streamlit 界面路由
# ==========================================
st.sidebar.title("🧬 玉佳生物科技")
st.sidebar.markdown(f"👋 **欢迎, {user['name']}**")

menu = st.sidebar.radio("工作台导航", user["menus"])

st.sidebar.divider()
if st.sidebar.button("🚪 退出登录"):
    st.session_state.current_user = None
    st.rerun()

# --- 模块 1：业务接单大厅 ---
if menu == "业务接单大厅":
    st.header("📝 客户与样品录入")
    
    if "create_order" not in user["actions"]:
        st.info("💡 您的权限级别为【只读】。无权在此录入新订单。")
    else:
        with st.form("order_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                client_name = st.text_input("客户名称 / 公司")
                contact_info = st.text_input("联系方式 (手机/微信)")
                # 【新增】：定金输入框
                st.markdown("---")
                amount = st.number_input("💰 订单总金额 (元)", min_value=0.0, value=0.0, step=100.0)
                deposit = st.number_input("💵 已付定金金额 (元)", min_value=0.0, value=0.0, step=100.0)
            with col2:
                sample_name = st.text_input("样品名称 (系统将自动生成订单编号)")
                arrival_date = st.date_input("到样日期")
                
            st.markdown("---")
            requirements = st.text_area("详细测试要求")
            submitted = st.form_submit_button("生成订单 & 通知实验室")
            
            if submitted and client_name and sample_name:
                if deposit > amount:
                    st.error("❌ 录入错误：已付定金不能大于订单总金额！")
                else:
                    with st.spinner("正在生成方案并同步数据库，请稍候..."):
                        ai_advice = get_gemini_testing_advice(sample_name, requirements)
                        
                        order_data = {
                            "client_name": client_name, "contact_info": contact_info, "sample_name": sample_name,
                            "arrival_date": str(arrival_date), "requirements": requirements, "ai_advice": ai_advice,
                            "status": "Pending", "amount": amount, "deposit": deposit, "is_paid": False, 
                            "has_test_list": False, "has_invoice": False, "creator_name": user["name"] 
                        }
                        try:
                            res = supabase.table("orders").insert(order_data).execute()
                            if res.data and len(res.data) > 0:
                                inserted_id = res.data[0]['id']
                                auto_order_no = f"YJ-{inserted_id:05d}"
                                
                                _, push_msg = send_new_order_notifications(auto_order_no, client_name, sample_name, requirements, ai_advice, amount, deposit, user["name"])
                                
                                st.success(f"✅ 订单创建成功！系统编号：**{auto_order_no}**")
                                st.info(f"状态: {push_msg}")
                                
                                with st.expander("查看 AI 生成的初始测试方案", expanded=False):
                                    st.write(ai_advice)
                            else:
                                st.error("❌ 数据库保存失败。")
                        except Exception as e:
                            st.error(f"❌ 异常: {str(e)}")

# --- 模块 2：实验室检测看板 ---
elif menu == "实验室检测看板":
    st.header("🔬 实验室样品处理看板")
    can_update_lab = "update_lab" in user["actions"]
    
    if not can_update_lab:
        st.info("💡 您的权限级别为【只读】。")
        
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
                    display_order_no = f"YJ-{order['id']:05d}"
                    
                    with col_a:
                        st.markdown(f"**🧾 {display_order_no}**")
                        st.markdown(f"**🧪 {order['sample_name']}**")
                        # 【更新】：实验室看板简单展示财务状态
                        balance = order.get('amount', 0) - order.get('deposit', 0)
                        st.caption(f"客户：{order['client_name']} | 总额: ¥{order.get('amount', 0)} (定金: ¥{order.get('deposit', 0)})")
                        st.caption(f"到样：{order.get('arrival_date', '未知')} | 接单员：**{order.get('creator_name', '未知')}**")
                    with col_b:
                        st.markdown("**测试要求：**")
                        st.info(order['requirements'])
                    with col_c:
                        status_opts = ["Pending", "Processing", "Completed"]
                        cur_idx = status_opts.index(order['status']) if order['status'] in status_opts else 0
                        new_status = st.selectbox("阶段变更", status_opts, index=cur_idx, key=f"status_{order['id']}_{unique_key_suffix}", label_visibility="collapsed", disabled=not can_update_lab)
                        if new_status != order['status'] and can_update_lab:
                            supabase.table("orders").update({"status": new_status}).eq("id", order['id']).execute()
                            st.rerun()
                    
                    if can_update_lab:
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
                    else:
                        if order.get('lab_remarks') or order.get('data_file_name'):
                            with st.expander("👀 查看已有实验记录"):
                                if order.get('lab_remarks'): st.write(f"**备注:** {order['lab_remarks']}")
                                if order.get('data_file_name'): st.caption(f"已存档文件: `{order['data_file_name']}`")

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
    st.header("💰 账单与业绩看板")
    
    can_update_finance = "update_finance" in user["actions"]
    if not can_update_finance:
        st.info("💡 您的权限级别为【只读】。您可以看到财务数据汇总，但无法勾选收款和单据状态。")
        
    try:
        response = supabase.table("orders").select("*").order("id", desc=True).execute()
        all_orders = response.data
        
        st.subheader("🏆 团队接单业绩统计")
        sales_stats = {}
        for o in all_orders:
            creator = o.get('creator_name') or '系统历史单'
            amt = o.get('amount', 0) or 0
            dep = o.get('deposit', 0) or 0
            
            if creator not in sales_stats:
                sales_stats[creator] = {"count": 0, "total_amt": 0, "collected_amt": 0}
            
            sales_stats[creator]["count"] += 1
            sales_stats[creator]["total_amt"] += amt
            
            # 业绩中已收账款的逻辑：如果已收全款(is_paid为真)，则为总金额；否则为已付定金
            if o.get('is_paid'):
                sales_stats[creator]["collected_amt"] += amt
            else:
                sales_stats[creator]["collected_amt"] += dep
                
        if sales_stats:
            stats_list = []
            for k, v in sales_stats.items():
                stats_list.append({
                    "接单员姓名": k,
                    "接单数量": v["count"],
                    "创造总业绩 (元)": f"¥ {v['total_amt']:,.2f}",
                    "已收账款 (包含定金)": f"¥ {v['collected_amt']:,.2f}",
                    "待收尾款总计": f"¥ {v['total_amt'] - v['collected_amt']:,.2f}"
                })
            st.dataframe(stats_list, use_container_width=True)
        else:
            st.info("暂无业绩数据")
            
        st.divider()

        st.subheader("🏢 公司总体财务概况")
        total_revenue = sum(o.get('amount', 0) or 0 for o in all_orders)
        # 公司总收款 = 所有已结清的订单总额 + 所有未结清订单的定金总额
        collected_revenue = sum(o.get('amount', 0) if o.get('is_paid') else o.get('deposit', 0) for o in all_orders)
        uncollected_revenue = total_revenue - collected_revenue
        
        col1, col2, col3 = st.columns(3)
        col1.metric("📊 累计订单总额", f"¥ {total_revenue:,.2f}")
        col2.metric("✅ 已收账款总额 (含定金)", f"¥ {collected_revenue:,.2f}")
        col3.metric("⏳ 待收尾款总额", f"¥ {uncollected_revenue:,.2f}")
        
        st.divider()
        st.write("### 待结算 / 已完工订单清单")
        
        completed_orders = [o for o in all_orders if o.get('status') == 'Completed']
        
        if not completed_orders:
            st.info("目前没有已完工的订单。")
        else:
            for order in completed_orders:
                with st.container(border=True):
                    display_order_no = f"YJ-{order['id']:05d}"
                    balance = order.get('amount', 0) - order.get('deposit', 0)
                    
                    st.markdown(f"**订单号：{display_order_no}** | 客户：{order['client_name']} | 样品：{order['sample_name']} | 接单员：{order.get('creator_name', '未知')}")
                    # 【更新】：在财务单显示详细的金额组成
                    st.markdown(f"**订单总计：** ¥ {order.get('amount', 0)} | **已付定金：** ¥ {order.get('deposit', 0)} | **待收尾款：** <font color='red'>**¥ {balance}**</font>", unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        # 如果勾选此项，代表尾款已经结清
                        new_is_paid = st.checkbox("✅ 确认已收全款 (结清尾款)", value=order.get('is_paid', False), key=f"paid_{order['id']}", disabled=not can_update_finance)
                    with c2:
                        new_has_test_list = st.checkbox("📑 已开测试清单", value=order.get('has_test_list', False), key=f"testlist_{order['id']}", disabled=not can_update_finance)
                    with c3:
                        new_has_invoice = st.checkbox("🧾 已开发票", value=order.get('has_invoice', False), key=f"invoice_{order['id']}", disabled=not can_update_finance)
                    
                    if can_update_finance:
                        if new_is_paid != order.get('is_paid', False) or new_has_test_list != order.get('has_test_list', False) or new_has_invoice != order.get('has_invoice', False):
                            supabase.table("orders").update({"is_paid": new_is_paid, "has_test_list": new_has_test_list, "has_invoice": new_has_invoice}).eq("id", order['id']).execute()
                            st.rerun() 
                            
    except Exception as e:
        st.error(f"加载数据失败: {str(e)}")
