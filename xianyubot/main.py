import asyncio
import base64
import json
import os
import time
import threading

import websockets
from dotenv import load_dotenv
from loguru import logger

from xianyu_agent.xianyubot.XianyuAgent import XianyuReplyBot
from xianyu_agent.xianyubot.XianyuApis import XianyuAPI
from xianyu_agent.xianyubot.context_manager import ChatContextManager
from xianyu_agent.xianyubot.utils.xianyu_utils import decrypt, generate_device_id, generate_mid, generate_uuid

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

WS_URL = "wss://wss-goofish.dingtalk.com/"
COOKIES = os.getenv("COOKIES_STR")
if not COOKIES:
    COOKIES = input("请输入COOKIES：")

api = XianyuAPI(COOKIES)
bot = XianyuReplyBot()
context_manager = ChatContextManager()

MY_USER_ID = ""

try:
    MY_USER_ID = api.cookies.get("unb","")
    if MY_USER_ID:
        logger.info(f"登录成功，当前用户ID{MY_USER_ID}")
    else:
        logger.warning(f"无法获取当前用户ID，可能会导致用户自己回复自己")
except:
    pass

DEVICE_ID = generate_device_id(MY_USER_ID)
CURRENT_TOKEN = None

import concurrent.futures
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

_processed_messages = {}
_message_lock = threading.Lock()

_DEDUP_EXPIRE = 60
_user_last_reply = {}
_REPLY_COOLDOWN = 3

async def get_token():
    "获取WebSocket连接所需的token"
    global CURRENT_TOKEN
    try:
        token_result = api.get_token(DEVICE_ID)
        if 'data' in token_result and "accessToken" in token_result['data']:
            CURRENT_TOKEN = token_result['data']['accessToken']
            logger.info("Token获取成功")
            return CURRENT_TOKEN
        else:
            logger.error(f"Token 获取失败:{token_result}")
            return None
    except Exception as e:
        logger.error(f"Token 获取异常{e}")
        return None

