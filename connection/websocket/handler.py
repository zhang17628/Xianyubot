import asyncio
import base64
import json
import os
import time
import threading
import concurrent.futures
from loguru import logger

from config.settings import DEDUP_EXPIRE, REPLY_COOLDOWN
from core.api.xianyu_api import XianyuAPI
from core.memory.context_manager import ChatContextManager
from core.agent.xianyubot_agent import XianyuReplyBot
from core.memory.intent_chain_analyzer import IntentChainAnalyzer, Intent, Emotion
from core.memory.conflict_detector import ConflictDetector
from utils.xianyu_utils import generate_mid, generate_uuid
from connection.websocket.message_parser import (
    parse_message_data, is_sync_package, extract_strings_from_binary, parse_dingtalk_binary
)


class MessageHandler:
    def __init__(self, api: XianyuAPI, my_user_id: str):
        self.api = api
        self.my_user_id = my_user_id
        self.bot = XianyuReplyBot()
        self.context_manager = ChatContextManager()

        # 意图链分析和冲突检测
        self.intent_chain_analyzer = IntentChainAnalyzer()
        self.conflict_detector = ConflictDetector()

        # 线程池
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        # 消息去重
        self._processed_messages = {}
        self._message_lock = threading.Lock()

        # 用户防抖
        self._user_last_reply = {}

    def _is_duplicate(self, msg_key: str) -> bool:
        """消息去重"""
        if not msg_key:
            return False
        now = time.time()
        with self._message_lock:
            expired = [k for k, v in self._processed_messages.items() if now - v > DEDUP_EXPIRE]
            for k in expired:
                del self._processed_messages[k]

            if msg_key in self._processed_messages:
                return True
            self._processed_messages[msg_key] = now
            return False

    def _in_cooldown(self, user_id: str) -> bool:
        """同一用户防抖"""
        if not user_id:
            return False
        now = time.time()
        last = self._user_last_reply.get(user_id, 0)
        if now - last < REPLY_COOLDOWN:
            return True
        self._user_last_reply[user_id] = now
        return False

    async def handle_message(self, message_data, ws):
        """处理新消息"""
        logger.debug(f"收到原始消息: {message_data}")

        try:
            # 1. 发送ACK确认
            try:
                if "headers" in message_data and "mid" in message_data["headers"]:
                    ack = {
                        "code": 200,
                        "headers": {
                            "mid": message_data["headers"].get("mid", generate_mid()),
                            "sid": message_data["headers"].get("sid", "")
                        }
                    }
                    await ws.send(json.dumps(ack))
            except Exception as e:
                logger.warning(f"发送ACK失败: {e}")

            # 2. 基本结构校验
            if not is_sync_package(message_data):
                return

            all_data = message_data["body"]["syncPushPackage"]["data"]

            replied = False
            for sync_data in all_data:
                if replied:
                    break
                object_type = sync_data.get("objectType", 0)
                if "data" not in sync_data:
                    continue
                raw_data = sync_data["data"]

                # 3. base64 解码
                try:
                    decoded_bytes = base64.b64decode(raw_data)
                except Exception as e:
                    logger.error(f"base64解码失败: {e}")
                    continue

                # 4. 尝试多种方式解析
                message = None

                # 4.1 msgpack 解析
                try:
                    import msgpack
                    message = msgpack.unpackb(decoded_bytes, raw=False, strict_map_key=False)
                    logger.info(f"[objectType={object_type}] msgpack(raw=False)解析成功")
                except Exception as e1:
                    try:
                        message = msgpack.unpackb(decoded_bytes, raw=True, strict_map_key=False)
                        logger.info(f"[objectType={object_type}] msgpack(raw=True)解析成功")
                    except Exception as e2:
                        try:
                            message = msgpack.unpackb(decoded_bytes)
                            logger.info(f"[objectType={object_type}] msgpack(默认)解析成功")
                        except Exception as e3:
                            logger.debug(f"msgpack全部失败: {e1} | {e2} | {e3}")

                # 4.2 手动解析 msgpack 二进制
                if message is None:
                    try:
                        import struct
                        message = parse_dingtalk_binary(decoded_bytes)
                        if message:
                            logger.info(f"[objectType={object_type}] 手动二进制解析成功")
                    except Exception as e:
                        logger.debug(f"手动解析失败: {e}")

                # 4.3 JSON 解析
                if message is None:
                    try:
                        message = json.loads(decoded_bytes.decode("utf-8"))
                        logger.info(f"[objectType={object_type}] JSON解析成功")
                    except Exception:
                        pass

                # 4.5 尝试直接从二进制中提取可读字符串
                if message is None:
                    try:
                        extracted = extract_strings_from_binary(decoded_bytes)
                        if extracted:
                            logger.info(f"[objectType={object_type}] 从二进制提取到字符串: {extracted}")
                            message = {"_extracted_strings": extracted, "_raw_hex": decoded_bytes[:100].hex()}
                    except Exception:
                        pass

                if message is None:
                    logger.warning(
                        f"[objectType={object_type}] 所有解析失败, 前100字节hex: {decoded_bytes[:100].hex()}")
                    continue

                # 5. 打印完整结构
                try:
                    msg_str = json.dumps(message, ensure_ascii=False,
                                         default=lambda x: x.decode('utf-8',
                                                                    errors='replace') if isinstance(x, bytes) else str(x))
                    logger.info(f"[objectType={object_type}] 完整结构: {msg_str[:800]}")
                except Exception:
                    logger.info(f"[objectType={object_type}] 完整结构(repr): {repr(message)[:800]}")

                # ===== 调试：dump 完整消息到文件，方便离线分析 =====
                try:
                    debug_dir = "data/debug_messages"
                    os.makedirs(debug_dir, exist_ok=True)
                    debug_file = os.path.join(debug_dir, f"msg_{int(time.time() * 1000)}_type{object_type}.json")

                    def make_serializable(obj):
                        if isinstance(obj, bytes):
                            try:
                                return obj.decode('utf-8')
                            except:
                                return f"<hex:{obj.hex()}>"
                        elif isinstance(obj, dict):
                            return {make_serializable(k): make_serializable(v) for k, v in obj.items()}
                        elif isinstance(obj, list):
                            return [make_serializable(i) for i in obj]
                        return obj

                    with open(debug_file, 'w', encoding='utf-8') as f:
                        json.dump(make_serializable(message), f, ensure_ascii=False, indent=2)
                    logger.info(f"📝 消息已保存到: {debug_file}")
                except Exception as e:
                    logger.warning(f"保存调试消息失败: {e}")

                # 6. 提取消息字段
                send_user_id, send_message, send_user_name, url_info, chat_id, image_url, is_image_message = \
                    parse_message_data(message)

                # 如果是图片消息但没有URL，尝试从API拉取
                if is_image_message and not image_url and chat_id:
                    logger.info(f"📷 确认为图片消息但WS推送中无图片URL，正在通过API拉取聊天记录...")
                    try:
                        fetched_url = self.api.extract_latest_image_url(chat_id)
                        if fetched_url:
                            image_url = fetched_url
                            logger.info(f"📷 ✅ 通过API成功获取图片URL: {image_url[:100]}")
                        else:
                            logger.warning(f"📷 ⚠️ API拉取聊天记录未找到图片URL")
                    except Exception as e:
                        logger.error(f"📷 ❌ API拉取图片URL失败: {e}")

                if not send_message and not image_url:
                    logger.debug(f"[objectType={object_type}] 未能提取到消息内容或图片，跳过")
                    continue

                if image_url and not send_message:
                    send_message = "[用户发送了一张图片]"
                    logger.info(f"📷 纯图片消息，已设置默认文本")

                if send_user_id and send_user_id == self.my_user_id:
                    logger.debug("是自己发送的消息，跳过")
                    continue

                dedup_key = f"{chat_id}:{send_user_id}:{send_message}"
                if self._is_duplicate(dedup_key):
                    logger.debug(f"⏭️ 重复消息，跳过: {dedup_key[:80]}")
                    continue

                cooldown_key = f"{chat_id}:{send_user_id}"
                if self._in_cooldown(cooldown_key):
                    logger.debug(f"⏭️ 用户 {send_user_id} 在冷却中，跳过")
                    continue

                # 7. 提取商品ID
                item_id = "0"
                if url_info and "itemId=" in url_info:
                    try:
                        item_id = url_info.split("itemId=")[1].split("&")[0]
                    except IndexError:
                        item_id = "0"

                if not chat_id:
                    chat_id = send_user_id or "unknown"
                if item_id == "0":
                    item_id = self.context_manager.get_latest_item_id_by_chat(chat_id)

                logger.info(
                    f"✅ 收到消息 - 用户: {send_user_name} (ID: {send_user_id}), "
                    f"商品: {item_id}, 会话: {chat_id}, "
                    f"消息: {send_message}, 图片: {image_url if image_url else '无'}")

                # 8. 获取商品信息并生成回复
                loop = asyncio.get_event_loop()
                item_desc = "未获取到具体商品信息，请根据常识和聊天上下文进行回复。"
                if item_id and item_id != "0":
                    item_data = self.context_manager.get_item_info(item_id)

                    if not item_data:
                        logger.info(f"本地无商品 {item_id} 缓存，正在请求API...")
                        api_res = await loop.run_in_executor(
                            self._executor, lambda: self.api.get_item_info(item_id)
                        )

                        if api_res and "data" in api_res:
                            raw_data = api_res.get("data", {})
                            item_data = {
                                "title": raw_data.get("item", {}).get("title", "未知商品"),
                                "soldPrice": raw_data.get("item", {}).get("price", "0"),
                                "desc": raw_data.get("item", {}).get("desc", "无详细描述"),
                            }
                            self.context_manager.save_item_info(item_id, item_data)

                    if item_data:
                        title = item_data.get("title", "未知")
                        price = item_data.get("soldPrice", "未知")
                        desc = item_data.get("desc", "无")
                        item_desc = f"商品名称：{title}\n标价：{price}元\n商品详细描述：{desc}"

                # 处理图片描述
                image_desc_for_memory = None
                if image_url:
                    try:
                        _img_url = image_url
                        _img_ctx = f"用户正在咨询商品，商品信息: {item_desc[:100]}"
                        image_desc_for_memory = await loop.run_in_executor(
                            self._executor,
                            lambda: self.context_manager.generate_image_description(_img_url, context=_img_ctx)
                        )
                        logger.info(f"📷 图片描述（存入长期记忆）: {image_desc_for_memory[:80]}...")
                    except Exception as e:
                        logger.warning(f"图片描述生成失败: {e}")

                # 新增：初始化并获取用户画像
                self.context_manager.init_user_profile(send_user_id)
                user_profile = await loop.run_in_executor(
                    self._executor,
                    lambda: self.context_manager.get_user_profile(send_user_id)
                )
                logger.debug(f"📊 获取用户画像: user_type={user_profile.get('user_type') if user_profile else 'unknown'}")

                # 获取上下文和生成回复
                _chat_id = chat_id
                _send_msg = send_message or ""
                history = await loop.run_in_executor(
                    self._executor,
                    lambda: self.context_manager.get_enriched_context(
                        chat_id=_chat_id,
                        current_message=_send_msg,
                        use_long_term=True
                    )
                )

                # 新增：获取意图链和冲突检测数据
                intent_chain_data = await loop.run_in_executor(
                    self._executor,
                    lambda: self.context_manager.get_intent_chain(chat_id)
                )

                conflict_data = await loop.run_in_executor(
                    self._executor,
                    lambda: self.context_manager.get_latest_conflicts(chat_id)
                )

                _item_desc = item_desc
                _history = history
                _image_url = image_url
                reply = await loop.run_in_executor(
                    self._executor,
                    lambda: self.bot.generate_reply(
                        _send_msg, _item_desc, _history, img_url=_image_url,
                        user_profile=user_profile,
                        intent_chain_data=intent_chain_data,
                        conflict_data=conflict_data
                    )
                )
                logger.info(f"准备回复: {reply}")

                # 9. 发送回复
                logger.info(f">>> 正在发送消息到 chat_id={chat_id}, user_id={send_user_id}")
                await self.send_ws_msg(ws, chat_id, send_user_id, reply)
                logger.info(">>> ✅ 消息发送成功")

                # 10. 存储对话记录
                safe_send_message = send_message if send_message else "[发送了一张图片]"
                current_item_info = None
                if item_id and item_id != "0":
                    current_item_info = self.context_manager.get_item_info(item_id)

                _save_args = {
                    "chat_id": chat_id, "send_user_id": send_user_id,
                    "item_id": item_id, "safe_send_message": safe_send_message,
                    "image_url": image_url, "image_desc": image_desc_for_memory,
                    "current_item_info": current_item_info,
                    "my_user_id": self.my_user_id, "reply": reply,
                    "last_intent": self.bot.last_intent,
                }

                def _save_context(args):
                    try:
                        self.context_manager.add_message_by_chat(
                            chat_id=args["chat_id"], user_id=args["send_user_id"],
                            item_id=args["item_id"], role='user',
                            content=args["safe_send_message"],
                            image_url=args["image_url"], image_desc=args["image_desc"],
                            item_info=args["current_item_info"]
                        )
                        self.context_manager.add_message_by_chat(
                            chat_id=args["chat_id"], user_id=args["my_user_id"],
                            item_id=args["item_id"], role='assistant',
                            content=args["reply"], item_info=args["current_item_info"]
                        )
                        if args["last_intent"] == "price":
                            self.context_manager.increment_bargain_count_by_chat(args["chat_id"])

                        # 新增：追踪意图链和冲突检测
                        self._track_intent_chain_and_conflicts(
                            chat_id=args["chat_id"],
                            user_id=args["send_user_id"],
                            current_intent=args["last_intent"]
                        )
                    except Exception as e:
                        logger.error(f"保存上下文失败: {e}")

                loop.run_in_executor(self._executor, _save_context, _save_args)

                replied = True
                logger.debug("✅ 已回复，跳过本批次剩余 sync_data")
                break

        except Exception as e:
            logger.error(f"处理消息出错: {e}")
            import traceback
            traceback.print_exc()

    async def send_ws_msg(self, ws, cid, toid, text):
        """通过WebSocket发送消息"""
        text_content = {
            "contenttype":1,
            "text":{"text":text}
        }
        text_base64 = base64.b64encode(json.dumps(text_content).encode("utf-8")).decode('utf-8')
        msg = {
            "lwp":"/r/MessageSend/sendByReceiverScope",
            "headers":{"mid":generate_mid()},
            "body":[{
                "uuid":generate_uuid(),
                "cid":f"{cid}@goofish",
                "conversationType":1,
                "content":{
                    "contentType":101,
                    "custom":{"type":1,"data":text_base64}
                },
                "redPointPolicy":0,
                "extension":{"extJson":"{}"},
                "ctx":{"appVersion":"1.0","platform":"web"},
                "mtags":{},
                "msgReadStatusSetting":1,
            },
                {
                    "actualReceivers":[
                        f"{toid}@goofish",
                        f"{self.my_user_id}@goofish"
                    ]
                }]

        }
        await ws.send(json.dumps(msg))

    def _track_intent_chain_and_conflicts(self, chat_id: str, user_id: str, current_intent: str):
        """
        追踪意图链和检测冲突

        这是一个异步的后台任务，不阻塞主消息处理流程
        """
        try:
            from datetime import datetime as dt

            # 获取用户的交互日志
            interaction_logs = self.context_manager.get_user_interaction_log(user_id, limit=100)

            if not interaction_logs:
                logger.debug(f"用户 {user_id} 无交互日志，跳过意图链追踪")
                return

            # 构建带有意图信息的消息列表
            messages_with_intents = []
            for idx, log in enumerate(interaction_logs):
                # 解析emotion（简化实现：基于关键词判断）
                message_text = log.get('message_text', '')
                emotion = self._analyze_emotion(message_text)

                # 处理timestamp：如果是字符串就保持字符串，如果是datetime就转换为字符串
                timestamp = log.get('timestamp')
                if timestamp and isinstance(timestamp, str):
                    # 已经是字符串，保持原样
                    pass
                elif timestamp:
                    # 是datetime对象，转换为字符串
                    timestamp = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)

                messages_with_intents.append({
                    'message_index': idx,
                    'text': message_text,
                    'intent': log.get('detected_intent', 'default') or 'default',
                    'confidence': 0.7,  # 简化：固定置信度
                    'emotion': emotion,
                    'keywords': log.get('keywords', []),
                    'timestamp': timestamp
                })

            # 追踪意图链
            intent_chain = self.intent_chain_analyzer.track_intent_evolution(
                chat_id=chat_id,
                user_id=user_id,
                messages_with_intents=messages_with_intents
            )

            # 保存意图链
            self.context_manager.save_intent_chain(chat_id, user_id, intent_chain)

            # 获取用户画像
            user_profile = self.context_manager.get_user_profile(user_id)

            # 检测冲突
            conflicts = self.conflict_detector.detect_conflicts(
                intent_chain=intent_chain,
                user_profile=user_profile,
                interaction_logs=interaction_logs
            )

            # 保存冲突检测结果
            if conflicts:
                self.context_manager.save_conflict_detection(chat_id, user_id, conflicts)
                logger.info(f"✅ 意图链和冲突检测完成: chat={chat_id}, 检测到{len(conflicts)}个冲突")
            else:
                logger.debug(f"✅ 意图链追踪完成，无明显冲突: chat={chat_id}")

        except Exception as e:
            logger.error(f"❌ 意图链追踪和冲突检测失败: {e}")
            import traceback
            traceback.print_exc()

    def _analyze_emotion(self, text: str) -> str:
        """
        分析文本的情感倾向（简化实现）

        在实际应用中，可以使用更复杂的NLP模型
        """
        # 负面关键词
        negative_keywords = ['不', '烦', '差', '坏', '讨厌', '糟糕', '贵', '太贵', '能不能便宜点', '砍价', '有问题', '缺陷', '磨损', '破损']
        # 积极关键词
        positive_keywords = ['好', '满意', '很好', '可以', '行', '没问题', '不错', '可以购买', '好的', '谢谢', '感谢', '确认', '同意', '购买']

        text_lower = text.lower()

        pos_count = sum(1 for kw in positive_keywords if kw in text_lower)
        neg_count = sum(1 for kw in negative_keywords if kw in text_lower)

        if pos_count > neg_count:
            return Emotion.POSITIVE.value
        elif neg_count > pos_count:
            return Emotion.NEGATIVE.value
        else:
            return Emotion.NEUTRAL.value

