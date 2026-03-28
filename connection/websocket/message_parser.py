import base64
import json
from loguru import logger


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


def parse_message_data(message_data: dict):
    """
    解析 WebSocket 消息数据
    返回: (send_user_id, send_message, send_user_name, url_info, chat_id, image_url, is_image_message)
    """
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

    # ========== 路径1: message[1][10] 格式（通知型推送） ==========
    meta = deep_get(message_data, 1, 10)
    if isinstance(meta, dict):
        send_user_id = bytes_to_str(
            meta.get("senderUserId") or meta.get(b"senderUserId") or "")
        send_message = bytes_to_str(
            meta.get("reminderContent") or meta.get(b"reminderContent") or "")
        send_user_name = bytes_to_str(
            meta.get("reminderTitle") or meta.get(b"reminderTitle") or "")
        url_info = bytes_to_str(
            meta.get("reminderUrl") or meta.get(b"reminderUrl") or "")

    inner = get_val(message_data, 1)
    if isinstance(inner, dict) and not chat_id:
        chat_source = get_val(inner, 2)
        if chat_source:
            chat_id = bytes_to_str(chat_source).split('@')[0]

    # ========== 路径2: message[1][5] 格式（消息体） ==========
    content_data = deep_get(message_data, 1, 5)
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

        found = find_in_dict(message_data, {
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

        found_image = extract_image_from_message(message_data)
        if found_image:
            image_url = found_image
            is_image_message = True
            logger.info(f"📷 递归搜索提取到图片: {image_url[:100]}")

    # ========== 路径5: 从提取的字符串中找图片 ==========
    if not image_url and isinstance(message_data, dict) and "_extracted_strings" in message_data:
        strings = message_data["_extracted_strings"]
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

    return send_user_id, send_message, send_user_name, url_info, chat_id, image_url, is_image_message


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
