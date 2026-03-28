import asyncio
import json
import time
from loguru import logger
import websockets

from config.settings import WS_URL, COOKIES, MAX_WORKERS
from core.api.xianyu_api import XianyuAPI
from utils.xianyu_utils import generate_device_id, generate_mid, generate_uuid


class WebSocketManager:
    def __init__(self):
        self.ws_url = WS_URL
        self.cookies = COOKIES
        self.api = XianyuAPI(COOKIES)
        self.current_token = None
        self.my_user_id = ""
        self.device_id = ""

        # 初始化用户ID
        try:
            self.my_user_id = self.api.cookies.get("unb", "")
            if self.my_user_id:
                logger.info(f"登录成功，当前用户ID: {self.my_user_id}")
            else:
                logger.warning(f"无法获取当前用户ID，可能会导致用户自己回复自己")
        except:
            pass

        self.device_id = generate_device_id(self.my_user_id)

    async def get_token(self):
        """获取WebSocket连接所需的token"""
        try:
            token_result = self.api.get_token(self.device_id)
            if 'data' in token_result and "accessToken" in token_result['data']:
                self.current_token = token_result['data']['accessToken']
                logger.info("Token获取成功")
                return self.current_token
            else:
                logger.error(f"Token 获取失败:{token_result}")
                return None
        except Exception as e:
            logger.error(f"Token 获取异常{e}")
            return None

    async def ws_init(self, ws):
        """WebSocket连接初始化：发送注册包"""
        if not self.current_token:
            await self.get_token()

        if not self.current_token:
            raise Exception("无法获取有效Token")

        reg_msg = {
            "lwp":"/reg",
            "headers":{
                "cache-header":"app-key token ua wv",
                "app-key":"444e9908a51d1cb236a27862abc769c9",
                "token":self.current_token,
                "ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                "dt":'j',
                "wv":"im:3,au:3,sy:6",
                "sync":"0,0;0,0;",
                "did":self.device_id,
                "mid":generate_mid()
            }
        }
        await ws.send(json.dumps(reg_msg))
        await asyncio.sleep(1)

        sync_msg = {
            "lwp":"/r/SyncStatus/ackDiff",
            "headers":{"mid":generate_mid()},
            "body":[{
                "pipline":"sync",
                "tooLong2Tag":"PNM,1",
                "channel":"sync",
                "topic":"sync",
                "highPts":0,
                "pts":int(time.time()*1000) * 1000,
                "seq":0,
                "timestamp":int(time.time()*1000)
            }]
        }
        await ws.send(json.dumps(sync_msg))
        logger.info("连接注册完成")

    async def send_heartbeat(self, ws):
        """发送心跳包"""
        try:
            heartbeat_msg = {
                "lwp": "/!",
                "headers": {
                    "mid": generate_mid()
                }
            }
            await ws.send(json.dumps(heartbeat_msg))
            logger.debug("心跳包已发送")
        except Exception as e:
            logger.error(f"发送心跳包失败: {e}")
            raise

    async def heartbeat_loop(self, ws):
        """心跳维护循环，每15秒发送一次"""
        while True:
            try:
                await asyncio.sleep(30)
                await self.send_heartbeat(ws)
            except Exception as e:
                logger.error(f"心跳循环出错: {e}")
                break

    async def connect_and_run(self, message_handler):
        """
        连接到WebSocket并处理消息
        message_handler: 消息处理回调函数
        """
        logger.info('闲鱼客服正在启动...')
        while True:
            heartbeat_task = None
            try:
                # ✅ 完整的请求头，模拟浏览器行为
                headers = {
                    "Cookie": self.cookies,
                    "Host": "wss-goofish.dingtalk.com",
                    "Connection": "Upgrade",
                    "Pragma": "no-cache",
                    "Cache-Control": "no-cache",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Origin": "https://www.goofish.com",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
                async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
                    logger.success("已成功连接到闲鱼WebSocket服务器")

                    await self.ws_init(ws)

                    heartbeat_task = asyncio.create_task(self.heartbeat_loop(ws))

                    async for message in ws:
                        try:
                            message_data = json.loads(message)

                            if (isinstance(message_data, dict)
                                    and "code" in message_data
                                    and message_data["code"] == 200
                                    and "lwp" not in message_data):
                                logger.debug("收到心跳/ACK响应")
                                continue

                            await message_handler(message_data, ws)
                        except json.JSONDecodeError:
                            logger.error("消息JSON解析失败")
                        except Exception as e:
                            logger.error(f"处理消息时发生错误: {str(e)}")
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket连接已关闭: {e}")
            except Exception as e:
                logger.error(f"连接发生错误: {e}")
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                logger.info("等待5秒后重连...")
                await asyncio.sleep(5)
