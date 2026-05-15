import requests, json, os, time, hmac, hashlib, base64, urllib.parse

# --- 1. 获取热搜数据 ---
def get_weibo_hotspots():
    api_url = "https://cn.apihz.cn/api/xinwen/weibo2.php"
    params = {
        "id": os.environ.get('APIBOX_ID'),
        "key": os.environ.get('APIBOX_KEY')
    }
    try:
        response = requests.get(api_url, params=params)
        hot_data = response.json()
        if hot_data.get('code') != 200:
            print(f"API错误: {hot_data.get('msg')}")
            return None, None
        return hot_data.get('data', []), hot_data.get('time2', '未知时间')
    except Exception as e:
        print(f"获取热搜失败: {e}")
        return None, None

# --- 2. 筛选健康内容并生成AI摘要 ---
def summarize_with_ai(hotspots, time_str):
    health_keywords =health_keywords = [
    '健康', '医疗', '医生', '医院', '护士', '药',
    '疫情', '病毒', '流感', '发烧', '咳嗽',
    '中医', '中药', '针灸', '把脉',
    '减肥', '健身', '运动', '跑步', '瑜伽',
    '睡眠', '失眠', '熬夜',
    '养生', '保健品', '维生素',
    '食品', '安全', '添加剂', '致癌',
    '体检', '血压', '血糖', '心脏',
    '癌症', '肿瘤', '白血病',
    '科普', '辟谣'   # 很多健康科普辟谣也会上热搜
    health_hotspots = [h for h in hotspots if any(kw in h.get('title', '') for kw in health_keywords)]

    if not health_hotspots:
        print("无相关健康热搜，跳过AI总结。")
        return None, None, []

    # 构建给AI的提示
    hotspots_text = "\n".join([f"- {item['title']} (热度: {item.get('desc_extr', 'N/A')})" for item in health_hotspots])
    prompt = f"请用一段话，概述以下微博健康类热搜的核心内容，并总结出关键信息：\n\n{hotspots_text}\n\nAI概述："

    # 调用DeepSeek API【6†L23-L25】
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY')}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的健康信息助手，你的任务是用简洁、专业的语言概述健康类热搜的核心内容。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "stream": False
    }

    try:
        ai_response = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload)
        if ai_response.status_code == 200:
            summary = ai_response.json()['choices'][0]['message']['content']
            return summary, time_str, health_hotspots
        else:
            print(f"AI API调用失败，状态码: {ai_response.status_code}, 内容: {ai_response.text}")
            return None, None, health_hotspots
    except Exception as e:
        print(f"AI调用异常: {e}")
        return None, None, health_hotspots

# --- 3. 推送到钉钉机器人 ---
def send_to_dingtalk(webhook_url, title, text):
    timestamp = str(round(time.time() * 1000))
    secret = os.environ.get('DINGTALK_SECRET') # 假设你的钉钉密钥存在这个Secret中
    if not secret:
        print("错误: 未找到DINGTALK_SECRET")
        return False

    secret_enc = secret.encode('utf-8')
    string_to_sign = f'{timestamp}\n{secret}'
    hmac_code = hmac.new(secret_enc, string_to_sign.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    webhook_url = f'{webhook_url}&timestamp={timestamp}&sign={sign}'

    headers = {'Content-Type': 'application/json'}
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text
        }
    }
    try:
        response = requests.post(webhook_url, headers=headers, json=data)
        if response.json().get('errcode') == 0:
            print("钉钉消息发送成功！")
            return True
        else:
            print(f"钉钉消息发送失败: {response.text}")
            return False
    except Exception as e:
        print(f"钉钉发送异常: {e}")
        return False

# --- 主程序 ---
if __name__ == "__main__":
    print("开始执行每日健康热搜任务...")
    hotspots, time_str = get_weibo_hotspots()

    if hotspots:
        summary, time_str, health_list = summarize_with_ai(hotspots, time_str)
        if summary:
            # 构建Markdown格式的消息
            msg_lines = [
                f"## 微博健康热搜AI概览",
                f"**数据时间：** {time_str}",
                "",
                "### 🔥 相关热搜："
            ]
            for item in health_list:
                msg_lines.append(f"- [{item.get('title', '无标题')}]({item.get('scheme', '#')}) (热度: {item.get('desc_extr', 'N/A')})")
            msg_lines.append("")
            msg_lines.append("### 🤖 AI概述：")
            msg_lines.append(summary)

            markdown_text = "\n".join(msg_lines)
            webhook_url = os.environ.get('DINGTALK_WEBHOOK')
            if webhook_url:
                send_to_dingtalk(webhook_url, "每日健康热搜", markdown_text)
            else:
                print("错误: 未配置DINGTALK_WEBHOOK环境变量！")
        else:
    print("未生成AI摘要，发送提示消息。")
    webhook_url = os.environ.get('DINGTALK_WEBHOOK')
    secret = os.environ.get('DINGTALK_SECRET')
    if webhook_url and secret:
        send_to_dingtalk(webhook_url, secret, "每日健康热搜", "今日微博热榜暂无匹配的健康话题。")
    else:
        print("未能获取热搜数据，任务结束。")
