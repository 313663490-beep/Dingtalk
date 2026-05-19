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

# 去重文件（从环境变量读取，默认使用 sent_topics_common.json）
CACHE_FILE = os.environ.get('SENT_TOPICS_FILE', 'sent_topics_common.json')
# 日累积文件
DAILY_FILE = os.environ.get('DAILY_FILE', 'daily_health_topics.json')

def load_sent_topics():
    """读取已发送的话题标题集合"""
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('topics', []))
    except FileNotFoundError:
        return set()

def save_sent_topics(topics):
    """保存当前所有健康话题标题（用于下次去重）"""
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'topics': list(topics)}, f, ensure_ascii=False)

# ==================== 1. 获取微博热搜 ====================
def get_weibo_hotspots():
    """使用微博官方公开接口获取热搜榜"""
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
                raw_title = item.get('word') or item.get('note') or item.get('title', '无标题')
                # 标准化标题
                title = ' '.join(raw_title.split())
                url = item.get('url', '')
                if not url:
                    url = f'https://s.weibo.com/weibo?q={urllib.parse.quote(title)}'
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
    """宽松判断，覆盖全健康场景"""
       prompt = f"""请用最宽松的标准判断以下微博热搜标题是否属于"健康全场景"。
健康全场景包括但不限于：
- 疾病、症状、治疗、药物、疫苗、医院、ICU、住院、手术、抢救、诊断、感染、中毒、过敏、流行病、食品安全、公共卫生。
- 饮食健康、营养、体重管理、减肥、增重、暴饮暴食、饮食误区、医嘱误解、食物中毒。
- 心理情绪：抑郁症、焦虑症、自杀干预、心理咨询，但排除纯心情抒发。
- 生活方式：健身、运动伤害、睡眠、熬夜、保健品、养生、美容整形（明确与健康相关）、衰老、死亡。
- 母婴：怀孕、生育、早产、育儿健康、母乳、月经、更年期。
- 环境健康：空气污染、水污染、辐射、虫害滋扰。
- 自然灾害与意外伤害：地震、洪水、台风、火灾、车祸、扶梯事故等直接造成人身伤亡或需紧急医疗救援的事件。
- 医疗制度与政策：医保改革、个人账户、异地结算、药品集采、医疗反腐、医患关系等。
- 科学辟谣（健康类）、医学科普。
即使标题包含明星姓名，只要涉及上述内容，必须判定为健康。

动物新闻规则：涉及人畜共患病、咬伤、狂犬病等影响人类健康的算健康；宠物去世、动物园趣事等不算。
拒绝示例："日本送给普京的秋田犬去世" → 否。
允许示例："女子被流浪狗咬伤后得狂犬病" → 是。

标题：{title}
请只回答一个字：是 或 否。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个健康话题过滤器，只输出是或否。"},
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

# ==================== 3. 生成专业话题+概述 ====================
def generate_professional_summaries(health_list):
    """为每条热搜生成专业话题名称、话题原标题和概述"""
    items_text = "\n".join([f"{item['rank']}. {item['title']}" for item in health_list])
        prompt = f"""你是专业健康信息分析师。以下是今日微博上与健康相关的完整热搜列表（含所有通过筛选的健康话题）：
{items_text}

请为其中**每条热搜**生成：
1. 一个专业话题名称和一个原标题（概括核心健康议题）。
2. 一句专业概述（100字以内），要求：
   - 聚焦健康风险或医疗要点。
   - **如果该话题与列表中其他热搜（特别是排名相邻或内容高度相关的话题）存在呼应关系，请在概述末尾简要提及这种关联**，例如"与热搜第2条内容高度呼应，聚焦XX事件"。

请严格按以下格式输出，每条一行，共{len(health_list)}行：
排名. 话题：... | 概述：...

输出示例：
1. 话题：医保个人账户新规 | 概述：国家医保局发布职工医保个账新规，明确支付白名单，禁止购买非医药类商品，强化家庭共济管理。
33. 话题：村庄癌症聚集与环境污染疑云 | 概述：武汉某村62人患癌，村民反映饮用水及化工污染问题，与热搜第2条内容高度呼应，呼吁权威医学与环境调查。

现在输入：
{items_text}

