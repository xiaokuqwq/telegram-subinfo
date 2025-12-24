import asyncio
import base64
import re
import time
import html
import logging
from datetime import datetime
from io import BytesIO

import aiohttp
import yaml
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# --- 日志配置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- 静态配置 ---
TOKEN = "你的_TELEGRAM_BOT_TOKEN"
REMOTE_MAPPINGS_URL = "https://raw.githubusercontent.com/Hyy800/Quantumult-X/refs/heads/Nana/ymys.txt"
REMOTE_CONFIG_MAPPINGS = {}

# 地区识别规则 (原版)
REGION_RULES = [
    ('香港', ['香港', 'hong kong', 'hongkong', 'hk', 'hkg']),
    ('台湾', ['台湾', 'taiwan', 'tw', 'taipei', 'tpe']),
    ('日本', ['日本', 'japan', 'jp', 'tokyo', 'osaka', 'jap']),
    ('新加坡', ['新加坡', 'singapore', 'sg', 'sgp']),
    ('韩国', ['韩国', 'korea', 'kr', 'seoul', 'kor']),
    ('美国', ['美国', 'united states', 'us', 'usa', 'los angeles', 'san jose']),
]

# 全局变量
GLOBAL_SEMAPHORE = asyncio.Semaphore(50)  # aiohttp 性能更好，并发可以开大一点
shared_session = None

# --- 工具函数 ---

def format_size(size: float) -> str:
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    level = 0
    while size >= 1024 and level < len(units) - 1:
        size /= 1024
        level += 1
    return f"{size:.2f} {units[level]}"

def parse_user_info(header: str):
    info = {}
    for part in header.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            info[k.strip().lower()] = v.strip()
    return info

def analyze_regions(proxies):
    stats = {}
    for p in proxies:
        name = str(p.get('name', '')).lower()
        found = False
        for region, keywords in REGION_RULES:
            if any(k in name for k in keywords):
                stats[region] = stats.get(region, 0) + 1
                found = True
                break
        if not found:
            stats['其他'] = stats.get('其他', 0) + 1
    
    if not stats: return "无有效节点"
    return " | ".join([f"{k}:{v}" for k, v in stats.items()])

async def fetch_node_info(url: str):
    """使用 aiohttp 获取节点详细信息"""
    try:
        async with shared_session.get(url, timeout=10) as resp:
            data = await resp.text()
            if 'proxies' in data:
                config = yaml.safe_load(data)
                proxies = config.get('proxies', [])
                return {"count": len(proxies), "detail": analyze_regions(proxies)}
            try:
                missing_padding = len(data) % 4
                if missing_padding: data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(data).decode('utf-8')
                lines = [l for l in decoded.splitlines() if '://' in l]
                if lines: return {"count": len(lines), "detail": f"{len(lines)}个通用节点"}
            except: pass
    except: pass
    return None

async def process_sub(url: str):
    """aiohttp 核心处理逻辑"""
    async with GLOBAL_SEMAPHORE:
        try:
            headers = {'User-Agent': 'Clash-Verge/1.0.0'}
            async with shared_session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return {"success": False, "url": url, "error": f"HTTP {resp.status}"}
                
                user_info = resp.headers.get('subscription-userinfo')
                if not user_info:
                    return {"success": False, "url": url, "error": "不返回流量Header"}
                
                info = parse_user_info(user_info)
                u, d, t, e = int(info.get('upload', 0)), int(info.get('download', 0)), int(info.get('total', 0)), int(info.get('expire', 0))
                
                used = u + d
                percent = round((used / t) * 100, 2) if t > 0 else 0
                name = next((v for k, v in REMOTE_CONFIG_MAPPINGS.items() if k in url), "未知机场")
                node = await fetch_node_info(url)
                
                return {
                    "success": True, "url": url, "name": name, "total": t, "used": used,
                    "remain": max(0, t - used), "percent": percent, "expire_ts": e,
                    "node": node, "up": u, "down": d
                }
        except Exception as err:
            return {"success": False, "url": url, "error": "连接超时/异常"}

# --- 消息处理器 ---

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg: return

    content = msg.text or msg.caption or ""
    urls = re.findall(r'https?://[^\s]+', content)

    if msg.document and (msg.document.file_name.endswith('.txt') or msg.document.mime_type == 'text/plain'):
        file = await msg.document.get_file()
        byte_content = await file.download_as_bytearray()
        urls.extend(re.findall(r'https?://[^\s]+', byte_content.decode('utf-8', errors='ignore')))

    urls = list(dict.fromkeys(urls))
    if not urls: return

    status_msg = await msg.reply_text("🚀 aiohttp 极速引擎处理中...")

    tasks = [process_sub(url) for url in urls]
    responses = await asyncio.gather(*tasks)

    results = []
    for res in responses:
        safe_url = html.escape(res['url'])
        if not res["success"]:
            results.append(f"❌ <b>解析失败</b>\n订阅: <code>{safe_url}</code>\n原因: {res['error']}")
            continue
        
        filled = min(15, int(res['percent'] / 6.6))
        bar = "█" * filled + "░" * (15 - filled)
        expire_date = datetime.fromtimestamp(res['expire_ts']).strftime('%Y-%m-%d') if res['expire_ts'] > 0 else "永久/未知"
        
        output = (
            f"📄 <b>机场名称</b>: <code>{html.escape(res['name'])}</code>\n"
            f"🏷️ <b>订阅链接</b>: <code>{safe_url}</code>\n"
            f"📊 <b>流量信息</b>:\n"
            f"预览: <code>[{bar}] {res['percent']}%</code>\n"
            f"总流量: <code>{format_size(res['total'])}</code>\n"
            f"已使用: <code>{format_size(res['used'])}</code> (↑{format_size(res['up'])} ↓{format_size(res['down'])})\n"
            f"剩余量: <code>{format_size(res['remain'])}</code>\n"
            f"⏰ <b>到期时间</b>: <code>{expire_date}</code>\n"
        )
        if res['node']:
            output += f"🌐 <b>节点信息</b>: <code>{res['node']['count']}个节点 ({res['node']['detail']})</code>"
        
        results.append(output)

    final_text = "\n" + ("="*20) + "\n\n".join(results)

    if len(final_text) > 4000:
        clean_text = re.sub('<[^<]+?>', '', final_text)
        bio = BytesIO(clean_text.encode())
        bio.name = "aio_report.txt"
        await msg.reply_document(document=bio, caption="✅ 批量查询完成")
        await status_msg.delete()
    else:
        await status_msg.edit_text(final_text, parse_mode=constants.ParseMode.HTML, disable_web_page_preview=True)

# --- 入口 ---

async def main():
    global shared_session
    # 初始化 aiohttp 连接池
    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    shared_session = aiohttp.ClientSession(connector=connector)

    # 加载映射
    try:
        async with shared_session.get(REMOTE_MAPPINGS_URL) as r:
            text = await r.text()
            for line in text.splitlines():
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    REMOTE_CONFIG_MAPPINGS[k.strip()] = v.strip()
    except: pass

    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.Category("text/plain"), handle_request))
    
    print(">>> aiohttp 极速并发版启动...")
    
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
    
    await shared_session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