async def ws_init(ws):
    """WebSocket连接初始化：发送注册包"""
    global  CURRENT_TOKEN
    if not CURRENT_TOKEN:
        await get_token()

    if not CURRENT_TOKEN:
        raise Exception("无法获取有效Token")

    reg_msg = {
        "lwp":"/reg",
        "headers":{
            "cache-header":"app-key token ua wv",
            "app-key":"444e9908a51d1cb236a27862abc769c9",
            "token":CURRENT_TOKEN,
            "ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
            "dt":'j',
            "wv":"im:3,au:3,sy:6",
            "sync":"0,0;0,0;",
            "did":DEVICE_ID,
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


def _is_duplicate(msg_key: str) -> bool:
    """消息去重"""
    if not msg_key:
        return False
    now = time.time()
    with _message_lock:

        expired = [k for k, v in _processed_messages.items() if now - v > _DEDUP_EXPIRE]
        for k in expired:
            del _processed_messages[k]

        if msg_key in _processed_messages:
            return True
        _processed_messages[msg_key] = now
        return False
def _in_cooldown(user_id: str) -> bool:
    """同一用户防抖"""
    if not user_id:
        return False
    now = time.time()
    last = _user_last_reply.get(user_id, 0)
    if now - last < _REPLY_COOLDOWN:
        return True
    _user_last_reply[user_id] = now
    return False

async def handle_message(message_data, ws):
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
        if not (isinstance(message_data, dict)
                and "body" in message_data
                and "syncPushPackage" in message_data.get("body", {})
                and "data" in message_data["body"]["syncPushPackage"]
                and len(message_data["body"]["syncPushPackage"]["data"]) > 0):
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

            # 4.4 decrypt 解密
            if message is None:
                try:
                    decrypted_data = decrypt(raw_data)
                    message = json.loads(decrypted_data)
                    logger.info(f"[objectType={object_type}] decrypt解析成功")
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
            def get_val(d, key):
                if not isinstance(d, dict):
                    return None
                if key in d:
                    return d[key]
                str_key = str(key)
                if str_key in d:
                    return d[str_key]
                if isinstance(key, str) and key.isdigit():
                    int_key = int(key)
                    if int_key in d:
                        return d[int_key]
                if isinstance(key, int):
                    for k, v in d.items():
                        if isinstance(k, bytes):
                            try:
                                if int(k) == key:
                                    return v
                            except:
                                pass
                        if str(k) == str(key):
                            return v
                return None

            def deep_get(d, *keys):
                """递归取值"""
                current = d
                for key in keys:
                    current = get_val(current, key)
                    if current is None:
                        return None
                return current

            # 初始化提取变量
            send_user_id = None
            send_message = None
            send_user_name = None
            url_info = None
            chat_id = None
            image_url = None
            is_image_message = False

            def bytes_to_str(val):
                if isinstance(val, bytes):
                    return val.decode('utf-8', errors='replace')
                return str(val) if val else ""

            # ========== 路径1: message[1][10] 格式（通知型推送） ==========
            meta = deep_get(message, 1, 10)
            if isinstance(meta, dict):
                send_user_id = bytes_to_str(
                    meta.get("senderUserId") or meta.get(b"senderUserId") or "")
                send_message = bytes_to_str(
                    meta.get("reminderContent") or meta.get(b"reminderContent") or "")
                send_user_name = bytes_to_str(
                    meta.get("reminderTitle") or meta.get(b"reminderTitle") or "")
                url_info = bytes_to_str(
                    meta.get("reminderUrl") or meta.get(b"reminderUrl") or "")

            inner = get_val(message, 1)
            if isinstance(inner, dict) and not chat_id:
                chat_source = get_val(inner, 2)
                if chat_source:
                    chat_id = bytes_to_str(chat_source).split('@')[0]

            # ========== 路径2: message[1][5] 格式（消息体） ==========
            content_data = deep_get(message, 1, 5)
            if isinstance(content_data, dict):
                # 2a. 从 extJson 中提取
                ext_json_raw = content_data.get("extJson") or content_data.get(b"extJson")
                if ext_json_raw:
                    try:
                        ext = json.loads(bytes_to_str(ext_json_raw))
                        logger.debug(f"📦 extJson 内容: {json.dumps(ext, ensure_ascii=False)[:500]}")

                        # 提取文本
                        text_obj = ext.get("text", {})
                        if isinstance(text_obj, dict):
                            extracted_text = text_obj.get("text", "")
                            if extracted_text and not send_message:
                                send_message = extracted_text


                        # 结构1: ext.image.picUrl
                        image_obj = ext.get("image", {})
                        if isinstance(image_obj, dict):
                            pic_url = (image_obj.get("picUrl")
                                       or image_obj.get("url")
                                       or image_obj.get("imgUrl")
                                       or image_obj.get("originUrl")
                                       or image_obj.get("thumbUrl"))
                            if pic_url and str(pic_url).startswith("http"):
                                image_url = str(pic_url)
                                is_image_message = True
                                logger.info(f"📷 从extJson.image提取到图片: {image_url[:100]}")

                        # 结构2: ext.customBody 中包含图片
                        custom_body = ext.get("customBody", "")
                        if isinstance(custom_body, str) and custom_body.startswith("{"):
                            try:
                                cb = json.loads(custom_body)
                                cb_img = (cb.get("picUrl") or cb.get("imageUrl")
                                          or cb.get("url") or cb.get("imgUrl"))
                                if cb_img and str(cb_img).startswith("http") and not image_url:
                                    image_url = str(cb_img)
                                    is_image_message = True
                                    logger.info(f"📷 从extJson.customBody提取到图片: {image_url[:100]}")
                            except:
                                pass

                        # 结构3: ext 顶层直接有图片字段
                        if not image_url:
                            for img_key in ["picUrl", "imageUrl", "imgUrl", "url",
                                            "originUrl", "thumbUrl", "pic_url", "image_url"]:
                                val = ext.get(img_key, "")
                                if isinstance(val, str) and val.startswith("http"):
                                    lower_val = val.lower()
                                    if any(kw in lower_val for kw in
                                           [".jpg", ".jpeg", ".png", ".gif", ".webp",
                                            "alicdn", "img.", "oss", "goofish"]):
                                        image_url = val
                                        is_image_message = True
                                        logger.info(f"📷 从extJson顶层提取到图片: {image_url[:100]}")
                                        break
                    except Exception as e:
                        logger.debug(f"extJson解析失败: {e}")

                # 2b. 直接从 content_data 取文本
                if not send_message:
                    text_val = content_data.get("text") or content_data.get(b"text")
                    if text_val:
                        send_message = bytes_to_str(text_val)

                # 2c. 检查 contentType 判断是否是图片消息
                ct = content_data.get("contentType") or content_data.get(b"contentType")
                if ct:
                    ct_val = int(ct) if isinstance(ct, (int, str, bytes)) and str(ct).isdigit() else 0

                    if ct_val in [2, 5]:
                        is_image_message = True
                        logger.info(f"📷 contentType={ct_val}，判定为图片消息")

                # 2d. 从 content_data.custom.data (base64) 中提取
                custom_field = content_data.get("custom") or content_data.get(b"custom")
                if custom_field:
                    custom_dict = custom_field
                    if isinstance(custom_field, (str, bytes)):
                        try:
                            custom_dict = json.loads(bytes_to_str(custom_field))
                        except:
                            custom_dict = None

                    if isinstance(custom_dict, dict):
                        custom_data_b64 = custom_dict.get("data") or custom_dict.get(b"data")
                        custom_type = custom_dict.get("type") or custom_dict.get(b"type")
                        if custom_data_b64:
                            try:
                                decoded_custom = base64.b64decode(bytes_to_str(custom_data_b64))
                                decoded_json = json.loads(decoded_custom.decode('utf-8'))
                                logger.debug(
                                    f"📦 custom.data 解码: {json.dumps(decoded_json, ensure_ascii=False)[:500]}")

                                # 提取文本
                                if not send_message:
                                    txt = decoded_json.get("text", {})
                                    if isinstance(txt, dict):
                                        send_message = txt.get("text", "")
                                    elif isinstance(txt, str):
                                        send_message = txt

                                # 提取图片
                                if not image_url:
                                    img_data = decoded_json.get("image", {})
                                    if isinstance(img_data, dict):
                                        pic = (img_data.get("picUrl")
                                               or img_data.get("url")
                                               or img_data.get("imgUrl")
                                               or img_data.get("originUrl"))
                                        if pic and str(pic).startswith("http"):
                                            image_url = str(pic)
                                            is_image_message = True
                                            logger.info(
                                                f"📷 从custom.data.image提取到图片: {image_url[:100]}")


                                    if decoded_json.get("contenttype") == 2 and not image_url:
                                        is_image_message = True
                                    # 递归搜索图片URL
                                    if not image_url:
                                        def find_img_in_dict(d, depth=0):
                                            if depth > 6 or not isinstance(d, dict):
                                                return None
                                            for k, v in d.items():
                                                k_str = bytes_to_str(k) if isinstance(k, bytes) else str(k)
                                                if isinstance(v, str) and v.startswith("http"):
                                                    lower_v = v.lower()
                                                    if any(kw in lower_v for kw in
                                                           [".jpg", ".jpeg", ".png", ".gif", ".webp",
                                                            "alicdn", "img.", "oss", "goofish"]):
                                                        return v
                                                elif isinstance(v, dict):
                                                    result = find_img_in_dict(v, depth + 1)
                                                    if result:
                                                        return result
                                                elif isinstance(v, list):
                                                    for item in v:
                                                        if isinstance(item, dict):
                                                            result = find_img_in_dict(item, depth + 1)
                                                            if result:
                                                                return result
                                            return None

                                        found_img = find_img_in_dict(decoded_json)
                                        if found_img:
                                            image_url = found_img
                                            is_image_message = True
                                            logger.info(
                                                f"📷 从custom.data递归搜索到图片: {image_url[:100]}")

                            except Exception as e:
                                logger.debug(f"custom.data base64解码失败: {e}")

            # ========== 路径3: 遍历整个message找关键字段 ==========
            if not send_message or not send_user_id:
                def find_in_dict(d, target_keys, depth=0):
                    if depth > 5 or not isinstance(d, dict):
                        return {}
                    result = {}
                    for k, v in d.items():
                        k_str = bytes_to_str(k) if isinstance(k, bytes) else str(k)
                        if k_str in target_keys:
                            result[k_str] = bytes_to_str(v) if isinstance(v, (str, bytes)) else v
                        if isinstance(v, dict):
                            result.update(find_in_dict(v, target_keys, depth + 1))
                        elif isinstance(v, list):
                            for item in v:
                                if isinstance(item, dict):
                                    result.update(find_in_dict(item, target_keys, depth + 1))
                    return result

                found = find_in_dict(message, {
                    "reminderContent", "senderUserId", "reminderTitle",
                    "reminderUrl", "text", "content", "senderNick",
                    "url", "picUrl", "imageUrl", "imgUrl", "originUrl", "thumbUrl"
                })

                if found:
                    logger.debug(f"遍历找到的字段: {found}")
                    send_message = send_message or found.get("reminderContent") or found.get("text") or found.get(
                        "content")
                    send_user_id = send_user_id or found.get("senderUserId")
                    send_user_name = send_user_name or found.get("reminderTitle") or found.get("senderNick")
                    url_info = url_info or found.get("reminderUrl")

                    # 尝试获取图片URL
                    if not image_url:
                        for img_key in ["picUrl", "imageUrl", "imgUrl", "originUrl", "thumbUrl"]:
                            extracted_img = found.get(img_key)
                            if extracted_img and isinstance(extracted_img, str) and extracted_img.startswith("http"):
                                image_url = extracted_img
                                is_image_message = True
                                logger.info(f"📷 从遍历字段[{img_key}]提取到图片: {image_url[:100]}")
                                break


                        if not image_url:
                            url_val = found.get("url", "")
                            if isinstance(url_val, str) and url_val.startswith("http"):
                                lower_url = url_val.lower()
                                if any(kw in lower_url for kw in
                                       [".jpg", ".jpeg", ".png", ".gif", ".webp",
                                        "alicdn", "img.", "oss"]):
                                    image_url = url_val
                                    is_image_message = True
                                    logger.info(f"📷 从遍历字段[url]提取到图片: {image_url[:100]}")

            # ========== 路径4: 递归搜索整个message中的图片URL ==========
            if not image_url:
                def extract_image_from_message(msg_dict, depth=0):
                    """递归搜索消息结构中的图片URL"""
                    if depth > 8:
                        return None
                    if isinstance(msg_dict, dict):
                        for k, v in msg_dict.items():
                            k_str = bytes_to_str(k) if isinstance(k, bytes) else str(k)
                            # 优先检查图片相关的key
                            if k_str.lower() in ["picurl", "imageurl", "imgurl", "originurl",
                                                 "thumburl", "pic_url", "image_url", "img_url"]:
                                v_str = bytes_to_str(v) if isinstance(v, (bytes, str)) else ""
                                if isinstance(v_str, str) and v_str.startswith("http"):
                                    return v_str

                            # 检查值是否是图片URL
                            if isinstance(v, (str, bytes)):
                                v_str = bytes_to_str(v) if isinstance(v, bytes) else v
                                if v_str.startswith("http"):
                                    lower_v = v_str.lower()
                                    if any(ext in lower_v for ext in
                                           ['.jpg', '.jpeg', '.png', '.gif', '.webp',
                                            'alicdn.com', 'img.alicdn', 'oss']):
                                        return v_str

                            # 检查值是否是JSON字符串
                            if isinstance(v, (str, bytes)):
                                v_str = bytes_to_str(v) if isinstance(v, bytes) else v
                                if v_str.startswith('{'):
                                    try:
                                        inner = json.loads(v_str)
                                        result = extract_image_from_message(inner, depth + 1)
                                        if result:
                                            return result
                                    except:
                                        pass

                            # 递归搜索
                            if isinstance(v, dict):
                                result = extract_image_from_message(v, depth + 1)
                                if result:
                                    return result
                            elif isinstance(v, list):
                                for item in v:
                                    if isinstance(item, (dict, str, bytes)):
                                        result = extract_image_from_message(
                                            item if isinstance(item, dict) else {}, depth + 1)
                                        if result:
                                            return result
                    return None

                found_image = extract_image_from_message(message)
                if found_image:
                    image_url = found_image
                    is_image_message = True
                    logger.info(f"📷 递归搜索提取到图片: {image_url[:100]}")

            # ========== 路径5: 从提取的字符串中找图片 ==========
            if not image_url and isinstance(message, dict) and "_extracted_strings" in message:
                strings = message["_extracted_strings"]
                for s in strings:
                    if s.startswith("http") and any(
                            kw in s.lower() for kw in [".jpg", ".png", ".jpeg", ".webp",
                                                       "alicdn", "oss", "img."]):
                        image_url = s
                        is_image_message = True
                        logger.info(f"📷 从二进制字符串提取到图片: {image_url[:100]}")
                        break

            # ========== 检测 reminderContent 中的图片标记 ==========
            if send_message and not image_url:
                msg_lower = send_message.strip().lower() if send_message else ""

                image_indicators = ["[图片]", "[图片消息]", "[image]", "发来一张图片",
                                    "发送了一张图片", "图片消息"]
                for indicator in image_indicators:
                    if indicator in msg_lower or indicator in send_message:
                        is_image_message = True
                        logger.info(f"📷 检测到图片标记: '{send_message}'")
                        break


            if is_image_message and not image_url and chat_id:
                logger.info(f"📷 确认为图片消息但WS推送中无图片URL，正在通过API拉取聊天记录...")
                try:
                    fetched_url = api.extract_latest_image_url(chat_id)
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

            if send_user_id and send_user_id == MY_USER_ID:
                logger.debug("是自己发送的消息，跳过")
                continue
            dedup_key = f"{chat_id}:{send_user_id}:{send_message}"
            if _is_duplicate(dedup_key):
                logger.debug(f"⏭️ 重复消息，跳过: {dedup_key[:80]}")
                continue

            cooldown_key = f"{chat_id}:{send_user_id}"
            if _in_cooldown(cooldown_key):
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
                item_id = context_manager.get_latest_item_id_by_chat(chat_id)

            logger.info(
                f"✅ 收到消息 - 用户: {send_user_name} (ID: {send_user_id}), "
                f"商品: {item_id}, 会话: {chat_id}, "
                f"消息: {send_message}, 图片: {image_url if image_url else '无'}")


            loop = asyncio.get_event_loop()
            item_desc = "未获取到具体商品信息，请根据常识和聊天上下文进行回复。"
            if item_id and item_id != "0":
                item_data = context_manager.get_item_info(item_id)

                if not item_data:
                    logger.info(f"本地无商品 {item_id} 缓存，正在请求API...")
                    api_res = await loop.run_in_executor(
                        _executor, lambda: api.get_item_info(item_id)
                    )

                    if api_res and "data" in api_res:
                        raw_data = api_res.get("data", {})
                        item_data = {
                            "title": raw_data.get("item", {}).get("title", "未知商品"),
                            "soldPrice": raw_data.get("item", {}).get("price", "0"),
                            "desc": raw_data.get("item", {}).get("desc", "无详细描述"),
                        }
                        context_manager.save_item_info(item_id, item_data)

                if item_data:
                    title = item_data.get("title", "未知")
                    price = item_data.get("soldPrice", "未知")
                    desc = item_data.get("desc", "无")
                    item_desc = f"商品名称：{title}\n标价：{price}元\n商品详细描述：{desc}"

            # 8. 生成回复
            image_desc_for_memory = None
            if image_url:
                try:
                    _img_url = image_url
                    _img_ctx = f"用户正在咨询商品，商品信息: {item_desc[:100]}"
                    image_desc_for_memory = await loop.run_in_executor(
                                _executor,
                                lambda: context_manager.generate_image_description(_img_url, context=_img_ctx)
                            )
                    logger.info(f"📷 图片描述（存入长期记忆）: {image_desc_for_memory[:80]}...")
                except Exception as e:
                    logger.warning(f"图片描述生成失败: {e}")
            _chat_id = chat_id
            _send_msg = send_message or ""
            history = await loop.run_in_executor(
                        _executor,
                        lambda: context_manager.get_enriched_context(
                            chat_id=_chat_id,
                            current_message=_send_msg,
                            use_long_term=True
                        )
                    )
            _item_desc = item_desc
            _history = history
            _image_url = image_url
            reply = await loop.run_in_executor(
                        _executor,
                        lambda: bot.generate_reply(_send_msg, _item_desc, _history, img_url=_image_url)
                    )
            logger.info(f"准备回复: {reply}")

            # 9. 发送回复
            logger.info(f">>> 正在发送消息到 chat_id={chat_id}, user_id={send_user_id}")
            await send_ws_msg(ws, chat_id, send_user_id, reply)
            logger.info(">>> ✅ 消息发送成功")


            safe_send_message = send_message if send_message else "[发送了一张图片]"
            current_item_info = None
            if item_id and item_id != "0":
                current_item_info = context_manager.get_item_info(item_id)

            _save_args = {
                "chat_id": chat_id, "send_user_id": send_user_id,
                "item_id": item_id, "safe_send_message": safe_send_message,
                "image_url": image_url, "image_desc": image_desc_for_memory,
                "current_item_info": current_item_info,
                "my_user_id": MY_USER_ID, "reply": reply,
                "last_intent": bot.last_intent,
            }

            def _save_context(args):
                try:
                    context_manager.add_message_by_chat(
                        chat_id=args["chat_id"], user_id=args["send_user_id"],
                        item_id=args["item_id"], role='user',
                        content=args["safe_send_message"],
                        image_url=args["image_url"], image_desc=args["image_desc"],
                        item_info=args["current_item_info"]
                    )
                    context_manager.add_message_by_chat(
                        chat_id=args["chat_id"], user_id=args["my_user_id"],
                        item_id=args["item_id"], role='assistant',
                        content=args["reply"], item_info=args["current_item_info"]
                    )
                    if args["last_intent"] == "price":
                        context_manager.increment_bargain_count_by_chat(args["chat_id"])
                except Exception as e:
                    logger.error(f"保存上下文失败: {e}")

            loop.run_in_executor(_executor, _save_context, _save_args)

            replied = True
            logger.debug("✅ 已回复，跳过本批次剩余 sync_data")
            break


    except Exception as e:
        logger.error(f"处理消息出错: {e}")
        import traceback
        traceback.print_exc()


def extract_strings_from_binary(data: bytes, min_length=4) -> list:
    """从二进制数据中提取所有可读UTF-8字符串"""
    strings = []
    current = b""
    for byte in data:
        if 32 <= byte < 127 or byte >= 0xC0:
            current += bytes([byte])
        else:
            if len(current) >= min_length:
                try:
                    s = current.decode("utf-8", errors="ignore")
                    if s.strip():
                        strings.append(s)
                except:
                    pass
            current = b""
    if len(current) >= min_length:
        try:
            s = current.decode("utf-8", errors="ignore")
            if s.strip():
                strings.append(s)
        except:
            pass
    return strings


def parse_dingtalk_binary(data: bytes) -> dict:
    """尝试手动解析钉钉二进制消息格式"""
    try:
        import msgpack
        # 尝试不同的 msgpack 解析参数
        for kwargs in [
            {"raw": False, "strict_map_key": False},
            {"raw": True, "strict_map_key": False},
            {"raw": False},
            {"raw": True},
            {},
        ]:
            try:
                result = msgpack.unpackb(data, **kwargs)
                return result
            except:
                continue
    except ImportError:
        pass

    # 如果 msgpack 都失败了，尝试手动提取
    strings = extract_strings_from_binary(data)
    if strings:
        return {"_manual_parse": True, "_strings": strings}
    return None



async def send_ws_msg(ws,cid,toid,text):
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
                    f"{MY_USER_ID}@goofish"
                ]
            }]

    }
    await ws.send(json.dumps(msg))

