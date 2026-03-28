import asyncio
from loguru import logger

from config.settings import COOKIES
from connection.websocket.manager import WebSocketManager
from connection.websocket.handler import MessageHandler


async def main():
    """主程序入口"""
    logger.info('🚀 闲鱼AI客服机器人启动中...')

    # 初始化WebSocket管理器
    ws_manager = WebSocketManager()

    # 初始化消息处理器
    message_handler = MessageHandler(ws_manager.api, ws_manager.my_user_id)

    # 启动WebSocket连接
    await ws_manager.connect_and_run(message_handler.handle_message)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('👋 程序已停止')
    except Exception as e:
        logger.error(f"❌ 程序运行出错: {e}")
