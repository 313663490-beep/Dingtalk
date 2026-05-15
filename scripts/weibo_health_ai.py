import requests, json, os, time, hmac, hashlib, base64, urllib.parse

# ========== 配置 ==========
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}

# ========== 1. 获取热搜 ==========
def get_weibo_hotspots():
    api_url = "http://101.35.2.25/api/xinwen/weibo2.php"
    params = {
        "id": os.environ.get('APIBOX_ID'),
        "key": os.environ.get('APIBOX_KEY')
    }
    try:
        resp = requests.get(api_url, params=params)
        data = resp.json()
        if data.get('code') != 200:
            print(f"热搜API错误: {data.get('msg')}")
            return None, None
        return data.get('data', []), data.get('time2', '未知时间')
    except Exception as e:
        print(f"获取热搜失败: {e}")
        return None, None

# ========== 2. 调用 AI 判断单条热搜是否为健康场景 ==========
def is_health_topic(title):
    """调用 AI 判断单条热搜是否属于健康全场景（最宽松标准）"""
    prompt = f"""请用最宽松的标准判断以下微博热搜标题是否属于“健康全场景”。
健康全场景包括一切可能直接或间接影响人类身心健康的话题，例如：
疾病、症状、治疗、药物、疫苗、医院、医生、护士、中医、西医、心理、情绪、压力、抑郁、焦虑、失眠、减肥、健身、运动、饮食、营养、食品安全、保健品、养生、美容、护肤、整形、医美、生育、怀孕、育儿、月经、更年期、衰老、死亡、意外伤害、急救、康复、过敏、环境健康、空气污染、水污染、辐射、科普、辟谣（健康相关）、生活方式、习惯改变等。
只要标题中含有以上任意一点关联，请回答“是”，否则回答“否”。
标题：{title}
请只回答一个字：是 或 否。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个健康全场景分类器，标准极其宽松。只输出是或否。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 10,
        "stream": False
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"判断接口返回非200: {resp.status_code} {resp.text}")
            return False
        answer = resp.json()['choices'][0]['message']['content'].strip()
        # 只要包含“是”就认定为健康
        if "是" in answer:
            return True
        else:
            return False
    except Exception as e:
        print(f"判断“{title}”时出错: {e}")
        return False

# ========== 3. AI 生成最终摘要 ==========
def generate_summary(health_list, time_str):
    hotspots_text = "\n".join(
        [f"- {item['title']} (热度: {item.get('desc_extr', 'N/A')})" for item in health_list]
    )
    prompt = f"请用一段话，概述以下微博健康类热搜的核心内容，并总结出关键信息：\n\n{hotspots_text}\n\nAI概述："

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的健康信息助手，用简洁专业的语言总结健康热点。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "stream": False
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        else:
            print(f"摘要生成失败: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        print(f"摘要生成异常: {e}")
        return None

# ========== 4. 发送钉钉消息 ==========
def send_to_dingtalk(webhook_url, secret, title, text):
    timestamp = str(round(time.time() * 1000))
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
        resp = requests.post(webhook_url, headers=headers, json=data)
        result = resp.json()
        if result.get('errcode') == 0:
            print("钉钉消息发送成功！")
            return True
        else:
            print(f"钉钉消息发送失败: {resp.text}")
            return False
    except Exception as e:
        print(f"钉钉发送异常: {e}")
        return False

# ========== 主程序 ==========
if __name__ == "__main__":
    print("开始执行每日健康热搜任务（AI 识别版）...")
    hotspots, time_str = get_weibo_hotspots()

    if not hotspots:
        print("未能获取热搜数据，任务结束。")
        exit(1)

    # AI 逐条筛选
    health_list = []
    total = len(hotspots)
    for idx, item in enumerate(hotspots, 1):
        title = item.get('title', '')
        if not title:
            continue
        print(f"[{idx}/{total}] 判断: {title}")
        is_health, reason = is_health_topic(title)
        if is_health:
            health_list.append(item)
            print(f"  ✅ 是健康话题 - {reason}")
        else:
            print(f"  ❌ 非健康话题 - {reason}")

    print(f"筛选完成，共识别出 {len(health_list)} 条健康热搜。")

    webhook_url = os.environ.get('DINGTALK_WEBHOOK')
    secret = os.environ.get('DINGTALK_SECRET')

    if health_list:
        summary = generate_summary(health_list, time_str)
        if summary:
            # 构建 Markdown 消息
            msg_lines = [
                f"## 微博健康热搜AI概览",
                f"**数据时间：** {time_str}",
                "",
                "### 🔥 识别到的健康热搜："
            ]
            for item in health_list:
                title = item.get('title', '无标题')
                url = item.get('scheme', '#')
                heat = item.get('desc_extr', 'N/A')
                msg_lines.append(f"- [{title}]({url}) (热度: {heat})")
            msg_lines.append("")
            msg_lines.append("### 🤖 AI概述：")
            msg_lines.append(summary)

            markdown_text = "\n".join(msg_lines)
            if webhook_url and secret:
                send_to_dingtalk(webhook_url, secret, "每日健康热搜", markdown_text)
            else:
                print("错误: 未配置钉钉环境变量")
        else:
            print("摘要生成失败，但健康热搜列表已筛选。")
    else:
        print("今日无健康热搜。")
        if webhook_url and secret:
            send_to_dingtalk(webhook_url, secret, "每日健康热搜", "今日微博热榜暂无匹配的健康话题。")
        else:
            print("钉钉环境变量缺失，无法发送通知。")
