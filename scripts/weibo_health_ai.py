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

# 模式控制（collect / summary）
RUN_MODE = os.environ.get('RUN_MODE', 'collect')

# 去重文件（记录所有已发送的话题）
SENT_FILE = os.environ.get('SENT_TOPICS_FILE', 'sent_topics_common.json')
# 待发池文件（采集模式写入，汇总模式读取并清空）
PENDING_FILE = os.environ.get('PENDING_FILE', 'pending_health.json')
# 日累积文件（汇总模式更新）
DAILY_FILE = os.environ.get('DAILY_FILE', 'daily_health_topics.json')

def load_json_set(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('topics', []))
    except FileNotFoundError:
        return set()

def save_json_set(filename, topics_set):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({'topics': list(topics_set)}, f, ensure_ascii=False)

def load_pending():
    """读取待发池，返回列表 [{title, rank, url}, ...]"""
    try:
        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('items', [])
    except FileNotFoundError:
        return []

def save_pending(items):
    """保存待发池（用 title 去重，保留最新的 rank 和 url）"""
    merged = {}
    for item in items:
        title = item['title']
        merged[title] = item
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump({'items': list(merged.values())}, f, ensure_ascii=False)

def clear_pending():
    save_pending([])

# ==================== 1. 获取微博热搜 ====================
def get_weibo_hotspots():
    api_url = "https://weibo.com/ajax/side/hotSearch"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://weibo.com/"
    }
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if 'data' in data and 'realtime' in data['data']:
            realtime_list = data['data']['realtime']
            formatted = []
            for idx, item in enumerate(realtime_list, start=1):
                raw_title = item.get('word') or item.get('note') or item.get('title', '无标题')
                title = ' '.join(raw_title.split())
                url = item.get('url', '')
                if not url:
                    url = f'https://s.weibo.com/weibo?q={urllib.parse.quote(title)}'
                formatted.append({'title': title, 'rank': idx, 'url': url})
            print(f"成功获取 {len(formatted)} 条热搜")
            return formatted
        else:
            print(f"接口返回数据格式错误: {data}")
            return []
    except Exception as e:
        print(f"获取热搜失败: {e}")
        return []

# ==================== 2. AI判断是否健康话题 ====================
def is_health_topic(title):
    prompt = f"""请用最宽松的标准判断以下微博热搜标题是否属于"健康全场景"。
健康全场景包括但不限于：
- 疾病、症状、治疗、药物、疫苗、医院、ICU、住院、手术、抢救、诊断、感染、中毒、过敏、流行病、食品安全、公共卫生。
- 饮食健康、营养、体重管理、减肥、增重、暴饮暴食、饮食误区、医嘱误解、食物中毒。
- 心理情绪：抑郁症、焦虑症、自杀干预、心理咨询，但排除纯心情抒发。
- 生活方式：健身、运动伤害、睡眠、熬夜、保健品、养生、美容整形（明确与健康相关）、衰老、死亡。
- 母婴：怀孕、生育、早产、育儿健康、母乳、月经、更年期。
- 环境健康：空气污染、水污染、辐射、虫害滋扰。
- 自然灾害与意外伤害：地震、洪水、台风、火灾、车祸、扶梯事故等直接造成人身伤亡或需紧急医疗救援的事件。
- 医疗制度与政策：医保改革、医保个人账户、异地就医结算、药品集采、医疗反腐、医患关系、医保基金监管等。凡是标题中提到"医保""职工医保""医保个人账户""医保新规""医保改革""异地就医""医保基金""医保卡"等词语的，都必须判定为健康。
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

# ==================== 3. 豆包关联判断 ====================
def is_doubao_related(title):
    """判断健康话题是否与豆包/Doubao/字节AI直接相关"""
    prompt = f"""请判断以下健康热搜标题是否与"豆包"、"Doubao"、"字节跳动AI"直接相关。
只判断是否关联豆包这个AI产品，不判断是否为健康话题。
如果标题中明确提到"豆包"、"Doubao"、"字节AI"，或标题描述的事件核心与豆包AI的指导行为有关，请回答"是"。
如果标题是关于其他AI产品（如ChatGPT、文心一言等）或通用AI话题，请回答"否"。
标题：{title}
请只回答一个字：是 或 否。"""
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个话题关联判断器，只输出是或否。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 10,
        "stream": False
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=HEADERS, json=payload, timeout=10)
        if resp.status_code != 200:
            return False
        answer = resp.json()['choices'][0]['message']['content'].strip()
        return "是" in answer
    except Exception as e:
        print(f"豆包关联判断异常: {e}")
        return False

# ==================== 4. 生成专业概述（仅用于汇总播报） ====================
def generate_summaries(health_items):
    """为待发送的热搜列表生成概述，返回带 topic（原话题）和 summary 的列表"""
    items_text = "\n".join([f"{item['rank']}. {item['title']}" for item in health_items])
    prompt = f"""你是专业健康信息分析师。以下是待发送的健康热搜列表：
{items_text}

请为每条热搜生成一句专业概述（100字以内），聚焦健康风险或医疗要点。
严格按以下格式输出，每条一行，共{len(health_items)}行：
排名. 概述：...

