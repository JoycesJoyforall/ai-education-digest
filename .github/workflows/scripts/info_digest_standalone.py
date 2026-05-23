#!/usr/bin/env python3
"""
AI + Education Information Digest Generator
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
# ============== 配置信息源 ==============
# X/Twitter 用户列表（通过 Nitter RSS 免费获取）
X_USERS = [
    ("drfeifei", "Fei-Fei Li"),
    ("emollick", "Ethan Mollick"),
    ("karpathy", "Andrej Karpathy"),
    ("simonw", "Simon Willison"),
    ("swyx", "Shawn Wang"),
    ("StanfordHAI", "Stanford HAI"),
]
# 网站 RSS 源
WEB_SOURCES = {
    "CAST": "https://www.cast.org/feed",
    "EdSurge": "https://www.edsurge.com/rss.xml",
    "Benetech": "https://benetech.org/feed/",
}
# YouTube 频道（需要 Channel ID）
YOUTUBE_CHANNELS = {
    "Andrej Karpathy": "UCnepndSK69NOOlu5Zv-rznw",
    "Edutopia": "UCdksngdLJN4bPaP3Wwm64yA",
}
# 手动检查源（只生成链接提醒）
MANUAL_SOURCES = {
    "MIT Lifelong Kindergarten": "https://www.media.mit.edu/groups/lifelong-kindergarten/",
    "Understood.org": "https://www.understood.org",
    "Common Sense Media - AI": "https://www.commonsensemedia.org/ai",
}
# Nitter RSS 服务（按优先级排序）
RSS_SERVICES = [
    "https://nitter.privacydev.net/{user}/rss",
    "https://nitter.net/{user}/rss",
    "https://nitter.cz/{user}/rss",
]
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
# ============== 工具函数 ==============
def fetch_url(url, timeout=15):
    """获取网页内容"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/rss+xml,application/xml,text/xml,*/*",
    }
    
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
                continue
            return f"ERROR: {str(e)[:100]}"
    return "ERROR: Failed after retries"
def parse_rss(xml_content, max_items=5):
    """解析 RSS XML"""
    items = []
    try:
        root = ET.fromstring(xml_content)
        
        # RSS 2.0
        if root.tag == "rss" or root.tag.endswith("rss"):
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item")[:max_items]:
                    title = item.find("title")
                    link = item.find("link")
                    pub_date = item.find("pubDate")
                    
                    items.append({
                        "title": _get_text(title) or "无标题",
                        "url": _get_text(link) or "",
                        "date": _get_text(pub_date) or "",
                    })
        
        # Atom
        elif root.tag.endswith("feed"):
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:max_items]:
                title = entry.find("atom:title", ns)
                link = entry.find("atom:link", ns)
                published = entry.find("atom:published", ns)
                
                items.append({
                    "title": _get_text(title) or "无标题",
                    "url": link.get("href") if link is not None else "",
                    "date": _get_text(published) or "",
                })
    except Exception as e:
        return [{"error": f"Parse error: {e}"}]
    
    return items
def _get_text(element):
    if element is None:
        return ""
    return element.text or ""
def _parse_date(date_str):
    """解析日期字符串"""
    if not date_str:
        return None
    
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None
def fetch_x_posts(username, display_name, since_hours=24):
    """获取 X/Twitter 用户最近帖子"""
    results = {"name": display_name, "posts": [], "error": None}
    
    for service_url in RSS_SERVICES:
        url = service_url.format(user=username)
        content = fetch_url(url, timeout=10)
        
        if not content.startswith("ERROR"):
            items = parse_rss(content, max_items=3)
            
            # 按时间过滤
            since_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            filtered = []
            
            for item in items:
                if "error" in item:
                    continue
                item_date = _parse_date(item.get("date", ""))
                if item_date and item_date < since_time:
                    continue
                filtered.append(item)
            
            results["posts"] = filtered
            return results
        
        time.sleep(0.5)
    
    results["error"] = "RSS服务暂时不可用"
    return results
def fetch_website(name, rss_url, since_hours=24):
    """获取网站 RSS"""
    results = {"name": name, "items": [], "error": None}
    
    content = fetch_url(rss_url, timeout=15)
    if content.startswith("ERROR"):
        results["error"] = content
        return results
    
    items = parse_rss(content, max_items=3)
    
    # 按时间过滤
    since_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    filtered = []
    
    for item in items:
        if "error" in item:
            continue
        item_date = _parse_date(item.get("date", ""))
        if item_date and item_date < since_time:
            continue
        filtered.append(item)
    
    results["items"] = filtered
    return results
def fetch_youtube(channel_name, channel_id, since_hours=24):
    """获取 YouTube 频道更新"""
    results = {"name": channel_name, "items": [], "error": None}
    
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    content = fetch_url(rss_url, timeout=15)
    
    if content.startswith("ERROR"):
        results["error"] = content
        return results
    
    items = parse_rss(content, max_items=3)
    
    # 按时间过滤
    since_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    filtered = []
    
    for item in items:
        if "error" in item:
            continue
        item_date = _parse_date(item.get("date", ""))
