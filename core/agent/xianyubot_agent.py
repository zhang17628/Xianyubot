import os

from dotenv import find_dotenv, load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI
from loguru import logger

from utils.xianyu_utils import download_image_as_base64

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

    def generate_reply(self, user_msg, item_desc, context= None, img_url = None, long_term_context= None, user_profile=None, intent_chain_data=None, conflict_data=None):
        """
        生成回复（升级版）

        参数:
            user_msg: 用户发的话
            item_desc: 商品描述
            context: 短期记忆（最近10条对话）
            img_url: 图片URL
            long_term_context: 长期记忆检索结果（已融合在context中，此参数备用）
            user_profile: 用户画像字典（新增）
            intent_chain_data: 意图链数据（新增）
            conflict_data: 冲突检测结果（新增）
        """
        if context is None:
            context = []
        intent = self.detect_intent(user_msg)
        self.last_intent = intent

        logger.info(f"识别意图：{intent}")

        system_prompt = self.prompts.get(intent,self.prompts["default"])

        full_system_prompt_parts = [f"{system_prompt}\n\n当前正在出售的商品：\n{item_desc}，不要回复任何与当前售卖商品无关的话！！"]

        # 新增：注入用户画像和意图链信息
        if user_profile or intent_chain_data or conflict_data:
            profile_hint = self._build_enhanced_profile_hint(
                user_profile=user_profile,
                intent_chain_data=intent_chain_data,
                conflict_data=conflict_data
            )
            full_system_prompt_parts.append(f"\n\n{profile_hint}")

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

    def _build_profile_hint(self, user_profile):
        """
        根据用户画像构建提示信息

        参数:
            user_profile: 用户画像字典

        返回:
            用户画像提示字符串
        """
        if not user_profile:
            return ""

        # 提取关键信息
        user_type = user_profile.get('user_type', 'unknown')
        bargain_freq = user_profile.get('bargain_frequency', 0)
        price_sens = user_profile.get('price_sensitivity', 0.5)
        quality_focus = user_profile.get('quality_focus', 0.5)
        logistics = user_profile.get('logistics_concern', 0.5)
        politeness = user_profile.get('politeness_level', 0.5)
        directness = user_profile.get('directness_level', 0.5)

        # 构建提示信息
        hints = ["【用户画像参考】"]

        # 用户类型
        hints.append(f"- 用户类型：{user_type}")

        # 关注点分析
        focus_points = []
        if price_sens > 0.6:
            focus_points.append(f"价格敏感（{int(price_sens*100)}%）")
        if quality_focus > 0.6:
            focus_points.append(f"品质关注（{int(quality_focus*100)}%）")
        if logistics > 0.6:
            focus_points.append(f"物流关注（{int(logistics*100)}%）")
        if focus_points:
            hints.append(f"- 关注重点：{' > '.join(focus_points)}")

        # 沟通风格
        style_desc = []
        if directness > 0.6:
            style_desc.append("直接")
        else:
            style_desc.append("温和")
        if politeness > 0.6:
            style_desc.append("礼貌")
        else:
            style_desc.append("随意")
        hints.append(f"- 沟通风格：{'/'.join(style_desc)}")

        # 砍价特征
        if bargain_freq > 0.6:
            hints.append(f"- 砍价特征：频繁砍价（频率{int(bargain_freq*100)}%），给予更多价格灵活性")
        elif bargain_freq > 0.3:
            hints.append(f"- 砍价特征：偶尔砍价（频率{int(bargain_freq*100)}%），适度让价")

        # 基于用户类型的建议策略
        if user_type == "砍价达人":
            hints.append("- 建议策略：在价格上给予更多空间；强调商品性价比而非品质；简洁直接地回答")
        elif user_type == "品质追求者":
            hints.append("- 建议策略：强调成色、使用状况等品质相关信息；提供详细的商品参数")
        elif user_type == "急速购手":
            hints.append("- 建议策略：强调发货速度、物流服务；快速直接地回答；提供配送时间预估")
        elif user_type == "慎重型":
            hints.append("- 建议策略：提供详细的商品信息和历史交易数据；耐心回答所有问题")

        return "\n".join(hints)

    def _build_enhanced_profile_hint(self, user_profile=None, intent_chain_data=None, conflict_data=None):
        """
        构建增强的用户画像提示，包含意图链和冲突检测信息

        参数:
            user_profile: 用户画像字典
            intent_chain_data: 意图链数据
            conflict_data: 冲突检测结果

        返回:
            增强的提示字符串
        """
        hints = []

        # 第一部分：基础用户画像
        if user_profile:
            hints.append(self._build_profile_hint(user_profile))

        # 第二部分：意图链分析
        if intent_chain_data:
            hints.append(self._build_intent_chain_hint(intent_chain_data))

        # 第三部分：冲突检测和应对策略
        if conflict_data:
            hints.append(self._build_conflict_hint(conflict_data))

        return "\n".join(hints) if hints else ""

    def _build_intent_chain_hint(self, intent_chain_data):
        """
        根据意图链数据构建提示信息

        参数:
            intent_chain_data: 意图链数据（包含summary, dominant_intent等）

        返回:
            意图链提示字符串
        """
        if not intent_chain_data:
            return ""

        hints = ["【对话意图链分析】"]

        chain_summary = intent_chain_data.get('chain_summary', '')
        dominant_intent = intent_chain_data.get('dominant_intent', 'unknown')
        overall_emotion = intent_chain_data.get('overall_emotion', 'unknown')

        if chain_summary:
            hints.append(f"- 对话演变：{chain_summary}")

        if dominant_intent != 'unknown':
            hints.append(f"- 主要意图：{dominant_intent}")

        if overall_emotion and overall_emotion != 'unknown':
            emotion_desc = self._translate_emotion(overall_emotion)
            hints.append(f"- 情感趋势：{emotion_desc}")

        return "\n".join(hints)

    def _build_conflict_hint(self, conflict_data):
        """
        根据冲突检测结果构建提示信息

        参数:
            conflict_data: 冲突检测结果（单个或列表）

        返回:
            冲突提示字符串
        """
        if not conflict_data:
            return ""

        # 处理单个或多个冲突
        conflicts = conflict_data if isinstance(conflict_data, list) else [conflict_data]

        if not conflicts:
            return ""

        hints = ["【冲突检测与应对策略】"]

        for conflict in conflicts:
            conflict_type = conflict.get('conflict_type', 'unknown')
            confidence = conflict.get('confidence', 0)
            surface = conflict.get('surface_intent', '')
            underlying = conflict.get('underlying_intent', '')
            strategy = conflict.get('recommended_strategy', '')

            hints.append(f"\n- 检测到【{conflict_type}】（{confidence:.0%}置信度）")
            if surface:
                hints.append(f"  表面诉求：{surface}")
            if underlying:
                hints.append(f"  潜在需求：{underlying}")
            if strategy:
                hints.append(f"  应对策略：{strategy}")

        return "\n".join(hints)

    def _translate_emotion(self, emotion_trend):
        """将情感趋势代码翻译为中文描述"""
        emotion_map = {
            "consistently_positive": "用户态度一直积极，购买意愿强",
            "consistently_negative": "用户态度一直消极，可能存在顾虑",
            "improving": "用户态度逐步改善，可能在消除顾虑",
            "deteriorating": "用户态度恶化，可能发现问题",
            "mixed": "用户态度波动，需要进一步了解"
        }
        return emotion_map.get(emotion_trend, "情感倾向不明确")
