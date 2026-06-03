import requests
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import json

# ==================== 配置 ====================
UAPIS_API_KEY = os.environ.get('UAPIS_API_KEY', '')
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
HEADERS_DEEPSEEK = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}

# 小红书热榜接口
XHS_HOTBOARD_URL = "https://uapis.cn/api/v1/misc/hotboard"

# 状态文件
LAST_CAPTURE_FILE = "xhs_last_capture.json"
PENDING_FILE = "xhs_pending.json"
SENT_FILE = "xhs_sent.json"

def get_xiaohongshu_hotboard():
    """从UAPIS获取小红书热榜"""
    if not UAPIS_API_KEY:
        print("未配置 UAPIS_API_KEY")
        return []
    headers = {"API-Key": UAPIS_API_KEY}
    params = {"type": "xiaohongshu"}
    try:
        resp = requests.get(XHS_HOTBOARD_URL, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == 200 and 'data' in data and 'list' in data['data']:
                hot_list = data['data']['list']
                posts = []
                for idx, item in enumerate(hot_list, start=1):
                    title = item.get('title', '').strip()
                    if not title:
                        continue
                    url = item.get('url', '')
                    note_id = item.get('id', '') or url.split('/')[-1]  # 尝试提取ID
                    if not note_id:
                        note_id = hashlib.md5(title.encode()).hexdigest()  # 临时ID
                    posts.append({
                        'note_id': note_id,
                        'title': title,
                        'url': url,
                        'hot_value': item.get('hot_value', 0),
                        'rank': idx
                    })
                return posts
            else:
                print(f"UAPIS 返回异常: {data}")
                return []
        else:
            print(f"UAPIS 请求失败: {resp.status_code}")
            return []
    except Exception as e:
        print(f"获取小红书热榜异常: {e}")
        return []

def load_json_set(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('ids', []))
    except FileNotFoundError:
        return set()

def save_json_set(filename, ids_set):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({'ids': list(ids_set)}, f)

def load_pending():
    try:
        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('items', [])
    except FileNotFoundError:
        return []

def save_pending(items):
    merged = {}
    for item in items:
        merged[item['note_id']] = item
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump({'items': list(merged.values())}, f, ensure_ascii=False)

def clear_pending():
    save_pending([])

def is_health_topic(title):
    prompt = f"""请判断以下小红书帖子标题是否属于健康/医疗/养生/科学育儿等相关话题。
标题：{title}
健康话题包括：疾病科普、就医经历、用药分享、症状讨论、养生方法、减肥经验、心理健康、医疗政策讨论、母婴育儿健康等。
不包括：纯商业广告（无实质健康内容）、娱乐八卦、明星日常、美食探店（非健康饮食类）、宠物日常（除非涉及人畜共患病）。
请只回答一个字：是 或 否。"""
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS_DEEPSEEK, json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是一个内容分类器，只输出是或否。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 10,
            "stream": False
        }, timeout=10)
        if resp.status_code == 200:
            answer = resp.json()['choices'][0]['message']['content'].strip()
            return "是" in answer
        else:
            return False
    except:
        return False

def send_to_dingtalk(webhook_url, secret, title, text):
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = f'{timestamp}\n{secret}'
    hmac_code = hmac.new(secret_enc, string_to_sign.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    webhook_url = f'{webhook_url}&timestamp={timestamp}&sign={sign}'

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    try:
        resp = requests.post(webhook_url, headers=headers, json=data)
        if resp.json().get('errcode') == 0:
            print("✅ 钉钉消息发送成功！")
        else:
            print(f"❌ 钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")

# ==================== 主程序 ====================
if __name__ == "__main__":
    RUN_MODE = os.environ.get('RUN_MODE', 'collect')
    print(f"当前模式：{RUN_MODE}")

    if RUN_MODE == 'collect':
        # ---------- 采集模式 ----------
        print("获取小红书热榜...")
        posts = get_xiaohongshu_hotboard()
        print(f"获取到 {len(posts)} 条热帖")

        last_ids = load_json_set(LAST_CAPTURE_FILE)
        current_ids = set()
        new_posts = []

        for post in posts:
            if not post['note_id']:
                continue
            current_ids.add(post['note_id'])
            if post['note_id'] not in last_ids:
                new_posts.append(post)

        print(f"其中 {len(new_posts)} 条为新上榜帖子")

        health_posts = []
        for post in new_posts:
            print(f"判断: {post['title']}")
            if is_health_topic(post['title']):
                health_posts.append(post)
                print("  ✅ 通过")
            else:
                print("  ❌ 拒绝")

        print(f"健康热帖：{len(health_posts)} 条")

        if health_posts:
            pending = load_pending()
            pending.extend(health_posts)
            save_pending(pending)
            print(f"已存入待发池，当前共 {len(pending)} 条。")

        save_json_set(LAST_CAPTURE_FILE, current_ids)
        print("已更新抓取记录。")

    elif RUN_MODE == 'summary':
        # ---------- 汇总推送模式 ----------
        webhook_url = os.environ.get('DINGTALK_WEBHOOK_XHS')
        secret = os.environ.get('DINGTALK_SECRET_XHS')
        if not webhook_url or not secret:
            print("钉钉凭证缺失")
            exit(1)

        pending = load_pending()
        if not pending:
            send_to_dingtalk(webhook_url, secret, "小红书健康热帖", "暂无新发现的健康热帖，等待下次更新。")
        else:
            sent_ids = load_json_set(SENT_FILE)
            new_items = [item for item in pending if item['note_id'] not in sent_ids]
            if not new_items:
                send_to_dingtalk(webhook_url, secret, "小红书健康热帖", "暂无新发现的健康热帖，等待下次更新。")
            else:
                messages = []
                for item in new_items:
                    title = item['title']
                    url = item.get('url', '')
                    hot = item.get('hot_value', item.get('rank', '?'))
                    messages.append(f"**{title}**\n🔥 热度：{hot}\n[查看原文]({url})\n")
                full_text = f"## 📕 小红书健康热帖\n\n" + "\n".join(messages)
                send_to_dingtalk(webhook_url, secret, "小红书健康热帖", full_text)

                sent_ids.update(item['note_id'] for item in new_items)
                save_json_set(SENT_FILE, sent_ids)

            clear_pending()
            print("已清空待发池。")
    else:
        print(f"未知模式：{RUN_MODE}")
