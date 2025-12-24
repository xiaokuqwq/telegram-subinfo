import asyncio
import base64
import re
import time
import html
from datetime import datetime
from io import BytesIO

import httpx
import yaml
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# --- 静态配置 ---
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
REMOTE_MAPPINGS_URL = "https://raw.githubusercontent.com/Hyy800/Quantumult-X/refs/heads/Nana/ymys.txt"
REMOTE_CONFIG_MAPPINGS = {}
MAX_CONCURRENT_REQUESTS = 5  # 最大并发数

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
    parts = header.split(';')
    for part in parts:
        if '=' in part:
            k, v = part.split('=', 1)
            info[k.strip().lower()] = v.strip()
    return info

async def get_node_info(url: str):
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            data = resp.text
            # 1. 尝试 YAML
            try:
                config = yaml.safe_load(data)
                if isinstance(config, dict) and 'proxies' in config:
                    return {"count": len(config['proxies']), "detail": "Clash/Surge"}
            except: pass
            # 2. 尝试 Base64
            try:
                missing_padding = len(data) % 4
                if missing_padding: data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(data).decode('utf-8')
                lines = [l for l in decoded.splitlines() if '://' in l]
                if lines: return {"count": len(lines), "detail": "V2Ray/SS"}
            except: pass
        except: pass
    return None

async def load_remote_mappings():
    global REMOTE_CONFIG_MAPPINGS
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(REMOTE_MAPPINGS_URL)
            for line in resp.text.splitlines():
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    REMOTE_CONFIG_MAPPINGS[k.strip()] = v.strip()
        except Exception as e:
            print(f"加载映射失败: {e}")

async def process_sub(url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        headers = {'User-Agent': 'FlClash/v0.8.76 clash-verge'}
        async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {"success": False, "url": url, "error": f"HTTP {resp.status_code}"}
                
                user_info_raw = resp.headers.get('subscription-userinfo')
                if not user_info_raw:
                    return {"success": False, "url": url, "error": "无流量统计信息"}
                
                info = parse_user_info(user_info_raw)
                upload = int(info.get('upload', 0))
                download = int(info.get('download', 0))
                total = int(info.get('total', 0))
                expire_ts = int(info.get('expire', 0))
                
                used = upload + download
                remain = max(0, total - used)
                percent = round((used / total) * 100, 2) if total > 0 else 0
                
                name = "未知机场"
                for k, v in REMOTE_CONFIG_MAPPINGS.items():
                    if k in url:
                        name = v
                        break
                
                node_data = await get_node_info(url)
                return {
                    "success": True, "url": url, "name": name, "total": total, "used": used,
                    "remain": remain, "percent": percent, "expire_ts": expire_ts,
                    "node": node_data, "upload": upload, "download": download
                }
            except Exception as e:
                return {"success": False, "url": url, "error": str(e)}

# --- 消息处理器 ---

async def auto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg: return

    # 提取所有链接
    content = msg.text or msg.caption or ""
    urls = re.findall(r'https?://[^\s]+', content)

    # 如果是文件，读取内容并提取链接
    if msg.document and (msg.document.file_name.endswith('.txt') or msg.document.mime_type == 'text/plain'):
        doc_file = await context.bot.get_file(msg.document.file_id)
        byte_content = await doc_file.download_as_bytearray()
        file_text = byte_content.decode('utf-8', errors='ignore')
        urls.extend(re.findall(r'https?://[^\s]+', file_text))

    # 去重
    urls = list(dict.fromkeys(urls))
    if not urls: return # 如果没有发现链接，不执行任何操作

    status_msg = await msg.reply_text(f"🔍 识别到 {len(urls)} 个链接，正在查询...")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    tasks = [process_sub(url, semaphore) for url in urls]
    responses = await asyncio.gather(*tasks)

    results = []
    for res in responses:
        # 使用 HTML 模式转义，彻底解决解析报错问题
        safe_url = html.escape(res['url'])
        if not res["success"]:
            results.append(f"❌ <b>链接</b>: <code>{safe_url}</code>\n失败: {html.escape(res['error'])}")
            continue
        
        safe_name = html.escape(res['name'])
        filled = min(15, int(res['percent'] / 6.6))
        bar = "█" * filled + "░" * (15 - filled)
        expire_date = datetime.fromtimestamp(res['expire_ts']).strftime('%Y-%m-%d') if res['expire_ts'] > 0 else "永久/未知"
        
        output = (
            f"📄 <b>机场</b>: <code>{safe_name}</code>\n"
            f"🔗 <b>订阅</b>: <code>{safe_url}</code>\n"
            f"📊 <b>流量</b>: <code>[{bar}] {res['percent']}%</code>\n"
            f"总计: <code>{format_size(res['total'])}</code> | 剩余: <code>{format_size(res['remain'])}</code>\n"
            f"已用: <code>{format_size(res['used'])}</code> (↑{format_size(res['upload'])} ↓{format_size(res['download'])})\n"
            f"⏰ <b>到期</b>: <code>{expire_date}</code>"
        )
        if res['node']:
            output += f"\n🌐 <b>节点</b>: <code>{res['node']['count']}个 ({res['node']['detail']})</code>"
        results.append(output)

    final_text = "\n" + ("—"*15) + "\n\n".join(results)

    # 如果内容太长，自动转为文件发送
    if len(final_text) > 4000:
        clean_text = final_text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        file_data = BytesIO(clean_text.encode())
        file_data.name = f"result_{int(time.time())}.txt"
        await msg.reply_document(document=file_data, caption="✅ 查询结果过长，已生成文件报告")
        await status_msg.delete()
    else:
        await status_msg.edit_text(final_text, parse_mode=constants.ParseMode.HTML, disable_web_page_preview=True)

# --- 启动 ---

if __name__ == "__main__":
    asyncio.run(load_remote_mappings())
    app = ApplicationBuilder().token(TOKEN).build()
    
    # 使用 MessageHandler 监听所有包含文字和文件的消息
    # 只要消息里有 http 链接或者上传了 txt 文件，就会触发
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.Category("text/plain"), auto_handler))
    
    print("Bot 已启动，正在监听链接和 TXT 文件...")
    app.run_polling()
