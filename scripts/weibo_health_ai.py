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

CACHE_FILE = "sent_topics.json"

def load_sent_topics():
    """读取上次发送的话题列表"""
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('topics', []))
    except FileNotFoundError:
        return set()

def save_sent_topics(topics):
    """保存本次发送的话题列表"""
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'topics': list(topics)}, f)

# ==================== 1. 获取微博热搜 (微博官方接口) ====================
def get_weibo_hotspots():
    """使用微博官方公开接口获取热搜榜（不获取时间）"""
    api_url = "https://weibo.com/ajax/side/hotSearch"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Referer": "https://weibo.com/"
    }
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if 'data' in data and 'realtime' in data['data']:
            realtime_list = data['data']['realtime']
            formatted_list = []
            for idx, item in enumerate(realtime_list, start=1):
                # 兼容不同字段名
                title = item.get('word') or item.get('note') or item.get('title', '无标题')
                # 优先用接口返回的链接
                url = item.get('url', '')
                if not url:
                    url = f'https://s.weibo.com/weibo?q={title}'
                formatted_list.append({
                    'title': title,
                    'rank': idx,
                    'url': url
                })
            print(f"成功获取 {len(formatted_list)} 条热搜")
            return formatted_list
        else:
            print(f"接口返回数据格式错误: {data}")
            return []
    except Exception as e:
        print(f"获取热搜失败: {e}")
        return []

# ==================== 2. AI判断是否健康话题 ====================
def is_health_topic(title):
    """严格判断，但明星关联的具体疾病/医疗事件必须纳入"""
    prompt = f"""请判断以下微博热搜标题是否属于“健康/医疗/疾病/公共卫生”领域。
绝对规则：
- 标题中如果直接出现以下词汇中的任意一个：ICU、重症监护室、住院、抢救、手术、治疗、出院、诊断、疫苗、感染、中毒、流行病、食品安全、公共卫生，则必须判定为健康话题。例如：“温岚在ICU接受治疗” → 是。
- 如果标题包含具体疾病名称（如败血症、糖尿病、抑郁症、癌症），即使与明星相关，也必须判定为健康。例如：“某某因抑郁症停工” → 是。
- 标题如果仅涉及明星外貌、身材、穿搭、综艺搞笑、演出延期、纯情感抒发，与具体健康问题无关，则判定为非健康。
- 情绪类：如果标题只是表达一时情绪（如“一会想通了一会又想不通”），不算健康；如果指向严重心理疾病（如抑郁症、焦虑症）或自杀干预，算健康。
标题：{title}
请只回答一个字：是 或 否。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个严格但遵循规则的健康话题过滤器，只输出是或否。"},
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

# ==================== 3. 生成单条概述 ====================
def generate_single_summary(title):
    """为一条健康热搜生成一句话专业概述"""
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
            summary = resp.json()['choices'][0]['message']['content'].strip()
            return summary
        else:
            print(f"概述生成失败，返回标题: {resp.status_code}")
            return title
    except Exception as e:
        print(f"概述生成异常: {e}")
        return title

# ==================== 4. 发送钉钉消息 ====================
def send_to_dingtalk(webhook_url, secret, title, text):
    """通过钉钉机器人发送 markdown 消息"""
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
            print("✅ 钉钉消息发送成功！")
        else:
            print(f"❌ 钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")

# ==================== 主程序 ====================
if __name__ == "__main__":
    print("开始健康热搜筛选与去重播报...")
    hotspots = get_weibo_hotspots()

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
            print("  ✅ 通过")
        else:
            print("  ❌ 拒绝")

    print(f"共筛选出 {len(health_list)} 条健康热搜")

    webhook_url = os.environ.get('DINGTALK_WEBHOOK')
    secret = os.environ.get('DINGTALK_SECRET')

    if not webhook_url or not secret:
        print("钉钉环境变量缺失，无法发送")
        exit(1)

    if health_list:
        current_titles = set(item['title'] for item in health_list)
        last_titles = load_sent_topics()

        if current_titles == last_titles:
            print("健康热搜列表与上次完全相同，跳过发送。")
        else:
            messages = []
            for item in health_list:
                rank = item.get('rank', '?')
                title = item['title']
                weibo_query = urllib.parse.quote(title)
                link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                summary = generate_single_summary(title)
                messages.append(f"话题：{title}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")

            full_text = f"## 微博健康热搜播报\n\n" + "\n".join(messages)
            send_to_dingtalk(webhook_url, secret, "健康热搜", full_text)
            # 发送成功后更新缓存
            save_sent_topics(current_titles)
            print("已更新去重缓存。")
    else:
        print("今日无健康热搜，不发送消息。")
