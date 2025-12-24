import asyncio
import base64
import re
import time
import html
import logging
from datetime import datetime
from io import BytesIO

import httpx
import yaml
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# --- 日志配置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- 静态配置 ---
TOKEN = "你的_TELEGRAM_BOT_TOKEN"
REMOTE_MAPPINGS_URL = "https://raw.githubusercontent.com/Hyy800/Quantumult-X/refs/heads/Nana/ymys.txt"
REMOTE_CONFIG_MAPPINGS = {}

# 全局并发限制：控制全系统同时进行的网络请求数量
GLOBAL_SEMAPHORE = asyncio.Semaphore(30)

# 全局共享 HTTP 客户端（自动管理连接池）
shared_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
    follow_redirects=True,
    headers={'User-Agent': 'Clash-Verge/1.0.0 (Windows NT 10.0; Win64; x64) Meta/1.18.0'}
)

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

async def load_remote_mappings():
    """初始化加载远程映射表"""
    global REMOTE_CONFIG_MAPPINGS
    try:
        resp = await shared_client.get(REMOTE_MAPPINGS_URL)
        for line in resp.text.splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                REMOTE_CONFIG_MAPPINGS[k.strip()] = v.strip()
        logging.info("远程映射表加载成功")
    except Exception as e:
        logging.error(f"加载映射失败: {e}")

async def get_node_info(url: str):
    """异步获取节点数"""
    try:
        resp = await shared_client.get(url)
        data = resp.text
        if 'proxies' in data:
            config = yaml.safe_load(data)
            return {"count": len(config.get('proxies', [])), "detail": "Clash"}
        try:
            missing_padding = len(data) % 4
            if missing_padding: data += '=' * (4 - missing_padding)
            decoded = base64.b64decode(data).decode('utf-8')
            lines = [l for l in decoded.splitlines() if '://' in l]
            if lines: return {"count": len(lines), "detail": "V2Ray/SS"}
        except: pass
    except: pass
    return None

async def process_sub(url: str):
    """处理单个链接"""
    async with GLOBAL_SEMAPHORE:
        try:
            resp = await shared_client.get(url)
            if resp.status_code != 200:
                return {"success": False, "url": url, "error": f"HTTP {resp.status_code}"}
            
            user_info_raw = resp.headers.get('subscription-userinfo')
            if not user_info_raw:
                return {"success": False, "url": url, "error": "无流量统计Header"}
            
            info = parse_user_info(user_info_raw)
            u, d, t, e = int(info.get('upload', 0)), int(info.get('download', 0)), int(info.get('total', 0)), int(info.get('expire', 0))
            
            used = u + d
            percent = round((used / t) * 100, 2) if t > 0 else 0
            name = next((v for k, v in REMOTE_CONFIG_MAPPINGS.items() if k in url), "未知机场")
            node = await get_node_info(url)
            
            return {
                "success": True, "url": url, "name": name, "total": t, "used": used,
                "remain": max(0, t - used), "percent": percent, "expire_ts": e,
                "node": node, "up": u, "down": d
            }
        except Exception:
            return {"success": False, "url": url, "error": "连接超时/失败"}

# --- 消息处理器 ---

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg: return

    # 1. 提取 URL
    content = msg.text or msg.caption or ""
    urls = re.findall(r'https?://[^\s]+', content)

    # 2. 处理文本附件
    if msg.document and (msg.document.file_name.endswith('.txt') or msg.document.mime_type == 'text/plain'):
        file = await msg.document.get_file()
        byte_content = await file.download_as_bytearray()
        urls.extend(re.findall(r'https?://[^\s]+', byte_content.decode('utf-8', errors='ignore')))

    urls = list(dict.fromkeys(urls))
    if not urls: return

    status_msg = await msg.reply_text("🚀 正在并发查询，请稍候...")

    # 3. 并发派发任务
    tasks = [process_sub(url) for url in urls]
    responses = await asyncio.gather(*tasks)

    # 4. 拼装结果
    results = []
    for res in responses:
        safe_url = html.escape(res['url'])
        if not res["success"]:
            results.append(f"❌ <code>{safe_url}</code> | <b>{res['error']}</b>")
            continue
        
        filled = min(10, int(res['percent'] / 10))
        bar = "█" * filled + "░" * (10 - filled)
        expire = datetime.fromtimestamp(res['expire_ts']).strftime('%Y-%m-%d') if res['expire_ts'] > 0 else "无限"
        
        item = (
            f"📄 <b>{html.escape(res['name'])}</b>\n"
            f"📊 <code>{bar} {res['percent']}%</code>\n"
            f"余: <code>{format_size(res['remain'])}</code> | 到期: <code>{expire}</code>\n"
            f"🔗 <code>{safe_url}</code>"
        )
        results.append(item)

    final_output = "\n\n".join(results)
    
    if len(final_output) > 4000:
        # 移除HTML标签生成纯文本文件
        clean_text = re.sub('<[^<]+?>', '', final_output)
        bio = BytesIO(clean_text.encode())
        bio.name = "result.txt"
        await msg.reply_document(document=bio, caption="✅ 查询完成，结果见文件")
        await status_msg.delete()
    else:
        await status_msg.edit_text(final_output, parse_mode=constants.ParseMode.HTML, disable_web_page_preview=True)

# --- 主入口 ---

async def main():
    # 1. 先加载远程数据
    await load_remote_mappings()
    
    # 2. 构建应用并开启并发处理
    # concurrent_updates=True 允许同时处理多个用户的消息
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()
    
    # 3. 注册处理器
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.Category("text/plain"), handle_request))
    
    print(">>> 工业级并发 Bot 已启动...")
    
    # 4. 运行
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        # 保持运行
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
