import requests
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import json

DAILY_FILE = "daily_finance_topics.json"

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
        "markdown": {"title": title, "text": text}
    }
    try:
        resp = requests.post(webhook_url, headers=headers, json=data)
        result = resp.json()
        if result.get('errcode') == 0:
            print("✅ 钉钉消息发送成功！")
        else:
            print(f"❌ 钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")

if __name__ == "__main__":
    print("开始生成今日理财热搜日汇总...")
    daily_topics = load_daily_topics()

    webhook_url = os.environ.get('DINGTALK_WEBHOOK_FINANCE')
    secret = os.environ.get('DINGTALK_SECRET_FINANCE')
    if not webhook_url or not secret:
        print("钉钉凭证缺失，无法发送")
        exit(1)

    if not daily_topics:
        send_to_dingtalk(webhook_url, secret, "今日理财热搜汇总", "今日没有监测到理财相关热搜，明天见～")
    else:
        lines = []
        for idx, topic in enumerate(daily_topics, start=1):
            query = urllib.parse.quote(topic)
            link = f"https://s.weibo.com/weibo?q={query}&t=31&Refer=top"
            lines.append(f"{idx}. [{topic}]({link})")
        full_text = f"## 📊 今日理财热搜汇总\n\n今日共监测到以下理财话题：\n" + "\n".join(lines)
        send_to_dingtalk(webhook_url, secret, "今日理财热搜汇总", full_text)

    clear_daily_topics()
    print("日汇总完成，已清空今日累积。")
