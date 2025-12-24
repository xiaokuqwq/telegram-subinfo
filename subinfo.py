import asyncio
import base64
import re
import time
import io
from datetime import datetime
from io import BytesIO

import httpx
import yaml
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- 静态配置 ---
TOKEN = "你的_TELEGRAM_BOT_TOKEN"
REMOTE_MAPPINGS_URL = "https://raw.githubusercontent.com/Hyy800/Quantumult-X/refs/heads/Nana/ymys.txt"
REMOTE_CONFIG_MAPPINGS = {}
MAX_CONCURRENT_REQUESTS = 5  # 最大并发请求数

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
    async with httpx.AsyncClient(timeout=10.0) as client:
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
                if lines:
                    return {"count": len(lines), "detail": "V2Ray/SS"}
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

# --- 核心逻辑 ---

async def process_sub(url: str, semaphore: asyncio.Semaphore):
    # 使用信号量控制并发
    async with semaphore:
        headers = {'User-Agent': 'FlClash/v0.8.76 clash-verge'}
        async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {"success": False, "url": url, "error": f"HTTP {resp.status_code}"}
                
                user_info_raw = resp.headers.get('subscription-userinfo')
                if not user_info_raw:
                    return {"success": False, "url": url, "error": "无流量统计信息 (Header)"}
                
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

# --- 指令处理器 ---

async def subinfo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = msg.text or msg.caption or ""
    urls = []

    # 1. 提取链接 (当前消息、当前附件、回复的消息、回复的附件)
    urls.extend(re.findall(r'https?://[^\s]+', text))
    
    # 辅助函数：从文档中读取链接
    async def extract_from_doc(doc):
        if doc and (doc.file_name.endswith('.txt') or doc.mime_type == 'text/plain'):
            doc_file = await context.bot.get_file(doc.file_id)
            byte_content = await doc_file.download_as_bytearray()
            return re.findall(r'https?://[^\s]+', byte_content.decode('utf-8', errors='ignore'))
        return []

    if msg.document:
        urls.extend(await extract_from_doc(msg.document))

    if msg.reply_to_message:
        reply = msg.reply_to_message
        urls.extend(re.findall(r'https?://[^\s]+', reply.text or reply.caption or ""))
        if reply.document:
            urls.extend(await extract_from_doc(reply.document))

    urls = list(dict.fromkeys(urls))

    if not urls:
        await msg.reply_text("❌ 未找到订阅链接。\n发送链接、上传 .txt 文件或回复文件即可查询。", parse_mode=constants.ParseMode.MARKDOWN)
        return

    is_txt = "txt" in text.lower()
    status_msg = await msg.reply_text(f"⏳ 发现 {len(urls)} 个链接，正在并发查询...")

    # 使用信号量批量并发执行任务
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    tasks = [process_sub(url, semaphore) for url in urls]
    responses = await asyncio.gather(*tasks)

    results = []
    for res in responses:
        if not res["success"]:
            results.append(f"❌ 链接: `{res['url']}`\n失败: {res['error']}")
            continue
        
        filled = min(20, int(res['percent'] / 5))
        bar = "█" * filled + "░" * (20 - filled)
        expire_date = datetime.fromtimestamp(res['expire_ts']).strftime('%Y-%m-%d') if res['expire_ts'] > 0 else "永久/未知"
        
        output = (
            f"📄 *机场*: `{res['name']}`\n"
            f"🏷️ *订阅*: `{res['url']}`\n"
            f"📊 *流量*: `[{bar}] {res['percent']}%`\n"
            f"总计: `{format_size(res['total'])}` | 剩余: `{format_size(res['remain'])}`\n"
            f"已用: `{format_size(res['used'])}` (↑{format_size(res['upload'])} ↓{format_size(res['download'])})\n"
            f"⏰ *到期*: `{expire_date}`\n"
        )
        if res['node']:
            output += f"🌐 *节点*: `{res['node']['count']}个 ({res['node']['detail']})`"
        results.append(output)

    final_text = "\n" + ("—"*15) + "\n\n".join(results)

    if is_txt:
        file_data = BytesIO(final_text.replace("*", "").replace("`", "").encode())
        file_data.name = f"sub_report_{int(time.time())}.txt"
        await msg.reply_document(document=file_data, caption=f"✅ 已完成 {len(urls)} 个链接的批量查询")
        await status_msg.delete()
    else:
        if len(final_text) > 4000:
            final_text = final_text[:4000] + "\n\n...(内容过长，请使用 `/subinfo txt` 获取文件报告)"
        await status_msg.edit_text(final_text, parse_mode=constants.ParseMode.MARKDOWN, disable_web_page_preview=True)

# --- 启动 ---

if __name__ == "__main__":
    asyncio.run(load_remote_mappings())
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler(["subinfo", "cha"], subinfo_handler))
    print("Bot 已启动，支持 TXT 文件批量识别...")
    app.run_polling()
