"""
对话意图链分析器

追踪用户在一个对话中意图的演变过程，识别意图转变模式，分析情感轨迹。
"""

from datetime import datetime
from enum import Enum
from loguru import logger
from typing import List, Dict, Optional, Tuple


class Intent(str, Enum):
    """用户意图分类"""
    PRICE = "price"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    AUTHENTICITY = "authenticity"
    TIME_SENSITIVITY = "time_sensitivity"
    PURCHASE_DECISION = "purchase_decision"
    COMPLAINT = "complaint"
    DEFAULT = "default"


class Emotion(str, Enum):
    """情感倾向"""
    POSITIVE = "positive"      # 🟢 积极（满意、准备购买）
    NEUTRAL = "neutral"        # 🟡 中立
    NEGATIVE = "negative"      # 🔴 消极（砍价激烈、不耐烦）


class IntentRecord:
    """单条意图记录"""

    def __init__(
        self,
        message_index: int,
        message_text: str,
        intent: Intent,
        confidence: float,
        emotion: Emotion,
        keywords: List[str] = None,
        timestamp: Optional[datetime] = None
    ):
        self.message_index = message_index
        self.message_text = message_text
        self.intent = intent
        self.confidence = confidence
        self.emotion = emotion
        self.keywords = keywords or []

        # 处理timestamp：如果是None就用当前时间，如果是字符串就保持，如果是datetime就保持
        if timestamp is None:
            self.timestamp = datetime.now()
        elif isinstance(timestamp, str):
            # 保持字符串格式
            self.timestamp = timestamp
        else:
            # 假设是datetime对象
            self.timestamp = timestamp

        self.transition_from = None  # 从哪个意图转移过来
        self.transition_smoothness = 0.5  # 转移的自然程度（0-1）
        self.resolved = False  # 该意图是否已被满足

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "message_index": self.message_index,
            "message_text": self.message_text,
            "intent": self.intent.value,
            "confidence": round(self.confidence, 3),
            "emotion": self.emotion.value,
            "keywords": self.keywords,
            "timestamp": self.timestamp if isinstance(self.timestamp, str) else self.timestamp.isoformat(),
            "transition_from": self.transition_from.value if self.transition_from else None,
            "transition_smoothness": round(self.transition_smoothness, 3),
            "resolved": self.resolved
        }


