import requests, os, time, hmac, hashlib, base64, urllib.parse

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}

def get_weibo_hotspots():
    api_url = "http://101.34.207.105/api/xinwen/weibo.php"
    params = {
        "id": os.environ.get('APIBOX_ID'),
        "key": os.environ.get('APIBOX_KEY')
    }
    try:
        resp = requests.get(api_url, params=params)
        data = resp.json()
        if data.get('code') != 200:
            print(f"热搜API错误: {data.get('msg')}")
            return [], None
        items = data.get('data', [])
        # 为每条热搜增加一个排名字段（列表索引+1）
        for idx, item in enumerate(items, start=1):
            item['rank'] = idx
        return items, data.get('time2', '未知时间')
    except Exception as e:
        print(f"获取热搜失败: {e}")
        return [], None

def is_health_topic(title):
    """
    严格判断真实健康话题，但明星/公众人物因具体疾病、住院等健康事件应予以纳入。
    排除纯娱乐、时尚、搞笑、情感宣泄等。
    """
    prompt = f"""请判断以下微博热搜标题是否属于“健康/医疗/疾病/公共卫生”领域。
规则：
1. 如果标题包含具体疾病（如败血症、高血压、癌症、过敏）、症状、治疗、药物、医院、疫苗、食品安全、公共卫生事件、科学辟谣(健康类)、严重心理疾病（如抑郁症）、罕见病、急救等，即使提及明星姓名，仍然属于健康话题。例如“温岚因败血症进入ICU”算健康。
2. 如果标题只关注明星外貌、身材、穿着、演出、综艺效果、纯情感段子、网红八卦等，与具体健康问题无关，则不算健康。
3. 情绪心理类：明确指向心理疾病（如抑郁、焦虑症）或心理危机干预的算健康；仅表达情绪波动（如“一会想通了一会又想不通”）不算。
标题：{title}
请只回答一个字：是 或 否。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个严格的健康话题过滤器，根据规则只输出是或否。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 10,
        "stream": False
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"判断接口异常 {resp.status_code}: {resp.text}")
            return False
        answer = resp.json()['choices'][0]['message']['content'].strip()
        return "是" in answer
    except Exception as e:
        print(f"判断“{title}”出错: {e}")
        return False

def generate_single_summary(title):
    """为单条健康热搜生成一句概述，聚焦健康要点"""
    prompt = f"用一句话概述以下微博健康热搜的核心事实（聚焦疾病、健康风险或医疗事件本身，不要娱乐化）：\n{title}\n概述："

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的健康信息摘要员，只输出一句话事实概述。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 100,
        "stream": False
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            print(f"概述生成失败 {resp.status_code}: {resp.text}")
            return title  # 失败时退而用标题
    except Exception as e:
        print(f"概述生成异常: {e}")
        return title

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
        else:
            print(f"钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"钉钉发送异常: {e}")

if __name__ == "__main__":
    print("开始严格健康热搜筛选...")
    hotspots, time_str = get_weibo_hotspots()

    if not hotspots:
        print("未获取到热搜数据，退出。")
        exit(1)

    health_list = []
    for item in hotspots:
        title = item.get('title', '')
        if not title:
            continue
        print(f"判断: {title}")
        if is_health_topic(title):
            health_list.append(item)
            print(f"  ✅ 通过")
        else:
            print(f"  ❌ 拒绝")

    print(f"共筛选出 {len(health_list)} 条健康热搜")

    webhook_url = os.environ.get('DINGTALK_WEBHOOK')
    secret = os.environ.get('DINGTALK_SECRET')

    if not webhook_url or not secret:
        print("钉钉环境变量缺失，无法发送")
        exit(1)

    if health_list:
        # 为每条健康热搜生成概述，并构建消息
        messages = []
        for item in health_list:
            rank = item.get('rank', '?')
            title = item['title']
            link = item.get('scheme', '#')
            summary = generate_single_summary(title)
            messages.append(f"话题：{title}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")

        full_text = f"## 微博健康热搜播报\n**数据时间：{time_str}**\n\n" + "\n".join(messages)
        send_to_dingtalk(webhook_url, secret, "每日健康热搜", full_text)
    else:
        # 无健康热搜，不发消息（或可选发一条通知）
        print("今日无健康热搜，不发送消息。")
