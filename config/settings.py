import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ========================================
# LLM 配置
# ========================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# ========================================
# WebSocket 配置
# ========================================
WS_URL = "wss://wss-goofish.dingtalk.com/"
COOKIES = os.getenv("COOKIES_STR")

if not COOKIES:
    logger.warning("未找到 COOKIES_STR，将提示用户输入")
    COOKIES = input("请输入COOKIES：")

# ========================================
# 消息处理配置
# ========================================
DEDUP_EXPIRE = 60  # 消息去重过期时间（秒）
REPLY_COOLDOWN = 3  # 用户防抖冷却时间（秒）

# ========================================
# 设备配置
# ========================================
MY_USER_ID = ""
DEVICE_ID = ""
CURRENT_TOKEN = None

# ========================================
# 线程池配置
# ========================================
MAX_WORKERS = 4