class IntentChain:
    """对话意图链"""

    # 意图自然转移矩阵（转移的合理性）
    TRANSITION_SMOOTHNESS = {
        (Intent.PRICE, Intent.PRICE): 1.0,              # 同一意图，完全自然
        (Intent.PRICE, Intent.QUALITY): 0.8,            # 砍价后关注品质，很自然
        (Intent.PRICE, Intent.LOGISTICS): 0.7,          # 砍价后关注物流，自然
        (Intent.QUALITY, Intent.PRICE): 0.6,            # 品质确认后砍价，有点突兀
        (Intent.QUALITY, Intent.QUALITY): 1.0,
        (Intent.QUALITY, Intent.LOGISTICS): 0.9,        # 品质确认后关注物流，很自然
        (Intent.LOGISTICS, Intent.PRICE): 0.4,          # 物流后再砍价，比较突兀
        (Intent.LOGISTICS, Intent.QUALITY): 0.5,        # 物流后回到品质，较突兀
        (Intent.LOGISTICS, Intent.LOGISTICS): 1.0,
        (Intent.PURCHASE_DECISION, Intent.PRICE): 0.2,  # 决定购买后再砍价，很突兀
        (Intent.PURCHASE_DECISION, Intent.QUALITY): 0.2,
        (Intent.PURCHASE_DECISION, Intent.LOGISTICS): 0.3,
    }

    # 情感转移矩阵（哪些转移是正常的）
    EMOTION_TRANSITION = {
        (Emotion.NEGATIVE, Emotion.NEGATIVE): 1.0,      # 一直消极
        (Emotion.NEGATIVE, Emotion.POSITIVE): 0.3,      # 消极→积极，反差大
        (Emotion.NEGATIVE, Emotion.NEUTRAL): 0.7,
        (Emotion.NEUTRAL, Emotion.NEGATIVE): 0.7,
        (Emotion.NEUTRAL, Emotion.NEUTRAL): 1.0,
        (Emotion.NEUTRAL, Emotion.POSITIVE): 0.9,       # 中立→积极，自然
        (Emotion.POSITIVE, Emotion.NEGATIVE): 0.2,      # 积极→消极，反差大
        (Emotion.POSITIVE, Emotion.NEUTRAL): 0.7,
        (Emotion.POSITIVE, Emotion.POSITIVE): 1.0,      # 一直积极
    }

    def __init__(self, chat_id: str, user_id: str):
        self.chat_id = chat_id
        self.user_id = user_id
        self.chain: List[IntentRecord] = []
        self.created_at = datetime.now()

    def add_intent(self, record: IntentRecord) -> None:
        """添加意图记录"""
        if self.chain:
            # 计算与前一条的转移
            prev_record = self.chain[-1]
            record.transition_from = prev_record.intent

            # 查询转移的自然程度
            transition_key = (prev_record.intent, record.intent)
            record.transition_smoothness = self.TRANSITION_SMOOTHNESS.get(
                transition_key, 0.5
            )

        self.chain.append(record)

    def detect_intent_pattern(self) -> Dict:
        """检测意图模式"""
        if not self.chain:
            return {}

        patterns = {
            "total_intents": len(self.chain),
            "unique_intents": len(set(r.intent for r in self.chain)),
            "intent_sequence": [r.intent.value for r in self.chain],
            "dominant_intent": self._get_dominant_intent(),
            "intent_switches": self._count_intent_switches(),
            "abnormal_transitions": self._detect_abnormal_transitions(),
            "intent_coverage": self._calculate_intent_coverage(),
        }
        return patterns

    def _get_dominant_intent(self) -> Optional[str]:
        """获取主要意图"""
        intent_counts = {}
        for record in self.chain:
            intent_counts[record.intent] = intent_counts.get(record.intent, 0) + 1

        if intent_counts:
            dominant = max(intent_counts, key=intent_counts.get)
            return dominant.value
        return None

    def _count_intent_switches(self) -> int:
        """统计意图切换次数"""
        switches = 0
        for i in range(1, len(self.chain)):
            if self.chain[i].intent != self.chain[i-1].intent:
                switches += 1
        return switches

    def _detect_abnormal_transitions(self) -> List[Dict]:
        """检测不自然的转移"""
        abnormal = []
        for i in range(1, len(self.chain)):
            prev = self.chain[i-1]
            curr = self.chain[i]

            smoothness = self.TRANSITION_SMOOTHNESS.get(
                (prev.intent, curr.intent), 0.5
            )

            # 如果转移的自然程度 < 0.6，标记为不自然
            if smoothness < 0.6:
                abnormal.append({
                    "from_index": prev.message_index,
                    "to_index": curr.message_index,
                    "from_intent": prev.intent.value,
                    "to_intent": curr.intent.value,
                    "smoothness": round(smoothness, 3),
                    "reason": f"意图从{prev.intent.value}突然转向{curr.intent.value}"
                })

        return abnormal

    def _calculate_intent_coverage(self) -> Dict:
        """计算各意图的覆盖度"""
        intent_counts = {}
        for record in self.chain:
            intent_counts[record.intent] = intent_counts.get(record.intent, 0) + 1

        total = len(self.chain)
        coverage = {}
        for intent, count in intent_counts.items():
            coverage[intent.value] = {
                "count": count,
                "percentage": round(count / total * 100, 1) if total > 0 else 0
            }

        return coverage

    def analyze_emotional_trajectory(self) -> Dict:
        """分析情感轨迹"""
        if not self.chain:
            return {}

        emotions = [r.emotion for r in self.chain]

        # 计算总体情感倾向
        pos_count = sum(1 for e in emotions if e == Emotion.POSITIVE)
        neg_count = sum(1 for e in emotions if e == Emotion.NEGATIVE)
        neu_count = sum(1 for e in emotions if e == Emotion.NEUTRAL)
        total = len(emotions)

        # 找情感转折点
        turning_points = []
        for i in range(1, len(emotions)):
            prev_emotion = emotions[i-1]
            curr_emotion = emotions[i]

            if prev_emotion != curr_emotion:
                # 情感发生了变化
                turning_points.append({
                    "message_index": self.chain[i].message_index,
                    "from_emotion": prev_emotion.value,
                    "to_emotion": curr_emotion.value,
                    "is_reversal": (prev_emotion == Emotion.NEGATIVE and curr_emotion == Emotion.POSITIVE) or \
                                   (prev_emotion == Emotion.POSITIVE and curr_emotion == Emotion.NEGATIVE)
                })

        # 计算情感反差指数
        discord_count = 0
        for i in range(1, len(emotions)):
            prev_e = emotions[i-1]
            curr_e = emotions[i]
            discord = self.EMOTION_TRANSITION.get((prev_e, curr_e), 0.5)
            if discord < 0.5:
                discord_count += 1

        return {
            "overall_trend": self._get_overall_trend(emotions),
            "positive_percentage": round(pos_count / total * 100, 1) if total > 0 else 0,
            "negative_percentage": round(neg_count / total * 100, 1) if total > 0 else 0,
            "neutral_percentage": round(neu_count / total * 100, 1) if total > 0 else 0,
            "turning_points": turning_points,
            "emotion_discord_count": discord_count,  # 情感不协调的转移次数
            "is_stable": discord_count == 0,  # 情感是否稳定
        }

    def _get_overall_trend(self, emotions: List[Emotion]) -> str:
        """获取总体情感趋势"""
        if not emotions:
            return "unknown"

        # 简单划分：前半段和后半段
        mid = len(emotions) // 2
        first_half = emotions[:mid]
        second_half = emotions[mid:]

        def get_emotion_score(emotion_list):
            if not emotion_list:
                return 0
            pos = sum(1 for e in emotion_list if e == Emotion.POSITIVE)
            neg = sum(1 for e in emotion_list if e == Emotion.NEGATIVE)
            return (pos - neg) / len(emotion_list)

        first_score = get_emotion_score(first_half)
        second_score = get_emotion_score(second_half)

        if first_score > 0.3 and second_score > 0.3:
            return "consistently_positive"
        elif first_score < -0.3 and second_score < -0.3:
            return "consistently_negative"
        elif first_score < -0.1 and second_score > 0.1:
            return "improving"  # 从消极转向积极
        elif first_score > 0.1 and second_score < -0.1:
            return "deteriorating"  # 从积极转向消极
        else:
            return "mixed"  # 混合

    def generate_chain_summary(self) -> str:
        """生成意图链的人类可读总结"""
        if not self.chain:
            return "无对话记录"

        # 构建摘要
        summary_parts = []

        # 1. 意图序列摘要
        intent_sequence = " → ".join([r.intent.value for r in self.chain])
        summary_parts.append(f"意图演变：{intent_sequence}")

        # 2. 主要意图
        dominant = self._get_dominant_intent()
        intent_pattern = self.detect_intent_pattern()
        coverage = intent_pattern.get("intent_coverage", {})

        top_intents = sorted(
            [(k, v["percentage"]) for k, v in coverage.items()],
            key=lambda x: x[1],
            reverse=True
        )[:2]

        top_str = " > ".join([f"{k}({v}%)" for k, v in top_intents])
        summary_parts.append(f"关注重点：{top_str}")

        # 3. 意图演变速度
        switches = intent_pattern.get("intent_switches", 0)
        if switches > 3:
            summary_parts.append("用户需求变化频繁，可能在探索多个方面")
        elif switches == 0:
            summary_parts.append("用户需求明确，专注于单一方面")
        else:
            summary_parts.append("用户需求逐步深化")

        # 4. 情感轨迹
        emotion_analysis = self.analyze_emotional_trajectory()
        overall_trend = emotion_analysis.get("overall_trend", "unknown")

        trend_mapping = {
            "consistently_positive": "用户态度一直积极，购买意愿强",
            "consistently_negative": "用户态度一直消极，可能存在顾虑",
            "improving": "用户态度逐步改善，可能在消除顾虑",
            "deteriorating": "用户态度恶化，可能发现问题",
            "mixed": "用户态度波动，需要进一步了解"
        }
        summary_parts.append(trend_mapping.get(overall_trend, "情感倾向不明确"))

        # 5. 异常转移
        abnormal = intent_pattern.get("abnormal_transitions", [])
        if abnormal:
            summary_parts.append(f"⚠️ 检测到{len(abnormal)}个不自然的意图转移，可能反映用户困惑或新发现")

        return "，".join(summary_parts)

    def to_dict(self) -> dict:
        """转为字典（用于数据库存储）"""
        patterns = self.detect_intent_pattern()
        emotion_analysis = self.analyze_emotional_trajectory()

        return {
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "chain_length": len(self.chain),
            "chain_records": [r.to_dict() for r in self.chain],
            "intent_patterns": patterns,
            "emotional_analysis": emotion_analysis,
            "summary": self.generate_chain_summary()
        }


