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

# 去重文件（理财专用）
CACHE_FILE = "sent_topics_finance.json"
# 日累积文件
DAILY_FILE = "daily_finance_topics.json"

def load_sent_topics():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('topics', []))
    except FileNotFoundError:
        return set()

def save_sent_topics(topics):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'topics': list(topics)}, f, ensure_ascii=False)

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

# ==================== 2. AI判断是否理财话题 ====================
def is_finance_topic(title):
    prompt = f"""请用最宽松的标准判断以下微博热搜标题是否属于“理财/投资/财经”领域。
理财话题包括但不限于：
- 存款、存钱、攒钱、搞钱、省钱、省钱技巧等与个人资金管理直接相关的话题。
- 股票、基金、债券、黄金、外汇、加密货币、期货等投资品种。
- 银行理财、保险理财、信托、资管新规、利率变化。
- 楼市政策、房贷利率、房价走势、房产投资。
- 个人所得税、企业税、印花税、社保公积金等财税政策。
- 养老金、个人养老金账户、退休规划、社保改革。
- 创业投资、独角兽、IPO、融资、并购、市值。
- 财经名人观点、机构研报、经济数据（CPI、GDP等）。
- 消费金融、信用卡、花呗、借呗、反诈骗提醒（涉及钱财）。
- 明确排除：明星发红包、转发抽奖、娱乐八卦、体育赛事、自然灾害等与个人/家庭理财无关的话题。

标题：{title}
请只回答一个字：是 或 否。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个理财话题过滤器，只输出是或否。"},
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
def generate_finance_summaries(finance_list):
    items_text = "\n".join([f"{item['rank']}. {item['title']}" for item in finance_list])
    prompt = f"""你是专业的财经分析师。以下是今日微博上与理财/财经相关的热搜列表：
{items_text}

请为**每条热搜**生成：
1. 一个专业话题名称（概括核心财经议题，例如“个人养老金制度落地”、“存款技巧讨论”）。
2. 一句专业概述（100字以内），简明扼要地说明新闻要点和潜在影响。

请严格按以下格式输出，每条一行，共{len(finance_list)}行：
排名. 话题：... | 概述：...

输出示例：
1. 话题：个人养老金账户新规 | 概述：个人养老金账户试点扩大，每年1.2万缴费上限不变，可投资公募基金等产品，利好长期理财规划。
2. 话题：年轻人攒钱新趋势 | 概述：热搜反映年轻群体开始重视强制储蓄，定期存款和货币基金受青睐，有助于个人财务安全垫构建。

现在输入：
{items_text}

请输出："""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位专业财经分析师，只输出指定格式。"},
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
                    topic = parts[0].split('话题：')[1].strip()
                    summary = parts[1].split('概述：')[1].strip()
                    for item in finance_list:
                        if item['rank'] == rank:
                            item_copy = item.copy()
                            item_copy['topic'] = topic
                            item_copy['summary'] = summary
                            results.append(item_copy)
                            break
            if len(results) == len(finance_list):
                return results
            else:
                print(f"AI返回条目不匹配，回退到原始标题")
                return None
        else:
            print(f"生成摘要失败: {resp.status_code}")
            return None
    except Exception as e:
        print(f"生成摘要异常: {e}")
        return None

# ==================== 4. 发送钉钉消息 ====================
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

# ==================== 主程序 ====================
if __name__ == "__main__":
    print("开始理财话题筛选与去重...")
    hotspots = get_weibo_hotspots()
    if not hotspots:
        print("未获取到热搜数据，退出。")
        exit(1)

    finance_list = []
    for item in hotspots:
        title = item['title']
        if not title:
            continue
        print(f"判断: {title}")
        if is_finance_topic(title):
            finance_list.append(item)
            print("  ✅ 通过")
        else:
            print("  ❌ 拒绝")

    print(f"共筛选出 {len(finance_list)} 条理财热搜")

    webhook_url = os.environ.get('DINGTALK_WEBHOOK_FINANCE')
    secret = os.environ.get('DINGTALK_SECRET_FINANCE')
    if not webhook_url or not secret:
        print("钉钉环境变量缺失，无法发送")
        exit(1)

    if finance_list:
        for item in finance_list:
            item['title'] = ' '.join(item['title'].split())

        current_titles = set(item['title'] for item in finance_list)
        last_titles = load_sent_topics()

        new_finance_list = [item for item in finance_list if item['title'] not in last_titles]

        if not new_finance_list:
            print("没有新增理财热搜，发送提示消息。")
            send_to_dingtalk(webhook_url, secret, "理财热搜", "暂时没最新理财消息，等待下次更新。")
        else:
            print(f"发现 {len(new_finance_list)} 条新增理财热搜")
            professional_items = generate_finance_summaries(new_finance_list)
            
            if professional_items:
                messages = []
                for item in professional_items:
                    rank = item.get('rank', '?')
                    topic = item.get('topic', item['title'])
                    summary = item.get('summary', item['title'])
                    weibo_query = urllib.parse.quote(item['title'])
                    link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                    messages.append(f"话题：{topic}\n排位：{rank}\n概述：{summary}\n链接：{link}\n")
                full_text = f"## 微博理财热搜播报\n\n" + "\n".join(messages)
            else:
                messages = []
                for item in new_finance_list:
                    rank = item.get('rank', '?')
                    title = item['title']
                    weibo_query = urllib.parse.quote(title)
                    link = f"https://s.weibo.com/weibo?q={weibo_query}&t=31&band_rank={rank}&Refer=top"
                    messages.append(f"话题：{title}\n排位：{rank}\n概述：{title}\n链接：{link}\n")
                full_text = f"## 微博理财热搜播报\n\n" + "\n".join(messages)
            
            send_to_dingtalk(webhook_url, secret, "理财热搜", full_text)

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

        save_sent_topics(current_titles)
        print("已更新去重状态文件。")
    else:
        print("今日无理财热搜，不发送消息。")
