import requests
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import json

# ==================== 配置 ====================
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}

DAILY_FILE = os.environ.get('DAILY_FILE', 'daily_health_topics.json')

def load_daily_topics():
    try:
        with open(DAILY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return list(data.get('topics', []))
    except FileNotFoundError:
        return []

def clear_daily_topics():
    with open(DAILY_FILE, 'w', encoding='utf-8') as f:
        json.dump({'topics': []}, f)

def generate_daily_summary(topics):
    if not topics:
        return None
    topics_text = "\n".join([f"- {t}" for t in topics])
    prompt = f"""你是一位专业的健康信息分析师。以下是今天微博上出现的与健康相关的热搜话题列表：
{topics_text}

请总结今日健康热点，用2-3段话概述核心议题和趋势，语言专业但通俗易懂，总字数控制在300字以内。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位专业的健康信息分析师，善于总结每日健康热点。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 500,
        "stream": False
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            print(f"AI 汇总失败: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        print(f"AI 汇总异常: {e}")
        return None

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
            print(f"✅ 钉钉消息发送成功！")
        else:
            print(f"❌ 钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")

if __name__ == "__main__":
    print("开始生成今日健康热搜日汇总...")
    daily_topics = load_daily_topics()

    webhooks_str = os.environ.get('DINGTALK_WEBHOOKS', '')
    secrets_str = os.environ.get('DINGTALK_SECRETS', '')
    webhooks = [w.strip() for w in webhooks_str.split(',') if w.strip()]
    secrets = [s.strip() for s in secrets_str.split(',') if s.strip()]

    if not webhooks or not secrets or len(webhooks) != len(secrets):
        print("钉钉凭证缺失或不匹配，无法发送")
        exit(1)

    if not daily_topics:
        print("今天暂无健康热搜，发送提示。")
        for i in range(len(webhooks)):
            send_to_dingtalk(webhooks[i], secrets[i], "今日健康热搜汇总", "今天没有监测到健康相关热搜，明天见～")
    else:
        summary = generate_daily_summary(daily_topics)
        if summary:
            full_text = f"## 📊 今日健康热搜汇总\n\n{summary}"
            for i in range(len(webhooks)):
                send_to_dingtalk(webhooks[i], secrets[i], "今日健康热搜汇总", full_text)
        else:
            # 回退：列出所有话题
            topics_list = "\n".join([f"- {t}" for t in daily_topics])
            full_text = f"## 📊 今日健康热搜汇总\n\n今日共监测到以下健康话题：\n{topics_list}"
            for i in range(len(webhooks)):
                send_to_dingtalk(webhooks[i], secrets[i], "今日健康热搜汇总", full_text)

    # 清空日累积文件
    clear_daily_topics()
    print("日汇总完成，已清空今日累积。")