请输出："""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位专业健康信息分析师，只输出指定格式。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 1500,
        "stream": False
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code == 200:
            result_text = resp.json()['choices'][0]['message']['content'].strip()
            results = []
            lines = result_text.split('\n')
            for line in lines:
                if '话题：' in line and '概述：' in line:
                    try:
                        rank = int(line.split('.')[0].strip())
                    except:
                        continue
                    parts = line.split('|')
                    if len(parts) != 2:
                        continue
                    topic_part = parts[0].split('话题：')[1].strip()
                    summary_part = parts[1].split('概述：')[1].strip()
                    for item in health_list:
                        if item['rank'] == rank:
                            item_copy = item.copy()
                            item_copy['topic'] = topic_part
                            item_copy['summary'] = summary_part
                            results.append(item_copy)
                            break
            if len(results) == len(health_list):
                return results
            else:
                print(f"AI返回条目不匹配，回退到原始标题")
                return None
        else:
            print(f"生成专业摘要失败: {resp.status_code}")
            return None
    except Exception as e:
        print(f"生成专业摘要异常: {e}")
        return None

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
            print(f"✅ 钉钉消息发送成功！")
        else:
            print(f"❌ 钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")

# ==================== 主程序 ====================
if __name__ == "__main__":
    print("开始健康热搜筛选与纯标题去重...")
    hotspots = get_weibo_hotspots()
    if not hotspots:
        print("未获取到热搜数据，退出。")
        exit(1)

    health_list = []
    for item in hotspots:
        title = item['title']
        if not title:
            continue
        print(f"判断: {title}")
        if is_health_topic(title):
            health_list.append(item)
            print("  ✅ 通过")
        else:
            print("  ❌ 拒绝")

    print(f"共筛选出 {len(health_list)} 条健康热搜")

    # 读取多个群的钉钉凭证
    webhooks_str = os.environ.get('DINGTALK_WEBHOOKS', '')
    secrets_str = os.environ.get('DINGTALK_SECRETS', '')
    webhooks = [w.strip() for w in webhooks_str.split(',') if w.strip()]
    secrets = [s.strip() for s in secrets_str.split(',') if s.strip()]

    if not webhooks or not secrets or len(webhooks) != len(secrets):
        print("钉钉环境变量缺失或数量不匹配，无法发送")
        exit(1)

    if health_list:
        # 标准化标题
        for item in health_list:
            item['title'] = ' '.join(item['title'].split())

        current_titles = set(item['title'] for item in health_list)
        last_titles = load_sent_topics()

        # 纯标题去重：只保留上次没出现过的新标题
        new_health_list = [item for item in health_list if item['title'] not in last_titles]

        if not new_health_list:
            print("没有新增健康热搜，发送提示消息给所有群。")
            for i in range(len(webhooks)):
                send_to_dingtalk(webhooks[i], secrets[i], "健康热搜", "暂时没最新消息，等待下次更新。")
        else:
            print(f"发现 {len(new_health_list)} 条新增健康热搜")
            professional_items = generate_professional_summaries(new_health_list)
            
            if professional_items:
                messages = []
                for item in professional_items:
                    rank = item.get('rank', '?')
                    topic = item.get('topic', item['title'])
                    summary = item.get('summary', item['title'])
                    weibo_query = urllib.parse.quote(item['title'])
                    link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                    messages.append(f"话题：{topic}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")
                full_text = f"## 微博健康热搜播报\n\n" + "\n".join(messages)
            else:
                # 回退方案：使用原始标题
                messages = []
                for item in new_health_list:
                    rank = item.get('rank', '?')
                    title = item['title']
                    weibo_query = urllib.parse.quote(title)
                    link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                    messages.append(f"话题：{title}\n排位：{rank}\n概述：{title}\n链接：{link}\n")
                full_text = f"## 微博健康热搜播报\n\n" + "\n".join(messages)
            
            # 向所有群发送同样的消息
            for i in range(len(webhooks)):
                send_to_dingtalk(webhooks[i], secrets[i], "健康热搜", full_text)

        # 追加到日累积文件
        try:
            with open(DAILY_FILE, 'r', encoding='utf-8') as f:
                daily_data = json.load(f)
                daily_topics = set(daily_data.get('topics', []))
        except FileNotFoundError:
            daily_topics = set()
        daily_topics.update(current_titles)
        with open(DAILY_FILE, 'w', encoding='utf-8') as f:
            json.dump({'topics': list(daily_topics)}, f, ensure_ascii=False)
        print(f"已更新日累积文件，当前累计 {len(daily_topics)} 个话题。")

        # 更新去重状态文件（保存当前所有健康话题标题）
        save_sent_topics(current_titles)
        print("已更新去重状态文件。")
    else:
        print("今日无健康热搜，不发送消息。")