class IntentChainAnalyzer:
    """意图链分析器"""

    def __init__(self, db=None):
        self.db = db

    def track_intent_evolution(
        self,
        chat_id: str,
        user_id: str,
        messages_with_intents: List[Dict]
    ) -> IntentChain:
        """
        追踪用户的意图演变

        参数:
            chat_id: 会话ID
            user_id: 用户ID
            messages_with_intents: 包含意图信息的消息列表
                每条消息格式: {
                    'message_index': int,
                    'text': str,
                    'intent': str,
                    'confidence': float,
                    'emotion': str,
                    'keywords': List[str],
                    'timestamp': datetime or str (optional)
                }

        返回:
            IntentChain对象
        """
        chain = IntentChain(chat_id, user_id)

        for msg_data in messages_with_intents:
            try:
                # 解析意图和情感
                intent = Intent(msg_data.get('intent', 'default'))
                emotion = Emotion(msg_data.get('emotion', 'neutral'))

                # 处理timestamp：可能是datetime或字符串
                timestamp = msg_data.get('timestamp')
                if isinstance(timestamp, str):
                    # 如果是字符串，尝试解析为datetime
                    try:
                        from datetime import datetime
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except:
                        timestamp = None

                record = IntentRecord(
                    message_index=msg_data.get('message_index', 0),
                    message_text=msg_data.get('text', ''),
                    intent=intent,
                    confidence=msg_data.get('confidence', 0.5),
                    emotion=emotion,
                    keywords=msg_data.get('keywords', []),
                    timestamp=timestamp
                )

                chain.add_intent(record)
            except (ValueError, KeyError) as e:
                logger.warning(f"解析消息意图失败: {e}, 消息: {msg_data}")
                continue

        logger.info(f"✅ 意图链追踪完成: chat={chat_id}, 消息数={len(chain.chain)}")
        return chain

    def save_intent_chain(self, chain: IntentChain) -> bool:
        """保存意图链到数据库"""
        if not self.db:
            logger.warning("未连接数据库，无法保存意图链")
            return False

        try:
            chain_data = chain.to_dict()

            logger.info(f"💾 意图链已保存: chat={chain.chat_id}")
            return True
        except Exception as e:
            logger.error(f"保存意图链失败: {e}")
            return False
