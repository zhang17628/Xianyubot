import os
import sys

import requests
import time
import json
import base64
from loguru import logger
from utils.xianyu_utils import generate_mid, generate_device_id, generate_sign,trans_cookies

class XianyuAPI:
    def __init__(self,cookies_str:str):
        self.header = {
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type":"application/x-www-form-urlencoded",
            "Referer": "https://market.m.taobao.com/app/idleFish-F2e/widle-taobao-rax/favor-detail",
            "Origin": "https://market.m.taobao.com"
        }
        self.cookies = trans_cookies(cookies_str)
        self.cookies_str = cookies_str

        self.token = self.cookies.get("_m_h5_tk","").split("_")[0]
        self.cna = self.cookies.get("cna","")
        self.isg = self.cookies.get("isg",'')
        self.session = requests.Session()
        self.session.headers.update(self.header)
        self.session.cookies.update(self.cookies)

        if not self.token:
            logger.warning("警告：Cookie未找到_m_h5_tk,可能无法工作")

    def _get_common_params(self, data_dict: dict, api_name: str = "mtop.taobao.idle.message.chat.send"):
        """构造通用参数+签名"""
        t = str(int(time.time() * 1000))
        data_str = json.dumps(data_dict, separators=(",", ":"))
        sign = generate_sign(t, self.token, data_str)
        return {
            "jsv": "2.7.2",
            "appKey": "34839810",
            "t": t,
            "sign": sign,
            "api": api_name,
            "v": "1.0",
            "type": "originaljson",
            "dataType": "json",
            "data": data_str
        }

    def send_text_msg(self,user_id:str,content:str,item_id:str):
        """发送文本信息"""
        api_name = "mtop.taobao.idle.message.chat.send"
        msg_data = {
            "chatId": "", # 如果是新会话，这里可以为空，也可以不传
            "receiverId": user_id,
            "sessionId": "",
            "templateData": json.dumps({"text": content}),
            "templateId": "1", # 1 代表纯文本消息
            "contentType": "1",
            "context": json.dumps({
                "userId": user_id,
                "itemId": item_id
            })
        }

        params = self._get_common_params(msg_data)
        params["api"] = api_name
        url = "https://h5api.m.taobao.com/h5/mtop.taobao.idle.message.chat.send/1.0/"
        try:
            logger.info(f"正在发送给{user_id}:{content[:10]}")
            resp = requests.post(
                url,
                headers=self.header,
                cookies=self.cookies,
                params=params,
                timeout=10
            )
            result = resp.json()
            if result.get("ret",[""])[0].startswith("SUCCESS"):
                logger.success(f"发送成功")
                return True
            else:
                logger.error(f"发送失败{result}")
                return False

        except Exception as e:
            logger.error(f"网络请求异常:{e}")
            return False

    def get_user_info(self):
        """获取当前登录用户的信息，验证Cookies是否有效"""
        api_name = "mtop.taobao.idle.user.baseinfo.get"
        data = {}
        params = self._get_common_params(data)
        params["api"] = api_name
        url = "https://h5api.m.taobao.com/h5/mtop.taobao.idle.user.baseinfo.get/1.0/"
        try:
            resp = requests.get(url,headers=self.header,cookies=self.cookies,params=params)
            logger.debug(f"🔍 API 响应内容: { resp.json()}")
            return resp.json()
        except:
            return None

    def clear_duplicate_cookies(self):
        """清理重复的cookies"""
        # 创建一个新的CookieJar
        new_jar = requests.cookies.RequestsCookieJar()


        added_cookies = set()

        cookie_list = list(self.session.cookies)
        cookie_list.reverse()

        for cookie in cookie_list:
            if cookie.name not in added_cookies:
                new_jar.set_cookie(cookie)
                added_cookies.add(cookie.name)

        self.session.cookies = new_jar

        self.update_env_cookies()

    def update_env_cookies(self):
        """更新.env文件中的COOKIES_STR"""
        try:
            cookie_str = '; '.join([f"{cookie.name}={cookie.value}" for cookie in self.session.cookies])

            env_path = os.path.join(os.getcwd(), '.env')
            if not os.path.exists(env_path):
                logger.warning(".env文件不存在，无法更新COOKIES_STR")
                return

            with open(env_path, 'r', encoding='utf-8') as f:
                env_content = f.read()

            if 'COOKIES_STR=' in env_content:
                new_env_content = re.sub(
                    r'COOKIES_STR=.*',
                    f'COOKIES_STR={cookie_str}',
                    env_content
                )


                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write(new_env_content)

                logger.debug("已更新.env文件中的COOKIES_STR")
            else:
                logger.warning(".env文件中未找到COOKIES_STR配置项")
        except Exception as e:
            logger.warning(f"更新.env文件失败: {str(e)}")
    def hasLogin(self, retry_count=0):
        """调用hasLogin.do接口进行登录状态检查"""
        if retry_count >= 2:
            logger.error("Login检查失败，重试次数过多")
            return False

        try:
            url = 'https://passport.goofish.com/newlogin/hasLogin.do'
            params = {
                'appName': 'xianyu',
                'fromSite': '77'
            }
            data = {
                'hid': self.session.cookies.get('unb', ''),
                'ltl': 'true',
                'appName': 'xianyu',
                'appEntrance': 'web',
                '_csrf_token': self.session.cookies.get('XSRF-TOKEN', ''),
                'umidToken': '',
                'hsiz': self.session.cookies.get('cookie2', ''),
                'bizParams': 'taobaoBizLoginFrom=web',
                'mainPage': 'false',
                'isMobile': 'false',
                'lang': 'zh_CN',
                'returnUrl': '',
                'fromSite': '77',
                'isIframe': 'true',
                'documentReferer': 'https://www.goofish.com/',
                'defaultView': 'hasLogin',
                'umidTag': 'SERVER',
                'deviceId': self.session.cookies.get('cna', '')
            }

            response = self.session.post(url, params=params, data=data)
            res_json = response.json()

            if res_json.get('content', {}).get('success'):
                logger.debug("Login成功")
                # 清理和更新cookies
                self.clear_duplicate_cookies()
                return True
            else:
                logger.warning(f"Login失败: {res_json}")
                time.sleep(0.5)
                return self.hasLogin(retry_count + 1)

        except Exception as e:
            logger.error(f"Login请求异常: {str(e)}")
            time.sleep(0.5)
            return self.hasLogin(retry_count + 1)
    def get_token(self, device_id, retry_count=3):
        if retry_count >= 2:
            logger.warning("获取token失败，尝试重新登陆")
            if self.hasLogin():
                logger.info("重新登录成功，重新尝试获取token")
                return self.get_token(device_id, 0)
            else:
                logger.error("重新登录失败，Cookie已失效")
                logger.error("🔴 程序即将退出，请更新.env文件中的COOKIES_STR后重新启动")
                sys.exit(1)

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time()) * 1000),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idlemessage.pc.login.token',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }

        data_val = '{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"' + device_id + '"}'
        data = {'data': data_val}

        token = self.session.cookies.get('_m_h5_tk', '').split('_')[0]
        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign

        try:
            logger.info("正在获取WebSocket Token...")

            response = self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/',
                params=params,
                data=data
            )
            res_json = response.json()

            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                if not any('SUCCESS::调用成功' in ret for ret in ret_value):
                    error_msg = str(ret_value)
                    if 'RGV587_ERROR' in error_msg or '被挤爆啦' in error_msg:
                        logger.error(f"❌ 触发风控: {ret_value}")
                        logger.error("🔴 请进入闲鱼网页版-点击消息-过滑块-复制最新的Cookie")
                        print("\n" + "=" * 50)
                        new_cookie_str = input("请输入新的Cookie字符串 (直接回车退出): ").strip()
                        print("=" * 50 + "\n")
                        if new_cookie_str:
                            try:
                                from http.cookies import SimpleCookie
                                cookie = SimpleCookie()
                                cookie.load(new_cookie_str)
                                self.session.cookies.clear()
                                for key, morsel in cookie.items():
                                    self.session.cookies.set(key, morsel.value, domain='.goofish.com')
                                logger.success("✅ Cookie已更新，正在尝试重连...")
                                self.update_env_cookies()
                                return self.get_token(device_id, 0)
                            except Exception as e:
                                logger.error(f"Cookie解析失败: {e}")
                                sys.exit(1)
                        else:
                            sys.exit(1)

                    logger.warning(f"Token API调用失败: {ret_value}")
                    if 'Set-Cookie' in response.headers:
                        logger.debug("检测到Set-Cookie，更新cookie")
                        self.clear_duplicate_cookies()
                    time.sleep(0.5)
                    return self.get_token(device_id, retry_count + 1)
                else:
                    logger.info("✅ Token获取成功")
                    return res_json
            else:
                logger.error(f"Token API返回格式异常: {res_json}")
                return self.get_token(device_id, retry_count + 1)

        except Exception as e:
            logger.error(f"Token API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_token(device_id, retry_count + 1)



    def get_item_info(self, item_id: str):
        """
        获取商品详细信息
        """
        api_name = "mtop.taobao.idle.pc.detail"
        data = {
            "itemId": item_id
        }
        params = self._get_common_params(data, api_name)
        url = f"https://h5api.m.taobao.com/h5/{api_name}/1.0/"
        try:
            logger.info(f"正在获取商品信息: {item_id}")
            resp = self.session.get(
                url,
                params=params,
                timeout=10
            )
            result = resp.json()
            logger.debug(f"商品API响应: {json.dumps(result, ensure_ascii=False)[:200]}...")
            ret = result.get("ret", [""])
            if isinstance(ret, list) and len(ret) > 0:
                ret_code = ret[0]
                if "SUCCESS" in ret_code:
                    logger.info(f"商品 {item_id} 信息获取成功")
                    return result
                else:
                    logger.error(f"获取商品信息失败，返回码: {ret_code}")
            return result
        except Exception as e:
            logger.error(f"获取商品信息网络请求异常: {e}")
            return {}

    # 在 XianyuAPI 类中添加以下方法

    def get_chat_messages(self, chat_id: str, page_size: int = 10):
        """
        获取指定会话的聊天记录（包含图片URL）
        chat_id: 会话ID（不带@goofish后缀）
        """
        api_name = "mtop.taobao.idle.im.message.query"
        data = {
            "conversationId": f"{chat_id}@goofish",
            "pageSize": str(page_size),
            "order": "desc"  # 最新的消息在前
        }
        params = self._get_common_params(data, api_name)
        url = f"https://h5api.m.goofish.com/h5/{api_name}/1.0/"

        try:
            logger.info(f"正在获取会话 {chat_id} 的聊天记录...")
            resp = self.session.get(url, params=params, timeout=10)
            result = resp.json()

            ret = result.get("ret", [""])
            if isinstance(ret, list) and any("SUCCESS" in r for r in ret):
                logger.info(f"聊天记录获取成功")
                return result
            else:
                logger.warning(f"聊天记录获取失败: {ret}")
                # 尝试备用API
                return self._get_chat_messages_v2(chat_id, page_size)
        except Exception as e:
            logger.error(f"获取聊天记录异常: {e}")
            return None

    def _get_chat_messages_v2(self, chat_id: str, page_size: int = 10):
        """备用聊天记录API"""
        api_name = "mtop.taobao.idlemessage.pc.chat.message.list"
        data = {
            "cid": f"{chat_id}@goofish",
            "pageSize": str(page_size),
            "msgId": "",
            "direction": "before"
        }
        params = self._get_common_params(data, api_name)
        url = f"https://h5api.m.goofish.com/h5/{api_name}/1.0/"

        try:
            resp = self.session.get(url, params=params, timeout=10)
            result = resp.json()
            logger.debug(f"备用聊天记录API响应: {json.dumps(result, ensure_ascii=False)[:500]}")
            return result
        except Exception as e:
            logger.error(f"备用聊天记录API异常: {e}")
            return None

    def extract_latest_image_url(self, chat_id: str) -> str:
        """
        从最近的聊天记录中提取最新的图片URL
        """
        result = self.get_chat_messages(chat_id, page_size=5)
        if not result:
            return None

        try:

            messages = None
            data = result.get("data", {})


            if isinstance(data, dict):
                messages = data.get("messages") or data.get("msgList") or data.get("data", {}).get("messages")


            if not messages:
                result_value = data.get("resultValue", {})
                if isinstance(result_value, dict):
                    messages = result_value.get("messages") or result_value.get("msgList")

            if not messages or not isinstance(messages, list):
                logger.warning(f"未找到消息列表，返回结构: {json.dumps(data, ensure_ascii=False)[:300]}")
                return None


            for msg in messages:
                if not isinstance(msg, dict):
                    continue

                content = msg.get("content", {})
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except:
                        continue

                if not isinstance(content, dict):
                    continue


                content_type = content.get("contentType") or content.get("type") or msg.get("contentType")

                # 直接搜索图片URL
                img_url = self._find_image_in_content(content)
                if img_url:
                    return img_url

                # 检查 custom 字段（闲鱼自定义消息格式）
                custom = content.get("custom", {})
                if isinstance(custom, str):
                    try:
                        custom = json.loads(custom)
                    except:
                        pass
                if isinstance(custom, dict):
                    custom_data = custom.get("data", "")
                    if custom_data:
                        try:
                            decoded = base64.b64decode(custom_data)
                            decoded_json = json.loads(decoded)
                            img_url = self._find_image_in_content(decoded_json)
                            if img_url:
                                return img_url
                        except:
                            pass

            return None
        except Exception as e:
            logger.error(f"提取图片URL异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _find_image_in_content(self, content: dict) -> str:
        """递归在消息内容中查找图片URL"""
        if not isinstance(content, dict):
            return None

        # 常见的图片字段名
        image_keys = [
            "picUrl", "imageUrl", "url", "imgUrl", "img_url",
            "pic_url", "image_url", "thumbUrl", "originUrl",
            "mediaUrl", "src", "imgSrc"
        ]

        for key in image_keys:
            val = content.get(key, "")
            if isinstance(val, str) and val.startswith("http"):
                # 过滤明显不是图片的URL
                if any(domain in val for domain in ["alicdn", "taobao", "goofish", "oss", "img"]):
                    return val
                if any(ext in val.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
                    return val

        # 递归搜索嵌套结构
        for k, v in content.items():
            if isinstance(v, dict):
                result = self._find_image_in_content(v)
                if result:
                    return result
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        result = self._find_image_in_content(item)
                        if result:
                            return result
            elif isinstance(v, str) and v.startswith("{"):
                try:
                    parsed = json.loads(v)
                    result = self._find_image_in_content(parsed)
                    if result:
                        return result
                except:
                    pass

        return None
