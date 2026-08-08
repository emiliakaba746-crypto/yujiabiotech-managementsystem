import streamlit as st
import requests
import google.generativeai as genai
from supabase import create_client, Client
import csv              
import io               
from datetime import datetime 
import pandas as pd     

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
    "2500": {"name": "Kevin", "menus": ["业务接单大厅", "耗材销售大厅", "实验室检测看板", "财务核对中心", "数据统计看板"], "actions": ["create_order", "update_lab", "update_finance"]},
    "2501": {"name": "周翠莹", "menus": ["业务接单大厅", "耗材销售大厅", "实验室检测看板", "财务核对中心", "数据统计看板"], "actions": ["create_order", "update_finance"]},
    "2502": {"name": "汪孝亮", "menus": ["业务接单大厅", "实验室检测看板", "财务核对中心", "数据统计看板"], "actions": ["update_lab"]},
    "2601": {"name": "周海迪", "menus": ["业务接单大厅", "耗材销售大厅", "实验室检测看板", "财务核对中心", "数据统计看板"], "actions": ["create_order"]},
    "2602": {"name": "吴班坤", "menus": ["实验室检测看板", "数据统计看板"], "actions": ["update_lab"]},
    "2603": {"name": "林伟雄", "menus": ["业务接单大厅", "耗材销售大厅", "实验室检测看板", "财务核对中心", "数据统计看板"], "actions": ["create_order"]}
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

