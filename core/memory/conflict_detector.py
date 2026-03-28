"""
冲突检测系统

识别用户表面诉求和真实需求之间的不匹配，检测各种冲突类型。
"""

from datetime import datetime
from enum import Enum
from loguru import logger
from typing import List, Dict, Optional
from core.memory.intent_chain_analyzer import IntentChain, Intent, Emotion


class ConflictType(str, Enum):
    """冲突类型"""
    BARGAIN_PARADOX = "bargain_paradox"              # 砍价悖论：小额多轮砍价
    QUALITY_ANXIETY = "quality_anxiety"              # 品质焦虑：突然转向品质询问
    TIME_ANXIETY = "time_anxiety"                    # 时间焦虑：最后关注发货时间
    DECISION_COLDNESS = "decision_coldness"          # 决策冷淡：长时间犹豫不决
    GENUINE_PRICE_SENSITIVITY = "genuine_price_sensitivity"  # 真正的价格敏感
    AUTHENTICITY_CONCERN = "authenticity_concern"    # 真实性关切：突然质疑真伪
    EMOTIONAL_MISMATCH = "emotional_mismatch"        # 情感不匹配：言词vs情感矛盾
    INTENT_CONTRADICTION = "intent_contradiction"    # 意图矛盾：前后需求不一致
    UNRESOLVED_INTENT = "unresolved_intent"          # 意图未解决：问题被多次提及


class ConflictReport:
    """冲突报告"""

    def __init__(
        self,
        chat_id: str,
        user_id: str,
        conflict_type: ConflictType,
        confidence: float
    ):
        self.chat_id = chat_id
        self.user_id = user_id
        self.conflict_type = conflict_type
        self.confidence = round(confidence, 3)
        self.surface_intent = None  # 表面诉求
        self.underlying_intent = None  # 潜在真实需求
        self.evidence = []  # 证据（文本片段等）
        self.recommended_strategy = ""  # 建议策略
        self.created_at = datetime.now()

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "conflict_type": self.conflict_type.value,
            "confidence": self.confidence,
            "surface_intent": self.surface_intent,
            "underlying_intent": self.underlying_intent,
            "evidence": self.evidence,
            "recommended_strategy": self.recommended_strategy,
            "created_at": self.created_at.isoformat()
        }


