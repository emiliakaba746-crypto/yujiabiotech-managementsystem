def get_gemini_testing_advice(sample_name, requirements):
    """调用 Gemini API 生成测试安排与方法提示 (增强容错版)"""
    try:
        # 1. 自动探测当前 API Key 支持的模型列表
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        if not available_models:
            return "AI 建议生成失败：您的 API Key 没有访问任何文本生成模型的权限。请确认 Key 是否有效或欠费。"

        # 2. 智能选择模型 (优先 1.5-flash，其次 pro，最后用列表里第一个保底)
        target_model_name = available_models[0] # 保底
        if 'models/gemini-1.5-flash' in available_models:
            target_model_name = 'gemini-1.5-flash'
        elif 'models/gemini-pro' in available_models:
            target_model_name = 'gemini-pro'
        else:
            # 清理 models/ 前缀适配 SDK
            target_model_name = target_model_name.replace('models/', '')

        # 3. 发起请求
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
        # 如果再次失败，把获取到的可用模型列表打印出来，方便排查
        debug_info = f"\n\n[排错信息] 当前 Key 支持的模型有: {available_models}" if 'available_models' in locals() else ""
        return f"AI 建议生成失败：{str(e)} {debug_info}"
