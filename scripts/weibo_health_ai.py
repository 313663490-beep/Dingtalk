import requests
import os
import time
import hmac
import hashlib
import base64
import urllib.parse

# ==================== 配置 ====================
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}

# ==================== 1. 获取微博热搜 (夏柔API) ====================
def get_weibo_hotspots():
    """使用夏柔免费API获取微博热搜榜（含排名）"""
    api_url = "https://zj.v.api.aa1.cn/api/weibo-rs/"
    try:
        resp = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == 1:
            items = data.get('data', [])
            # 确保排名字段存在，如果接口返回的字段是 'index' 则保留原样
            for idx, item in enumerate(items):
                # 以防接口返回的排名字段名不一样，统一用 'rank'
                if 'index' in item:
                    item['rank'] = item['index']
                elif 'rank' not in item:
                    # 如果都没有，就用列表顺序作为排名
                    item['rank'] = idx + 1
            time_str = time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"成功获取 {len(items)} 条热搜")
            return items, time_str
        else:
            print(f"热搜API返回错误: {data}")
            return [], None
    except Exception as e:
        print(f"获取热搜失败: {e}")
        return [], None

# ==================== 2. AI判断是否健康话题 ====================
def is_health_topic(title):
    """严格判断，但允许明星关联的具体疾病/医疗事件"""
    prompt = f"""请判断以下微博热搜标题是否属于“健康/医疗/疾病/公共卫生”领域。
重要规则：
- 标题如果包含具体疾病（如败血症、癌症、高血压）、症状、治疗、药物、医院、疫苗、食品安全、公共卫生、科学辟谣(健康)、严重心理疾病等，哪怕提到了明星或其他公众人物，也必须判定为健康话题。例如：“温岚因败血症进入ICU” → 是；“某某患抑郁症” → 是；“某某膝盖手术成功” → 是。
- 标题如果仅涉及明星外貌、身材、穿搭、综艺搞笑、纯情感抒发、演出延期等，与具体健康问题无关，则判定为非健康。
- 情绪心理类：明确指向心理疾病（如抑郁症、焦虑症）或专业心理援助的，算健康；仅表达一时情绪波动（如“一会想通了一会又想不通”）不算。
标题：{title}
请只回答一个字：是 或 否。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个健康话题过滤器，严格按规则只输出是或否。"},
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
    print("开始执行严格健康热搜筛选...")
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
        messages = []
        for item in health_list:
            rank = item.get('rank', '?')
            title = item['title']
            # 生成带排名的微博搜索链接
            weibo_query = urllib.parse.quote(title)
            link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
            
            summary = generate_single_summary(title)
            messages.append(f"话题：{title}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")

        full_text = f"## 微博健康热搜播报\n**数据时间：{time_str}**\n\n" + "\n".join(messages)
        send_to_dingtalk(webhook_url, secret, "每日健康热搜", full_text)
    else:
        print("今日无健康热搜，不发送消息。")