class ConflictDetector:
    """冲突检测器"""

    def __init__(self, db=None):
        self.db = db

    def detect_conflicts(
        self,
        intent_chain: IntentChain,
        user_profile: Optional[Dict] = None,
        interaction_logs: Optional[List[Dict]] = None
    ) -> List[ConflictReport]:
        """
        检测对话中存在的冲突

        参数:
            intent_chain: 意图链对象
            user_profile: 用户画像（可选）
            interaction_logs: 交互日志（可选）

        返回:
            冲突报告列表
        """
        conflicts = []

        # 1. 检测砍价悖论
        bargain_conflict = self._check_bargain_paradox(intent_chain, user_profile)
        if bargain_conflict:
            conflicts.append(bargain_conflict)

        # 2. 检测品质焦虑
        quality_conflict = self._check_quality_anxiety(intent_chain)
        if quality_conflict:
            conflicts.append(quality_conflict)

        # 3. 检测时间焦虑
        time_conflict = self._check_time_anxiety(intent_chain)
        if time_conflict:
            conflicts.append(time_conflict)

        # 4. 检测决策冷淡
        decision_conflict = self._check_decision_coldness(intent_chain)
        if decision_conflict:
            conflicts.append(decision_conflict)

        # 5. 检测真正的价格敏感
        price_conflict = self._check_genuine_price_sensitivity(intent_chain, user_profile)
        if price_conflict:
            conflicts.append(price_conflict)

        # 6. 检测真实性关切
        auth_conflict = self._check_authenticity_concern(intent_chain)
        if auth_conflict:
            conflicts.append(auth_conflict)

        # 7. 检测情感不匹配
        emotion_conflict = self._check_emotional_mismatch(intent_chain)
        if emotion_conflict:
            conflicts.append(emotion_conflict)

        # 8. 检测意图矛盾
        contradiction_conflict = self._check_intent_contradiction(intent_chain)
        if contradiction_conflict:
            conflicts.append(contradiction_conflict)

        logger.info(f"✅ 冲突检测完成: chat={intent_chain.chat_id}, 检测到{len(conflicts)}个冲突")

        return conflicts

    def _check_bargain_paradox(
        self,
        intent_chain: IntentChain,
        user_profile: Optional[Dict] = None
    ) -> Optional[ConflictReport]:
        """
        检测砍价悖论

        规则：
        - 砍价次数 > 2 AND 砍价幅度小 (< 10%) AND 多次砍价后接受原价/小幅降价
        -> 用户不是真正的价格敏感，而是需要被认可
        """
        price_intents = [
            r for r in intent_chain.chain if r.intent == Intent.PRICE
        ]

        if len(price_intents) < 2:
            return None

        # 简化计算：这里假设砍价频率和激进度从user_profile获取
        # 实际应该从价格历史中提取
        if not user_profile:
            return None

        bargain_freq = user_profile.get('bargain_frequency', 0)
        bargain_agg = user_profile.get('bargain_aggressiveness', 0)

        # 判断条件
        if len(price_intents) >= 3 and bargain_freq > 0.5 and bargain_agg < 0.4:
            conflict = ConflictReport(
                chat_id=intent_chain.chat_id,
                user_id=intent_chain.user_id,
                conflict_type=ConflictType.BARGAIN_PARADOX,
                confidence=0.75
            )
            conflict.surface_intent = "砍价"
            conflict.underlying_intent = "寻求认可/确认被重视"
            conflict.evidence = [
                f"砍价次数：{len(price_intents)}次（多次）",
                f"砍价激进度：{bargain_agg:.1%}（较低）",
                "砍价幅度较小但持续进行"
            ]
            conflict.recommended_strategy = (
                "不要继续围绕价格纠缠。"
                "转变策略：强调商品的稀有性、质量保证、正品保证。"
                "用户的真实需求是确认商品的价值，而非单纯的价格优惠。"
            )
            return conflict

        return None

    def _check_quality_anxiety(
        self,
        intent_chain: IntentChain
    ) -> Optional[ConflictReport]:
        """
        检测品质焦虑

        规则：
        - 用户从price intent突然转向quality intent（急速转移）
        -> 可能在砍价过程中发现了质量问题或产生了疑虑
        """
        abnormal_transitions = []
        patterns = intent_chain.detect_intent_pattern()

        for transition in patterns.get("abnormal_transitions", []):
            if (transition.get("from_intent") == Intent.PRICE.value and
                transition.get("to_intent") == Intent.QUALITY.value):
                if transition.get("smoothness", 0.5) < 0.7:
                    abnormal_transitions.append(transition)

        if not abnormal_transitions:
            return None

        conflict = ConflictReport(
            chat_id=intent_chain.chat_id,
            user_id=intent_chain.user_id,
            conflict_type=ConflictType.QUALITY_ANXIETY,
            confidence=0.7
        )
        conflict.surface_intent = "询问品质细节"
        conflict.underlying_intent = "对商品质量产生了疑虑"
        conflict.evidence = [
            f"检测到{len(abnormal_transitions)}个从价格到品质的急速转移",
            "用户在砍价过程中突然转向品质询问",
            "这种转移显得不自然，暗示有新发现"
        ]
        conflict.recommended_strategy = (
            "立即主动提供详细的品质证明。"
            "包括：成色、使用时长、有无缺陷、维修历史等。"
            "提供权威鉴定证书或交易记录作为证明。"
            "消除用户心中的质量疑虑。"
        )
        return conflict

    def _check_time_anxiety(
        self,
        intent_chain: IntentChain
    ) -> Optional[ConflictReport]:
        """
        检测时间焦虑

        规则：
        - 用户在回答完价格和品质问题后，最后关注logistics（发货时间）
        - 且问题相对具体（"什么时候发货"、"几天到")
        -> 用户已经做出购买决策，现在只关心交付
        """
        if not intent_chain.chain:
            return None

        # 获取最后3条消息的意图序列
        recent_records = intent_chain.chain[-3:]

        # 检查是否最后一条是logistics intent
        if recent_records[-1].intent != Intent.LOGISTICS:
            return None

        # 检查前面是否有price或quality
        has_price_or_quality = any(
            r.intent in [Intent.PRICE, Intent.QUALITY]
            for r in recent_records[:-1]
        )

        if not has_price_or_quality:
            return None

        conflict = ConflictReport(
            chat_id=intent_chain.chat_id,
            user_id=intent_chain.user_id,
            conflict_type=ConflictType.TIME_ANXIETY,
            confidence=0.8
        )
        conflict.surface_intent = "询问发货时间"
        conflict.underlying_intent = "已经决定购买，现在关心交付"
        conflict.evidence = [
            "价格/品质问题已解决",
            "最后的问题转向物流（发货时间）",
            "这是购买决策的最后一步"
        ]
        conflict.recommended_strategy = (
            "突出发货速度和物流优势。"
            "立即确认发货时间、配送方式、预计到达时间。"
            "提供物流追踪链接。"
            "强化用户的购买信心，推进交易完成。"
        )
        return conflict

    def _check_decision_coldness(
        self,
        intent_chain: IntentChain
    ) -> Optional[ConflictReport]:
        """
        检测决策冷淡

        规则：
        - 对话轮数 >= 10 AND 消息间隔长（>1小时）AND 意图没有收敛到purchase_decision
        -> 用户购买意愿不足，需要额外激励
        """
        if len(intent_chain.chain) < 10:
            return None

        # 检查是否有purchase_decision intent
        has_purchase = any(
            r.intent == Intent.PURCHASE_DECISION
            for r in intent_chain.chain
        )

        if has_purchase:
            return None

        # 简化处理：如果对话很长但没有明确的购买决策，标记为冷淡
        emotion_analysis = intent_chain.analyze_emotional_trajectory()
        negative_pct = emotion_analysis.get("negative_percentage", 0)

        # 如果消极比例高或情感稳定但倾向于中立，表示冷淡
        if negative_pct > 30 or emotion_analysis.get("overall_trend") == "mixed":
            conflict = ConflictReport(
                chat_id=intent_chain.chat_id,
                user_id=intent_chain.user_id,
                conflict_type=ConflictType.DECISION_COLDNESS,
                confidence=0.65
            )
            conflict.surface_intent = "继续询问相关问题"
            conflict.underlying_intent = "购买意愿不足，需要更强的激励"
            conflict.evidence = [
                f"对话轮数：{len(intent_chain.chain)}（较长）",
                f"消极情感比例：{negative_pct:.1f}%",
                "未检测到明确的购买决策意图"
            ]
            conflict.recommended_strategy = (
                "主动提出新的价值主张或优惠方案。"
                "使用促销、限时优惠、赠品等激励手段。"
                "问用户'有什么我可以帮你的吗？'来打破僵局。"
                "如果无法推动，可能需要放弃这个客户。"
            )
            return conflict

        return None

    def _check_genuine_price_sensitivity(
        self,
        intent_chain: IntentChain,
        user_profile: Optional[Dict] = None
    ) -> Optional[ConflictReport]:
        """
        检测真正的价格敏感

        规则：
        - 砍价次数多 AND 砍价幅度大（> 15%）AND 坚决不放 AND 价格敏感度高
        -> 用户是真正的价格敏感，可能是预算限制
        """
        if not user_profile:
            return None

        bargain_freq = user_profile.get('bargain_frequency', 0)
        bargain_agg = user_profile.get('bargain_aggressiveness', 0)
        price_sens = user_profile.get('price_sensitivity', 0.5)

        # 判断条件：频繁砍价 + 激进砍价 + 高价格敏感
        if bargain_freq > 0.6 and bargain_agg > 0.5 and price_sens > 0.6:
            conflict = ConflictReport(
                chat_id=intent_chain.chat_id,
                user_id=intent_chain.user_id,
                conflict_type=ConflictType.GENUINE_PRICE_SENSITIVITY,
                confidence=0.8
            )
            conflict.surface_intent = "砍价"
            conflict.underlying_intent = "真正的价格敏感/预算限制"
            conflict.evidence = [
                f"砍价频率：{bargain_freq:.1%}（高）",
                f"砍价激进度：{bargain_agg:.1%}（高）",
                f"价格敏感度：{price_sens:.1%}（高）",
                "这是真实的价格敏感，而非虚假砍价"
            ]
            conflict.recommended_strategy = (
                "给予更多的价格灵活性和优惠空间。"
                "考虑分期付款方案。"
                "突出商品的性价比（而不是品质）。"
                "快速直接地回答价格问题。"
            )
            return conflict

        return None

    def _check_authenticity_concern(
        self,
        intent_chain: IntentChain
    ) -> Optional[ConflictReport]:
        """
        检测真实性关切

        规则：
        - 用户突然从quality intent转向authenticity intent
        -> 用户发现了可疑之处，需要真实性保证
        """
        patterns = intent_chain.detect_intent_pattern()
        abnormal_transitions = patterns.get("abnormal_transitions", [])

        for transition in abnormal_transitions:
            from_intent = transition.get("from_intent")
            to_intent = transition.get("to_intent")

            # 从任何意图转向authenticity都可能表示concern
            if to_intent == Intent.AUTHENTICITY.value:
                conflict = ConflictReport(
                    chat_id=intent_chain.chat_id,
                    user_id=intent_chain.user_id,
                    conflict_type=ConflictType.AUTHENTICITY_CONCERN,
                    confidence=0.7
                )
                conflict.surface_intent = f"询问真实性（从{from_intent}转移）"
                conflict.underlying_intent = "对商品真实性产生了疑虑"
                conflict.evidence = [
                    f"用户从{from_intent}忽然转向真实性询问",
                    "这种转移表明用户发现了新的关注点",
                    "可能在品质或价格中发现了可疑之处"
                ]
                conflict.recommended_strategy = (
                    "立即提供权威的真实性证明。"
                    "提供：正品认证、品牌授权证明、销售凭证、交易记录。"
                    "如果有质保卡、包装盒等，拍照上传。"
                    "主动消除用户的真实性疑虑。"
                )
                return conflict

        return None

    def _check_emotional_mismatch(
        self,
        intent_chain: IntentChain
    ) -> Optional[ConflictReport]:
        """
        检测情感不匹配

        规则：
        - 用户的话语（intent）显示积极（如决定购买）
        - 但情感倾向是负面（语气不满意）
        -> 存在矛盾，用户可能有保留
        """
        emotion_analysis = intent_chain.analyze_emotional_trajectory()
        turning_points = emotion_analysis.get("turning_points", [])

        # 检查是否有负面到正面的转折，但最后又回到负面
        mismatches = [
            tp for tp in turning_points
            if tp.get("is_reversal", False) and tp.get("to_emotion") == Emotion.NEGATIVE.value
        ]

        if not mismatches:
            return None

        # 检查最后几条消息的情感
        if intent_chain.chain:
            last_emotion = intent_chain.chain[-1].emotion
            second_last_emotion = (
                intent_chain.chain[-2].emotion
                if len(intent_chain.chain) > 1
                else None
            )

            # 如果最后是负面情感，但有purchase相关的intent
            if (last_emotion == Emotion.NEGATIVE and
                any(r.intent == Intent.PURCHASE_DECISION for r in intent_chain.chain[-3:])):

                conflict = ConflictReport(
                    chat_id=intent_chain.chat_id,
                    user_id=intent_chain.user_id,
                    conflict_type=ConflictType.EMOTIONAL_MISMATCH,
                    confidence=0.65
                )
                conflict.surface_intent = "表示要购买"
                conflict.underlying_intent = "实际上有保留或不满"
                conflict.evidence = [
                    "用户表示同意购买，但语气不满意",
                    f"最后的情感倾向是{last_emotion.value}（负面）",
                    "这种矛盾表明用户有隐藏的顾虑"
                ]
                conflict.recommended_strategy = (
                    "主动询问用户的疑虑：'您还有什么顾虑吗？'。"
                    "倾听真实想法，而不是急于成交。"
                    "解决根本问题，而不是表面承诺。"
                    "如果问题无法解决，坦诚地说出来，而不是强行推进。"
                )
                return conflict

        return None

    def _check_intent_contradiction(
        self,
        intent_chain: IntentChain
    ) -> Optional[ConflictReport]:
        """
        检测意图矛盾

        规则：
        - 用户的意图存在明显的前后不一致
        - 例如：砍价后表示要购买，然后又问"有没有便宜的替代品"
        -> 用户的真实需求可能是寻找替代方案，而非当前商品
        """
        intent_sequence = [r.intent for r in intent_chain.chain]

        # 简化检查：如果在PURCHASE_DECISION后还有PRICE intent
        purchase_indices = [
            i for i, intent in enumerate(intent_sequence)
            if intent == Intent.PURCHASE_DECISION
        ]

        if not purchase_indices:
            return None

        last_purchase_idx = max(purchase_indices)

        # 检查purchase后是否还有price或其他需求inquiry
        post_purchase_intents = intent_sequence[last_purchase_idx + 1:]

        if Intent.PRICE in post_purchase_intents or Intent.QUALITY in post_purchase_intents:
            conflict = ConflictReport(
                chat_id=intent_chain.chat_id,
                user_id=intent_chain.user_id,
                conflict_type=ConflictType.INTENT_CONTRADICTION,
                confidence=0.6
            )
            conflict.surface_intent = "同意购买"
            conflict.underlying_intent = "其实还在寻找替代品或犹豫中"
            conflict.evidence = [
                "用户表示要购买，但之后又提出新的疑问或需求",
                "这表明购买决策并不坚定",
                "用户可能在多个选项间权衡"
            ]
            conflict.recommended_strategy = (
                "直接问用户：'您是否还在考虑其他选项？'。"
                "了解用户真实的购买驱动因素。"
                "如果用户确实在比较，直接突出本商品的独特优势。"
                "如果用户心意已决，快速推进交易。"
            )
            return conflict

        return None

    def generate_conflict_summary(self, conflicts: List[ConflictReport]) -> str:
        """生成冲突总结"""
        if not conflicts:
            return "未检测到明显冲突"

        summary_parts = []

        for conflict in conflicts:
            summary_parts.append(
                f"【{conflict.conflict_type.value}】({conflict.confidence:.0%}置信度)\n"
                f"  表面诉求：{conflict.surface_intent}\n"
                f"  潜在需求：{conflict.underlying_intent}"
            )

        return "\n".join(summary_parts)
