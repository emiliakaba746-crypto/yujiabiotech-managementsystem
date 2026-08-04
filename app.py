import streamlit as st
import requests
import google.generativeai as genai

# ==========================================
# 1. API 配置与工具函数
# ==========================================

# 配置 Gemini API
genai.configure(api_key="您的_GEMINI_API_KEY")

def get_gemini_testing_advice(sample_name, requirements):
    """调用 Gemini API 生成测试安排与方法提示"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    作为玉佳生物科技的资深实验员，请根据以下样品信息提供测试建议：
    - 样品名称：{sample_name}
    - 客户测试要求：{requirements}
    
    请提供：
    1. 推荐的测试方法（标准方法或业内通用做法）
    2. 具体的测试流程与安排建议
    3. 样品的保存条件及实验安全注意事项
    """
    response = model.generate_content(prompt)
    return response.text

def send_wxpusher_group_msg(client, sample, requirements, advice):
    """调用 WxPusher 向微信群发送新样品通知"""
    url = "https://wxpusher.zjiecode.com/api/send/message"
    content = f"🔔【玉佳生物 - 新样品到达】\n\n客户：{client}\n样品：{sample}\n要求：{requirements}\n\n🤖【AI 测试建议提要】\n{advice[:100]}..."
    
    payload = {
        "appToken": "您的_WXPUSHER_APP_TOKEN",
        "content": content,
        "summary": f"新样品: {sample}",
        "contentType": 1, 
        "topicIds": [12345],  # 替换为您的 WxPusher 群组 Topic ID
    }
    # requests.post(url, json=payload) # 生产环境取消注释
    return True

# ==========================================
# 2. Streamlit 界面路由与功能实现
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
            with st.spinner("正在呼叫 AI 助手生成测试方案..."):
                # 1. 获取 AI 建议
                ai_advice = get_gemini_testing_advice(sample_name, requirements)
                
                # 2. 发送微信推送
                send_wxpusher_group_msg(client_name, sample_name, requirements, ai_advice)
                
                # 3. 存入数据库 (此处需连接 SQLite 或 MySQL)
                # db.save_order(...) 
                
                st.success(f"✅ 订单已创建！微信群已通知。样品分配给：{client_name}")
                with st.expander("查看 AI 生成的初始测试方案"):
                    st.write(ai_advice)

# --- 模块 2：实验室检测看板 ---
elif menu == "实验室检测看板":
    st.header("🔬 实验室样品处理")
    
    # 模拟从数据库提取的待处理订单
    st.info("以下为待处理样品。点击展开可查看详情与 AI 测试指南。")
    
    # 样品卡片设计，让检测人员一目了然
    with st.container():
        col_a, col_b, col_c = st.columns([2, 5, 2])
        col_a.markdown("**样品：高纯度质粒 DNA**\n\n客户：王教授团队")
        col_b.markdown("**要求：** 浓度测定及纯度检测 (A260/A280)")
        
        status = col_c.selectbox("状态更新", ["待处理 (Pending)", "检测中 (Processing)", "已完成 (Completed)"], key="status_1")
        
    with st.expander("🤖 查看 Gemini 测试方案建议与方法"):
        st.markdown("""
        **1. 推荐测试方法：** 使用 Nanodrop 紫外分光光度计进行吸光度测定。
        **2. 流程安排：** 样品需先在 4°C 融化。先用对应的洗脱缓冲液进行空白校准，再取 1-2 μL 样品进行测量。
        **3. 注意事项：** 确保 A260/A280 比值在 1.8 左右以确认无蛋白质污染。
        """)

# --- 模块 3：财务核对中心 ---
elif menu == "财务核对中心":
    st.header("💰 账单与开票管理")
    
    st.write("筛选 **已完成** 测试的订单进行结算。")
    
    # 模拟财务核对行
    st.markdown("### 订单号：YJ-202310-001 (已完工)")
    st.markdown("**客户：** 王教授团队 | **样品：** 高纯度质粒 DNA | **费用核定：** ¥ 850.00")
    
    col1, col2 = st.columns(2)
    with col1:
        invoice_file = st.file_uploader("上传发票副本 (PDF/JPG)", type=['pdf', 'jpg', 'png'])
        if invoice_file:
            st.success("发票上传成功")
            
    with col2:
        manifest_file = st.file_uploader("上传最终测试清单 (PDF/Excel)", type=['pdf', 'xlsx'])
        if manifest_file:
            st.success("测试清单上传成功")
            
    if st.button("核对无误，归档订单"):
        st.balloons()
        st.success("订单流转结束，已封存入库！")