``` (1/2)
if item_date and item_date < since_time:
            continue
        filtered.append(item)
    
    results["items"] = filtered
    return results


# ============== 生成摘要 ==============

def generate_digest(since_hours=24):
    """生成信息摘要"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    period = "24小时" if since_hours <= 24 else "7天"
    
    lines = [
        f"📰 AI + Education {period}摘要",
        f"生成时间: {now}",
        "",
        "---",
        "",
    ]
    
    # 1. X/Twitter 更新
    lines.append("🐦 X / Twitter 更新")
    lines.append("")
    
    x_has_content = False
    for username, display_name in X_USERS:
        result = fetch_x_posts(username, display_name, since_hours)
        
        if result.get("error"):
            lines.append(f"• {display_name}: {result['error']}")
        elif result["posts"]:
            x_has_content = True
            lines.append(f"【{display_name}】")
            for post in result["posts"]:
                lines.append(f"  • {post['title'][:80]}...")
                if post['url']:
                    lines.append(f"    {post['url']}")
            lines.append("")
    
    if not x_has_content:
        lines.append("（暂无新内容或RSS服务暂时不可用）")
    lines.append("")
    
    # 2. 网站更新
    lines.append("🌐 网站更新")
    lines.append("")
    
    web_has_content = False
    for name, rss_url in WEB_SOURCES.items():
        result = fetch_website(name, rss_url, since_hours)
        
        if result.get("error"):
            lines.append(f"• {name}: 获取失败")
        elif result["items"]:
            web_has_content = True
            lines.append(f"【{name}】")
            for item in result["items"]:
                lines.append(f"  • {item['title'][:80]}")
                if item['url']:
                    lines.append(f"    {item['url']}")
            lines.append("")
    
    if not web_has_content:
        lines.append("（暂无新内容）")
    lines.append("")
    
    # 3. YouTube 更新
    lines.append("📺 YouTube 更新")
    lines.append("")
    
    yt_has_content = False
    for name, channel_id in YOUTUBE_CHANNELS.items():
        result = fetch_youtube(name, channel_id, since_hours)
        
        if result.get("error"):
            lines.append(f"• {name}: 获取失败")
        elif result["items"]:
            yt_has_content = True
            lines.append(f"【{name}】")
            for item in result["items"]:
                lines.append(f"  • {item['title'][:80]}")
                if item['url']:
                    lines.append(f"    {item['url']}")
            lines.append("")
    
    if not yt_has_content:
        lines.append("（暂无新内容）")
    lines.append("")
    
    # 4. 手动检查提醒
    lines.append("👀 手动检查源")
    lines.append("（以下源需要手动访问检查）")
    lines.append("")
    for name, url in MANUAL_SOURCES.items():
        lines.append(f"• {name}: {url}")
    lines.append("")
    
    # 页脚
    lines.append("---")
    lines.append("💡 提示：X/Twitter 通过 Nitter RSS 免费获取，可能偶尔不稳定")
    lines.append("🤖 由 GitHub Actions 自动生成")
    
    return "\n".join(lines)


# ============== 发送到飞书 ==============

def send_to_feishu(content):
    """发送消息到飞书"""
    if not FEISHU_WEBHOOK_URL:
        print("警告: 未设置 FEISHU_WEBHOOK_URL 环境变量")
        return False
    
    # 限制内容长度（飞书消息有长度限制）
    if len(content) > 3000:
        content = content[:2950] + "\n\n... (内容已截断)"
    
    payload = {
        "msg_type": "text",
        "content": {
            "text": content
        }
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            FEISHU_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0:
                print("✅ 飞书消息发送成功")
                return True
            else:
                print(f"❌ 飞书发送失败: {result}")
                return False
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False


# ============== 主程序 ==============

def main():
    parser = argparse.ArgumentParser(description="AI + Education Digest Generator")
    parser.add_argument("--daily", action="store_true", help="生成日报（24小时）")
    parser.add_argument("--weekly", action="store_true", help="生成周报（7天）")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--feishu", action="store_true", help="发送到飞书")
    
    args = parser.parse_args()
    
    # 确定时间范围
    if args.weekly:
        since_hours = 24 * 7
        print("📅 生成周报...")
    else:
        since_hours = 24
        print("📅 生成日报...")
    
    # 生成摘要
    digest = generate_digest(since_hours)
    
    # 保存到文件
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(digest)
        print(f"✅ 已保存到: {args.output}")
    
    # 打印到控制台
    print("\n" + "="*50)
    print(digest)
    print("="*50)
    
    # 发送到飞书
    if args.feishu:
        send_to_feishu(digest)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