def send_new_order_notifications(order_no, client, sample, test_type, requirements, advice, amount, deposit, creator):
    balance = amount - deposit
    content = f"""🔔 **【新样品到达】**
> **订单编号：** <font color="info">{order_no}</font>
> **接单员：** {creator}
> **客户：** {client}
> **样品：** {sample} (<font color="comment">{test_type}</font>)
> **财务状态：** 订单总额 ¥{amount} (已付定金 ¥{deposit} | 待收尾款 <font color="warning">¥{balance}</font>)
> **要求：** {requirements}

---
🤖 **【AI 测试方案建议】**
<font color="comment">{advice}</font>
"""
    results = []
    if WECHAT_WEBHOOK:
        payload_wecom = {"msgtype": "markdown", "markdown": {"content": content}}
        headers = {'Content-Type': 'application/json'}
        try:
            res_wecom = requests.post(WECHAT_WEBHOOK, json=payload_wecom, headers=headers, timeout=5)
            if res_wecom.status_code == 200: results.append("✅ 企业微信群通知已发送")
            else: results.append(f"❌ 企微群失败(码:{res_wecom.status_code})")
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
    st.header("📝 客户与样品录入 (实验室检测单)")
    
    if "create_order" not in user["actions"]:
        st.info("💡 您的权限级别为【只读】。无权在此录入新订单。")
    else:
        with st.form("order_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                client_name = st.text_input("客户名称 / 公司")
                contact_info = st.text_input("联系方式 (手机/微信)")
                st.markdown("---")
                amount = st.number_input("💰 订单总金额 (元)", min_value=0.0, value=0.0, step=100.0)
                deposit = st.number_input("💵 已付定金金额 (元)", min_value=0.0, value=0.0, step=100.0)
            with col2:
                sample_name = st.text_input("样品名称 (系统将自动生成订单编号)")
                test_type = st.selectbox("🎯 测试类型", ["ICP-MS", "TOC", "温室气体", "氨基酸", "其他"])
                arrival_date = st.date_input("到样日期")
                
            st.markdown("---")
            
            req_template = """一、 样品基本信息
样品名称： XXX（例如：水质样本、铝合金铸件、土壤）
样品数量/体积/重量： X 个 / X ml / X g
样品形态： XXX（例如：固体粉末、固体块状、水溶液、有机溶剂、气体）
样品成分预估： XXX（简述主要基质或成分，如：含30%乙醇的水溶液、铁基合金。这有助于实验室选择合适的试剂）

二、 核心测试需求
测试项目/元素： XXX（例如：铅(Pb)、镉(Cd)含量测试；抗拉强度；表面形貌SEM观察）
参考测试标准（可选）： XXX（例如：国标 GB/T XXXX-XXXX、美标 ASTM XXXX、或者“参照实验室常规方法”）
精度/检出限要求： XXX（例如：精确到 0.01%、检出限需达到 ppm 级别、或者“常规精度即可”）

三、 样品储存与安全属性（必填，关乎实验室安全）
储存/运输条件：
[ ] 常温
[ ] 冷藏 (4℃)
[ ] 冷冻 (-20℃)
[ ] 避光保藏
[ ] 干燥保藏
[ ] 其他特殊要求：XXX
样品危险性声明：
[ ] 无危险性 (安全)
[ ] 易燃 / 易爆
[ ] 有毒 / 有腐蚀性
[ ] 放射性 / 生物危害性
备注：如果是危险品，请务必详细说明：XXX

四、 测试后处理与其他备注
检后样品处理：
[ ] 实验室自行废弃销毁
[ ] 寄回原址（邮费到付）
测试报告要求：
[ ] 仅需电子版 (PDF/Excel数据)
[ ] 需要纸质盖章版（如CMA/CNAS资质报告）
[ ] 中英双语报告
特殊要求或备注： XXX（例如：“测试前请先超声清洗样品表面”、“如果A元素超标，则停止后续B元素的测试”等）"""
            
            requirements = st.text_area("详细测试要求 (请直接在下方模板修改/填写相应的 XXX 与 [ ])", value=req_template, height=450)
            
            submitted = st.form_submit_button("生成订单 & 通知实验室")
            
            if submitted and client_name and sample_name:
                if deposit > amount:
                    st.error("❌ 录入错误：已付定金不能大于订单总金额！")
                else:
                    with st.spinner("正在生成方案并同步数据库，请稍候..."):
                        ai_advice = get_gemini_testing_advice(sample_name, requirements)
                        
                        # 【新增】加入 tail_payment 字段，默认为 0
                        order_data = {
                            "client_name": client_name, "contact_info": contact_info, "sample_name": sample_name,
                            "test_type": test_type, "arrival_date": str(arrival_date), "requirements": requirements, 
                            "ai_advice": ai_advice, "status": "Pending", "amount": amount, "deposit": deposit, 
                            "tail_payment": 0.0, "is_paid": False, "has_test_list": False, "has_invoice": False, "creator_name": user["name"] 
                        }
                        try:
                            res = supabase.table("orders").insert(order_data).execute()
                            if res.data and len(res.data) > 0:
                                inserted_id = res.data[0]['id']
                                auto_order_no = f"YJ-{inserted_id:05d}"
                                
                                _, push_msg = send_new_order_notifications(auto_order_no, client_name, sample_name, test_type, requirements, ai_advice, amount, deposit, user["name"])
                                
                                st.success(f"✅ 订单创建成功！系统编号：**{auto_order_no}**")
                                st.info(f"状态: {push_msg}")
                                
                                with st.expander("查看 AI 生成的初始测试方案", expanded=False):
                                    st.write(ai_advice)
                            else:
                                st.error("❌ 数据库保存失败。")
                        except Exception as e:
                            st.error(f"❌ 异常: {str(e)}")

# --- 模块 5：耗材销售大厅 (全新耗材模块) ---
elif menu == "耗材销售大厅":
    st.header("📦 耗材产品销售录入")
    
    if "create_order" not in user["actions"]:
        st.info("💡 您的权限级别为【只读】。无权在此录入新单。")
    else:
        st.write("💡 **提示：** 耗材销售单生成后，将直接越过实验室环节（标记为已完工），直接进入财务中心进行账款核对。")
        with st.form("consumable_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                client_name = st.text_input("客户名称 / 公司")
                contact_info = st.text_input("联系方式 (手机/微信)")
                st.markdown("---")
                amount = st.number_input("💰 销售总金额 (元)", min_value=0.0, value=0.0, step=10.0)
                deposit = st.number_input("💵 已收首款/定金 (元)", min_value=0.0, value=0.0, step=10.0)
            with col2:
                c_type = st.selectbox("📦 选择耗材类别", ["大锥", "小锥", "调谐液", "其他"])
                custom_c = st.text_input("若上方选了'其他'，请在此手工填写具体耗材名称：")
                sale_date = st.date_input("销售/出库日期")
                
            st.markdown("---")
            requirements = st.text_area("销售备注 / 发货信息 (例如：购买数量10个，顺丰包邮，发往XX地址等)")
            
            submitted = st.form_submit_button("💳 生成耗材销售单 & 同步财务")
            
            if submitted and client_name:
                final_c_name = custom_c.strip() if c_type == "其他" else c_type
                
                if not final_c_name:
                    st.error("❌ 请填写具体的耗材名称！")
                elif deposit > amount:
                    st.error("❌ 录入错误：已收金额不能大于销售总金额！")
                else:
                    with st.spinner("正在同步至数据库并通知财务..."):
                        order_data = {
                            "client_name": client_name, 
                            "contact_info": contact_info, 
                            "sample_name": f"[耗材] {final_c_name}",  
                            "test_type": "耗材销售",                 
                            "arrival_date": str(sale_date), 
                            "requirements": requirements if requirements else "无备注", 
                            "ai_advice": "此单为耗材现货销售，无需安排实验室上机检测。",
                            "status": "Completed",                   
                            "amount": amount, 
                            "deposit": deposit, 
                            "tail_payment": 0.0,                     # 【新增】耗材单也同样加入尾款字段
                            "is_paid": False, 
                            "has_test_list": True,                   
                            "has_invoice": False, 
                            "creator_name": user["name"] 
                        }
                        try:
                            res = supabase.table("orders").insert(order_data).execute()
                            if res.data and len(res.data) > 0:
                                inserted_id = res.data[0]['id']
                                auto_order_no = f"YJ-{inserted_id:05d}"
                                
                                balance = amount - deposit
                                content = f"📦 **【新耗材售出】**\n> **订单编号：** <font color=\"info\">{auto_order_no}</font>\n> **销售员：** {user['name']}\n> **客户：** {client_name}\n> **商品：** {final_c_name}\n> **财务状态：** 订单总额 ¥{amount} (已收 ¥{deposit} | 待收 <font color=\"warning\">¥{balance}</font>)\n> **备注：** {requirements}"
                                push_status = ""
                                if WECHAT_WEBHOOK:
                                    try:
                                        requests.post(WECHAT_WEBHOOK, json={"msgtype": "markdown", "markdown": {"content": content}}, headers={'Content-Type': 'application/json'}, timeout=5)
                                        push_status = "✅ 企微群通知成功"
                                    except:
                                        push_status = "❌ 企微网络超时"
                                
                                st.success(f"✅ 耗材销售单创建成功！系统编号：**{auto_order_no}**")
                                st.info(f"💡 该订单已直接越过实验室，传送至【财务核对中心】。推送状态: {push_status}")
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
                    t_type = order.get('test_type', '其他')
                    
                    with col_a:
                        st.markdown(f"**🧾 {display_order_no}**")
                        st.markdown(f"**🧪 {order['sample_name']}** (<font color='blue'>{t_type}</font>)", unsafe_allow_html=True)
                        # 【更新显示】包含尾款
                        tail_paid = order.get('tail_payment', 0)
                        balance = order.get('amount', 0) - order.get('deposit', 0) - tail_paid
                        st.caption(f"客户：{order['client_name']} | 总额: ¥{order.get('amount', 0)}")
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
    st.header("💰 账单明细与开票管理")
    can_update_finance = "update_finance" in user["actions"]
    if not can_update_finance:
        st.info("💡 您的权限级别为【只读】。您可以看到财务数据汇总，但无法操作收款和单据状态。")
        
    try:
        response = supabase.table("orders").select("*").order("id", desc=True).execute()
        all_orders = response.data
        
        st.write("### 🧾 订单与耗材财务明细清单 (全部)")
        
        col_search, col_download = st.columns([3, 1])
        with col_search:
            fin_search = st.text_input("🔍 搜索客户名称快速定位...", key="fin_search")
            
        with col_download:
            if all_orders:
                csv_buffer = io.StringIO()
                csv_writer = csv.writer(csv_buffer)
                # 【新增】CSV 表头加入“已收尾款(元)”
                csv_writer.writerow(['单号编号', '接单员', '业务类型', '发生日期', '客户名称', '标的名称', '总额(元)', '已付定金(元)', '已收尾款(元)', '待收余额(元)', '已结清', '已开清单', '已开发票', '系统进度'])
                status_map = {"Pending": "待处理", "Processing": "检测中", "Completed": "已完工"}
                
                for o in all_orders:
                    order_no_csv = f"YJ-{o['id']:05d}"
                    amt_csv = o.get('amount', 0) or 0
                    dep_csv = o.get('deposit', 0) or 0
                    tail_csv = o.get('tail_payment', 0) or 0
                    bal_csv = amt_csv - dep_csv - tail_csv
                    
                    csv_writer.writerow([
                        order_no_csv, o.get('creator_name', '未知'), o.get('test_type', '其他'), o.get('arrival_date', '未知'),
                        o.get('client_name', '未知'), o.get('sample_name', '未知'), amt_csv, dep_csv, tail_csv, bal_csv,
                        "是" if o.get('is_paid') else "否", "是" if o.get('has_test_list') else "否", "是" if o.get('has_invoice') else "否",
                        status_map.get(o.get('status', ''), '未知')
                    ])
                
                csv_bytes = csv_buffer.getvalue().encode('utf-8-sig')
                st.download_button(
                    label="📥 导出全部财务数据 (CSV)", data=csv_bytes, file_name=f"玉佳生物财务明细_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv", use_container_width=True
                )
        
        filtered_orders = all_orders
        if fin_search:
            filtered_orders = [o for o in all_orders if fin_search.lower() in o.get('client_name', '').lower() or fin_search.lower() in o.get('sample_name', '').lower()]
            
        if not filtered_orders:
            st.info("暂无订单数据。")
        else:
            status_map_ui = {"Pending": "🟡 待处理", "Processing": "🔵 检测中", "Completed": "🟢 已完工/已发货"}
            for order in filtered_orders:
                with st.container(border=True):
                    display_order_no = f"YJ-{order['id']:05d}"
                    
                    # 【核心更新】：精确计算资金明细
                    order_amt = order.get('amount', 0)
                    order_dep = order.get('deposit', 0)
                    order_tail = order.get('tail_payment', 0)
                    balance = order_amt - order_dep - order_tail
                    
                    current_status = status_map_ui.get(order.get('status', ''), "未知")
                    t_type = order.get('test_type', '其他')
                    
                    st.markdown(f"**单号：{display_order_no}** | 客户：{order['client_name']} | 标的：{order['sample_name']} (<font color='blue'>{t_type}</font>) | 负责人：{order.get('creator_name', '未知')} | 进度：**{current_status}**", unsafe_allow_html=True)
                    st.markdown(f"**总计：** ¥ {order_amt} | **已付定金：** ¥ {order_dep} | **已收尾款：** ¥ {order_tail} | **待收余额：** <font color='red'>**¥ {balance}**</font>", unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        new_is_paid = st.checkbox("✅ 确认订单归档结清", value=order.get('is_paid', False), key=f"paid_{order['id']}", disabled=not can_update_finance)
                    with c2:
                        new_has_test_list = st.checkbox("📑 已开清单", value=order.get('has_test_list', False), key=f"testlist_{order['id']}", disabled=not can_update_finance)
                    with c3:
                        new_has_invoice = st.checkbox("🧾 已开发票", value=order.get('has_invoice', False), key=f"invoice_{order['id']}", disabled=not can_update_finance)
                    
                    if can_update_finance:
                        if new_is_paid != order.get('is_paid', False) or new_has_test_list != order.get('has_test_list', False) or new_has_invoice != order.get('has_invoice', False):
                            supabase.table("orders").update({"is_paid": new_is_paid, "has_test_list": new_has_test_list, "has_invoice": new_has_invoice}).eq("id", order['id']).execute()
                            st.rerun() 
                    
                    # 【核心新增】：财务专用的“尾款录入窗口”
                    if can_update_finance:
                        with st.expander("💸 登记尾款 / 更新收款进度"):
                            col_t1, col_t2 = st.columns([3, 1])
                            with col_t1:
                                input_tail = st.number_input("录入该笔订单已收尾款金额 (元)", value=float(order_tail), step=10.0, key=f"input_tail_{order['id']}")
                            with col_t2:
                                st.write("")
                                st.write("")
                                if st.button("💾 保存尾款金额", key=f"btn_tail_{order['id']}", use_container_width=True):
                                    supabase.table("orders").update({"tail_payment": input_tail}).eq("id", order['id']).execute()
                                    st.success("尾款更新成功！")
                                    st.rerun()
                            
    except Exception as e:
        st.error(f"加载数据失败: {str(e)}")

# --- 模块 4：数据统计看板 ---
elif menu == "数据统计看板":
    st.header("📈 数据统计与业务分析")
    try:
        response = supabase.table("orders").select("*").execute()
        all_orders = response.data
        
        if not all_orders:
            st.info("暂无订单数据可用于统计分析。")
        else:
            df = pd.DataFrame(all_orders)
            
            df['arrival_date'] = pd.to_datetime(df['arrival_date'], errors='coerce')
            df['month'] = df['arrival_date'].dt.strftime('%Y-%m')
            
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
            df['deposit'] = pd.to_numeric(df.get('deposit', 0), errors='coerce').fillna(0)
            df['tail_payment'] = pd.to_numeric(df.get('tail_payment', 0), errors='coerce').fillna(0)
            
            # 真实收回的款项 = 定金 + 尾款
            df['collected_amt'] = df['deposit'] + df['tail_payment']
            
            if 'test_type' not in df.columns:
                df['test_type'] = '其他'
            df['test_type'] = df['test_type'].fillna('其他')
            
            if 'creator_name' not in df.columns:
                df['creator_name'] = '未知'
            df['creator_name'] = df['creator_name'].fillna('未知')
            
            df = df.dropna(subset=['month']).sort_values('month')
            
            # --- 图表 1 ---
            st.subheader("📊 1. 每月营业总额趋势 (含测试与耗材)")
            monthly_total = df.groupby('month')['amount'].sum().reset_index()
            monthly_total.columns = ['月份', '营业额 (元)']
            st.bar_chart(monthly_total.set_index('月份'))
            
            st.divider()
            
            # --- 图表 2 ---
            st.subheader("🎯 2. 每月各【业务类型】营业额分布")
            type_pivot = df.pivot_table(index='month', columns='test_type', values='amount', aggfunc='sum', fill_value=0)
            st.bar_chart(type_pivot)
            
            st.divider()
            
            # --- 图表 3 ---
            st.subheader("🏢 3. 核心大客户消费能力明细")
            client_pivot = df.pivot_table(index='client_name', columns='month', values='amount', aggfunc='sum', fill_value=0)
            client_pivot['累计总消费'] = client_pivot.sum(axis=1)
            client_pivot = client_pivot.sort_values('累计总消费', ascending=False).reset_index()
            client_pivot.rename(columns={'client_name': '客户 / 单位名称'}, inplace=True)
            for col in client_pivot.columns:
                if col != '客户 / 单位名称':
                    client_pivot[col] = client_pivot[col].apply(lambda x: f"¥ {x:,.2f}")
            st.dataframe(client_pivot, use_container_width=True)
            
            st.divider()
            
            # --- 图表 4 ---
            st.subheader("👨‍💼 4. 每月各【接单/销售员】业绩与收款明细")
            creator_chart_pivot = df.pivot_table(index='month', columns='creator_name', values='amount', aggfunc='sum', fill_value=0)
            st.bar_chart(creator_chart_pivot)
            
            # 【更新统计逻辑】：使用真实的定金+尾款进行已收账款核算
            creator_table = df.groupby('creator_name').agg(
                接单数量=('id', 'count'),
                创造总业绩=('amount', 'sum'),
                已收账款=('collected_amt', 'sum')
            ).reset_index()
            
            creator_table['待收尾款总计'] = creator_table['创造总业绩'] - creator_table['已收账款']
            creator_table = creator_table.sort_values('创造总业绩', ascending=False)
            creator_table.rename(columns={'creator_name': '人员姓名', '创造总业绩': '创造总业绩 (元)', '已收账款': '真实已收账款(含定金+尾款)', '待收尾款总计': '待收余额总计(元)'}, inplace=True)
            
            for col in creator_table.columns:
                if col not in ['人员姓名', '接单数量']:
                    creator_table[col] = creator_table[col].apply(lambda x: f"¥ {x:,.2f}")
            st.dataframe(creator_table, use_container_width=True)
            
            # 顶部全局财务卡片
            total_revenue = df['amount'].sum()
            collected_revenue = df['collected_amt'].sum()
            uncollected_revenue = total_revenue - collected_revenue
            
            st.sidebar.divider()
            st.sidebar.write("### 🏢 公司实时总账")
            st.sidebar.metric("累计订单总额", f"¥ {total_revenue:,.2f}")
            st.sidebar.metric("真实已收总额 (定金+尾款)", f"¥ {collected_revenue:,.2f}")
            st.sidebar.metric("当前待收余额", f"¥ {uncollected_revenue:,.2f}")
            
    except Exception as e:
        st.error(f"加载统计数据失败: {str(e)}")
