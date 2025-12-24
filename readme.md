# 📈 Subinfo Bot (Python Edition)

[中文说明](#中文说明) | [English Instructions](#english-instructions)

---

<a name="中文说明"></a>

## 📖 简介
这是一个从原版 TypeScript 插件深度移植并优化的 Python 版 Telegram 机器人。它专为机场订阅链接（Subscription Links）的多维度查询与管理而设计，支持流量统计、到期时间预测、节点协议识别及详细报告生成。

### ✨ 功能特性
* **详细流量统计**：实时解析已用流量（上传/下载）、剩余流量、总流量及可视化进度条。
* **协议与节点识别**：深度解析 Clash (YAML) 和 V2Ray/SS (Base64) 订阅，统计节点总数。
* **智能到期管理**：解析 Header 信息中的 `expire` 字段，自动计算到期日期与剩余天数。
* **机场信息匹配**：支持从远程 URL 加载配置，自动识别订阅链接对应的机场名称。
* **灵活输出**：支持直接发送富文本消息或导出为 `.txt` 文件报告，防止长消息被截断。

### 🚀 快速开始

#### 1. 系统要求
* Python 3.10+
* [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 框架

#### 2. 环境搭建
建议使用虚拟环境以避免依赖冲突：
```bash
# 创建并进入项目目录
mkdir subinfo-bot && cd subinfo-bot

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows 使用 .\venv\Scripts\activate

# 安装必要依赖
pip install python-telegram-bot httpx PyYAML beautifulsoup4 python-dateutil

3. 配置与启动
 * 在 subinfo_bot.py 中填入你的 TOKEN。
 * 运行脚本：
   python subinfo_bot.py

💡 使用方法
 * 普通查询：/subinfo [订阅链接]
 * 文件模式：/subinfo txt [订阅链接]
 * 回复查询：直接回复一条含有链接的消息并输入 /subinfo。
<a name="english-instructions"></a>
English Instructions
📖 Introduction
A robust Telegram Bot ported from the original TypeScript version, optimized for Python. It specializes in multi-dimensional querying of subscription links, offering traffic statistics, expiration analysis, and node protocol identification.
✨ Features
 * Traffic Analysis: Real-time tracking of Up/Down usage, remaining capacity, and visual progress bar.
 * Protocol Detection: Parses Clash (YAML) and V2Ray/SS (Base64) formats to count total nodes.
 * Expiration Tracking: Extracts expiration dates from headers to calculate remaining time.
 * Provider Identification: Automatically identifies airport names via remote mapping files.
 * Dual Output: Rich-text messages or .txt file exports for bulk queries.
🚀 Quick Start
 * Setup: python3 -m venv venv && source venv/bin/activate
 * Install: pip install python-telegram-bot httpx PyYAML beautifulsoup4 python-dateutil
 * Config: Replace TOKEN in the script.
 * Run: python subinfo_bot.py
💡 Usage
 * Query: /subinfo [Link]
 * TXT Mode: /subinfo txt [Link]
 * Reply Mode: Reply to any message containing links with /subinfo.
<!-- end list -->

---