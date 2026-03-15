import os

from dotenv import find_dotenv, load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI
from loguru import logger

from xianyu_agent.xianyubot.utils.xianyu_utils import download_image_as_base64

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

class XianyuReplyBot:
    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.base_url = OPENAI_BASE_URL
        self.modle_name = 'gpt-4o-mini'
        if not self.api_key:
            raise ValueError("未找到 API_KEY,请检查.env文件")
        self.client = ChatOpenAI(model =self.modle_name,api_key = self.api_key,base_url = self.base_url)

        self.prompts = {
            "classify":self._load_prompt("classify_prompt.txt"),
            "default":self._load_prompt("default_prompt.txt"),
            "price":self._load_prompt("price_prompt.txt")
        }

        self.last_intent = "default"
    def _load_prompt(self,filename):
        """读取对应的prompt文件"""
        try:
            clean_filename = filename.strip()
            path = os.path.join(r"prompts",clean_filename)
            # print(path)
            if not os.path.exists(path):
                logger.warning("提示词文件不存在，将使用空提示词")
                return ""
            with open(path,"r",encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"读取提示词失败{filename}:{e}")
            return ""

    def detect_intent(self,text):
        """分析用户意图是什么"""
        try:
            messages = [
                {"role": "system", "content": self.prompts["classify"]},
                {"role": "user", "content": f"用户输入：{text}"}
            ]
            response = self.client.invoke(messages)
            intent = response.content.strip().lower()
            if "price" in intent:
                return "price"
            elif "tech" in intent:
                return "tech"
            else:
                return "default"
        except Exception as e:
            logger.error(f"意图识别出错{e}")
            return "default"

    def generate_reply(self, user_msg, item_desc, context= None, img_url = None,long_term_context= None):
        """
        生成回复（升级版）

        参数:
            user_msg: 用户发的话
            item_desc: 商品描述
            context: 短期记忆（最近10条对话）
            img_url: 图片URL
            long_term_context: 长期记忆检索结果（已融合在context中，此参数备用）
        """
        if context is None:
            context = []
        intent = self.detect_intent(user_msg)
        self.last_intent = intent

        logger.info(f"识别意图：{intent}")

        system_prompt = self.prompts.get(intent,self.prompts["default"])

        full_system_prompt_parts = [f"{system_prompt}\n\n当前正在出售的商品：\n{item_desc}，不要回复任何与当前售卖商品无关的话！！"]
        if long_term_context:
            full_system_prompt_parts.insert(1,
                f"\n\n【历史对话参考（来自长期记忆）】\n{long_term_context}\n"
                f"请参考以上信息回答，但以最近的对话内容为准。"
            )
        full_system_prompt = "".join(full_system_prompt_parts)
        messages = [{"role":"system","content":full_system_prompt}]

        if context:
            messages.extend(context)

        if img_url:
            user_content = []
            if user_msg and user_msg not in ["[用户发送了一张图片]", "[图片]"]:
                user_content.append({"type": "text", "text": user_msg})
            else:
                user_content.append({
                    "type": "text",
                    "text": """当用户发送图片时，你需要先判断图片内容是否与当前售卖的商品相关：
 判断标准：- 相关：图片中的物品与当前商品是同一类/同一个东西，或者图片是在询问商品细节
- 无关：图片中的内容与当前商品完全无关（
回复规则：
1. 如果图片与商品【相关】→ 正常根据图片内容回复，介绍商品信息
2. 如果图片与商品【无关】→ 回复：亲，我有什么可以帮您的吗
3. 如果无法确定是否相关 → 回复：亲，我有什么可以帮您的吗
请严格按照以上规则回复，不要自作主张对无关图片进行描述或评论。"""
                })
            # 🔑 核心改动：下载图片转 base64
            base64_data_uri = download_image_as_base64(img_url)
            if base64_data_uri:
                # ✅ 用 base64 data URI，所有模型都支持
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": base64_data_uri}
                })
                logger.info("📷 使用 base64 方式传入图片")
            else:
                # base64 下载失败，回退到原始URL试试
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url}
                })
                logger.warning("📷 base64下载失败，回退到原始URL")
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_msg if user_msg else "无文本内容"})
        try:
            response = self.client.invoke(messages)
            reply = response.content.strip()
            return reply
        except Exception as e:
            logger.error(f"生成回复失败：{e}")
            return "亲，稍等一下哈~"