def is_sync_package(message_data):
    try:
        return(
            isinstance(message_data,dict)
            and "body" in message_data
            and "syncPushPackage" in message_data.get("body",{})
            and "data" in message_data["body"]["syncPushPackage"]
            and len(message_data["body"]["syncPushPackage"]["data"]) > 0
        )
    except Exception:
        return False

def is_chat_message(message):
    try:
        return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], dict)
                and "10" in message["1"]
                and isinstance(message["1"]["10"], dict)
                and "reminderContent" in message["1"]["10"]
        )
    except Exception:
        return False

async def send_heartbeat(ws):
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
async def heartbeat_loop(ws):
    """心跳维护循环，每15秒发送一次"""
    while True:
        try:
            await asyncio.sleep(30)
            await send_heartbeat(ws)
        except Exception as e:
            logger.error(f"心跳循环出错: {e}")
            break

async def main():
    """主函数，包含自动重连逻辑"""
    logger.info('闲鱼客服正在启动...')
    while True:
        heartbeat_task = None
        try:
            # ✅ 完整的请求头，模拟浏览器行为
            headers = {
                "Cookie": COOKIES,
                "Host": "wss-goofish.dingtalk.com",
                "Connection": "Upgrade",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Origin": "https://www.goofish.com",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            async with websockets.connect(WS_URL, additional_headers=headers) as ws:
                logger.success("已成功连接到闲鱼WebSocket服务器")

                await ws_init(ws)

                heartbeat_task = asyncio.create_task(heartbeat_loop(ws))

                async for message in ws:
                    try:
                        message_data = json.loads(message)

                        if (isinstance(message_data, dict)
                                and "code" in message_data
                                and message_data["code"] == 200
                                and "lwp" not in message_data):
                            logger.debug("收到心跳/ACK响应")
                            continue

                        await handle_message(message_data, ws)
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
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('程序已停止')
    except Exception as e:
        logger.error(f"运行报错: {e}")