输出示例：
1. 概述：国家医保局发布职工医保个账新规，明确支付白名单，禁止购买非医药类商品，强化家庭共济管理。
2. 概述：武汉某村62人患癌，村民反映饮用水及化工污染问题，呼吁权威医学与环境调查。

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
            results = {}
            for line in result_text.split('\n'):
                if '概述：' in line:
                    try:
                        rank = int(line.split('.')[0].strip())
                    except:
                        continue
                    summary = line.split('概述：')[1].strip()
                    results[rank] = summary
            for item in health_items:
                item['summary'] = results.get(item['rank'], item['title'])
            return health_items
        else:
            print(f"生成概述失败: {resp.status_code}")
            return None
    except Exception as e:
        print(f"生成概述异常: {e}")
        return None

# ==================== 5. 发送钉钉消息 ====================
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
        result = resp.json()
        if result.get('errcode') == 0:
            print("✅ 钉钉消息发送成功！")
        else:
            print(f"❌ 钉钉发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")

# ==================== 主程序 ====================
if __name__ == "__main__":
    print(f"当前模式：{RUN_MODE}")
    hotspots = get_weibo_hotspots()
    if not hotspots:
        print("未获取到热搜数据，退出。")
        exit(1)

    health_items = []
    for item in hotspots:
        title = item['title']
        if not title:
            continue
        print(f"判断: {title}")
        if is_health_topic(title):
            health_items.append(item)
            print("  ✅ 通过")
        else:
            print("  ❌ 拒绝")
    print(f"共筛选出 {len(health_items)} 条健康热搜")

    webhooks_str = os.environ.get('DINGTALK_WEBHOOKS', '')
    secrets_str = os.environ.get('DINGTALK_SECRETS', '')
    webhooks = [w.strip() for w in webhooks_str.split(',') if w.strip()]
    secrets = [s.strip() for s in secrets_str.split(',') if s.strip()]

    if RUN_MODE == 'collect':
        # ---------- 采集模式 ----------
        if health_items:
            for item in health_items:
                item['title'] = ' '.join(item['title'].split())
            pending = load_pending()
            pending_dict = {p['title']: p for p in pending}
            for item in health_items:
                pending_dict[item['title']] = item
            save_pending(list(pending_dict.values()))
            print(f"已更新待发池，当前共有 {len(pending_dict)} 个待发话题。")
        else:
            print("无健康热搜，待发池不变。")

    elif RUN_MODE == 'summary':
        # ---------- 汇总发送模式 ----------
        if not webhooks or not secrets or len(webhooks) != len(secrets):
            print("钉钉凭证缺失或不匹配，无法发送")
            exit(1)

        pending = load_pending()
        if not pending:
            print("待发池为空，发送提示消息。")
            for i in range(len(webhooks)):
                send_to_dingtalk(webhooks[i], secrets[i], "健康热搜", "暂时没最新消息，等待下次更新。")
        else:
            sent_set = load_json_set(SENT_FILE)
            new_items = [item for item in pending if item['title'] not in sent_set]
            if not new_items:
                print("待发池中的话题均已发送过，发送提示。")
                for i in range(len(webhooks)):
                    send_to_dingtalk(webhooks[i], secrets[i], "健康热搜", "暂时没最新消息，等待下次更新。")
            else:
                print(f"待发池共 {len(pending)} 条，其中 {len(new_items)} 条为新增。")
                # 生成概述并发送主健康播报
                summarized = generate_summaries(new_items)
                if summarized:
                    messages = []
                    for item in summarized:
                        rank = item.get('rank', '?')
                        title = item['title']
                        summary = item.get('summary', item['title'])
                        weibo_query = urllib.parse.quote(title)
                        link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                        messages.append(f"话题：{title}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")
                    full_text = f"## 微博健康热搜播报\n\n" + "\n".join(messages)
                else:
                    messages = []
                    for item in new_items:
                        rank = item.get('rank', '?')
                        title = item['title']
                        weibo_query = urllib.parse.quote(title)
                        link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                        messages.append(f"话题：{title}\n排位：{rank}\n概述：{title}\n链接：{link}\n")
                    full_text = f"## 微博健康热搜播报\n\n" + "\n".join(messages)

                for i in range(len(webhooks)):
                    send_to_dingtalk(webhooks[i], secrets[i], "健康热搜", full_text)

                # ---------- 豆包专项：筛选并单独推送 ----------
                doubao_items = []
                for item in new_items:
                    if is_doubao_related(item['title']):
                        doubao_items.append(item)
                if doubao_items:
                    doubao_summarized = generate_summaries(doubao_items)
                    if doubao_summarized:
                        doubao_messages = []
                        for item in doubao_summarized:
                            rank = item.get('rank', '?')
                            title = item['title']
                            summary = item.get('summary', item['title'])
                            weibo_query = urllib.parse.quote(title)
                            link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                            doubao_messages.append(f"话题：{title}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")
                        doubao_full_text = f"## 🤖 豆包相关健康话题\n\n" + "\n".join(doubao_messages)
                        for i in range(len(webhooks)):
                            send_to_dingtalk(webhooks[i], secrets[i], "豆包健康话题", doubao_full_text)
                        print(f"豆包专项：推送了 {len(doubao_items)} 条相关话题。")
                # ------------------------------------------------

                # 更新已发送集合和日累积
                sent_set.update(item['title'] for item in new_items)
                save_json_set(SENT_FILE, sent_set)

                daily_set = load_json_set(DAILY_FILE)
                daily_set.update(item['title'] for item in new_items)
                save_json_set(DAILY_FILE, daily_set)
                print(f"已更新日累积，当前共 {len(daily_set)} 个话题。")

            # 清空待发池
            clear_pending()
            print("已清空待发池。")

    else:
        print(f"未知模式：{RUN_MODE}，请设置 RUN_MODE 为 collect 或 summary。")
