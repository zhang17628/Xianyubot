"""
冲突检测规则库

定义可配置的冲突检测规则，支持规则的添加、修改和评分。
"""

from typing import Dict, Callable, List, Optional
from dataclasses import dataclass


@dataclass
class ConflictRule:
    """冲突检测规则"""

    rule_id: str                           # 规则ID
    conflict_type: str                     # 冲突类型
    name: str                              # 规则名称
    description: str                       # 规则描述
    condition_check: Callable              # 条件检查函数
    extract_evidence: Callable             # 证据提取函数
    recommended_strategy: Callable         # 建议策略生成函数
    severity: str = "medium"               # 严重程度：low/medium/high
    enabled: bool = True                   # 是否启用

    def evaluate(self, intent_chain, user_profile=None, interaction_logs=None) -> Optional[Dict]:
        """
        评估规则是否命中

        返回: 如果规则命中，返回冲突报告字典；否则返回None
        """
        if not self.enabled:
            return None

        # 检查条件
        is_matched, confidence = self.condition_check(intent_chain, user_profile, interaction_logs)

        if not is_matched:
            return None

        # 提取证据
        evidence = self.extract_evidence(intent_chain, user_profile, interaction_logs)

        # 生成策略
        strategy = self.recommended_strategy(intent_chain, user_profile, interaction_logs)

        return {
            "rule_id": self.rule_id,
            "conflict_type": self.conflict_type,
            "name": self.name,
            "confidence": confidence,
            "evidence": evidence,
            "strategy": strategy,
            "severity": self.severity
        }


# ============================================================
# 具体规则实现
# ============================================================

def bargain_paradox_condition(intent_chain, user_profile=None, interaction_logs=None):
    """砍价悖论条件检查"""
    if not user_profile:
        return False, 0

    bargain_freq = user_profile.get('bargain_frequency', 0)
    bargain_agg = user_profile.get('bargain_aggressiveness', 0)

    # 多次砍价但幅度小
    is_matched = bargain_freq > 0.5 and bargain_agg < 0.4
    confidence = min(bargain_freq * (1 - bargain_agg), 1.0)

    return is_matched, confidence


def bargain_paradox_evidence(intent_chain, user_profile=None, interaction_logs=None):
    """砍价悖论证据提取"""
    evidence = []

    if user_profile:
        bargain_freq = user_profile.get('bargain_frequency', 0)
        bargain_agg = user_profile.get('bargain_aggressiveness', 0)
        bargain_count = user_profile.get('bargain_count', 0)

        evidence.append(f"砍价次数：{bargain_count}次（多次）")
        evidence.append(f"砍价频率：{bargain_freq:.1%}")
        evidence.append(f"砍价激进度：{bargain_agg:.1%}（较低）")

    return evidence


def bargain_paradox_strategy(intent_chain, user_profile=None, interaction_logs=None):
    """砍价悖论策略"""
    return (
        "不要继续围绕价格纠缠，这不是真正的价格敏感。"
        "转变策略：强调商品的稀有性、质量保证、正品保证、性价比。"
        "用户的真实需求是被重视和认可，而不是单纯的价格优惠。"
        "可以说：'这个价格已经很有竞争力了，主要是品质和信誉有保证。'"
    )


def quality_anxiety_condition(intent_chain, user_profile=None, interaction_logs=None):
    """品质焦虑条件检查"""
    patterns = intent_chain.detect_intent_pattern()
    abnormal = patterns.get("abnormal_transitions", [])

    # 查找从PRICE到QUALITY的不自然转移
    price_to_quality = [
        t for t in abnormal
        if t.get("from_intent") == "price" and t.get("to_intent") == "quality"
        and t.get("smoothness", 0.5) < 0.7
    ]

    is_matched = len(price_to_quality) > 0
    confidence = min(len(price_to_quality) * 0.4, 1.0) if is_matched else 0

    return is_matched, confidence


def quality_anxiety_evidence(intent_chain, user_profile=None, interaction_logs=None):
    """品质焦虑证据提取"""
    patterns = intent_chain.detect_intent_pattern()
    abnormal = patterns.get("abnormal_transitions", [])

    price_to_quality = [
        t for t in abnormal
        if t.get("from_intent") == "price" and t.get("to_intent") == "quality"
    ]

    evidence = [
        f"检测到{len(price_to_quality)}个从价格到品质的急速转移",
        "用户在砍价过程中突然转向品质询问",
        "这种转移显得不自然，可能表示用户发现了质量问题"
    ]

    return evidence


def quality_anxiety_strategy(intent_chain, user_profile=None, interaction_logs=None):
    """品质焦虑策略"""
    return (
        "立即主动提供详细的品质证明，消除用户疑虑。"
        "包括：成色照片、使用时长、有无缺陷、维修历史。"
        "如有权威鉴定证书，立即出示。"
        "提供交易记录和历史评价，增强信任。"
    )


def time_anxiety_condition(intent_chain, user_profile=None, interaction_logs=None):
    """时间焦虑条件检查"""
    if len(intent_chain.chain) < 3:
        return False, 0

    # 检查最后几条消息
    recent = intent_chain.chain[-3:]
    last_intent = recent[-1].intent

    # 最后是logistics，前面有price或quality
    from core.memory.intent_chain_analyzer import Intent

    is_last_logistics = last_intent == Intent.LOGISTICS
    has_prior_discussion = any(
        r.intent in [Intent.PRICE, Intent.QUALITY]
        for r in recent[:-1]
    )

    is_matched = is_last_logistics and has_prior_discussion
    confidence = 0.8 if is_matched else 0

    return is_matched, confidence


def time_anxiety_evidence(intent_chain, user_profile=None, interaction_logs=None):
    """时间焦虑证据提取"""
    evidence = [
        "价格/品质问题已被讨论和解决",
        "最后的问题转向物流时间",
        "这通常表示用户已做出购买决策，现在只关心交付"
    ]
    return evidence


def time_anxiety_strategy(intent_chain, user_profile=None, interaction_logs=None):
    """时间焦虑策略"""
    return (
        "突出发货速度和物流优势。"
        "立即确认发货时间、配送方式、预计到达时间。"
        "提供物流追踪链接和配送保证。"
        "强化用户的购买信心，推进交易完成。"
        "建议立即确认订单，不要让用户有反悔的时间。"
    )


def decision_coldness_condition(intent_chain, user_profile=None, interaction_logs=None):
    """决策冷淡条件检查"""
    from core.memory.intent_chain_analyzer import Intent

    if len(intent_chain.chain) < 10:
        return False, 0

    # 检查是否有purchase_decision
    has_purchase = any(
        r.intent == Intent.PURCHASE_DECISION
        for r in intent_chain.chain
    )

    if has_purchase:
        return False, 0

    emotion_analysis = intent_chain.analyze_emotional_trajectory()
    negative_pct = emotion_analysis.get("negative_percentage", 0)
    trend = emotion_analysis.get("overall_trend", "mixed")

    # 判断条件
    is_matched = (negative_pct > 30 or trend == "mixed" or trend == "deteriorating")
    confidence = min((negative_pct / 100) * 0.8, 1.0) if is_matched else 0

    return is_matched, confidence


def decision_coldness_evidence(intent_chain, user_profile=None, interaction_logs=None):
    """决策冷淡证据提取"""
    emotion_analysis = intent_chain.analyze_emotional_trajectory()

    evidence = [
        f"对话轮数：{len(intent_chain.chain)}（较长）",
        f"消极情感比例：{emotion_analysis.get('negative_percentage', 0):.1f}%",
        f"情感趋势：{emotion_analysis.get('overall_trend', '未知')}",
        "未检测到明确的购买决策意图"
    ]

    return evidence


def decision_coldness_strategy(intent_chain, user_profile=None, interaction_logs=None):
    """决策冷淡策略"""
    return (
        "主动打破僵局，问用户：'有什么我可以帮你的吗？' 或 '您还有其他疑虑吗？'。"
        "提出新的价值主张或优惠方案（限时优惠、赠品等）。"
        "了解用户的真实障碍，针对性地解决。"
        "如果问题无法解决，坦诚地说出来，而不是强行推进。"
        "做好失单的心理准备，但要礼貌地要求反馈。"
    )


def genuine_price_sensitivity_condition(intent_chain, user_profile=None, interaction_logs=None):
    """真正的价格敏感条件检查"""
    if not user_profile:
        return False, 0

    bargain_freq = user_profile.get('bargain_frequency', 0)
    bargain_agg = user_profile.get('bargain_aggressiveness', 0)
    price_sens = user_profile.get('price_sensitivity', 0.5)

    # 频繁砍价 + 激进砍价 + 高价格敏感
    is_matched = bargain_freq > 0.6 and bargain_agg > 0.5 and price_sens > 0.6
    confidence = min((bargain_freq + bargain_agg + price_sens) / 3, 1.0) if is_matched else 0

    return is_matched, confidence


def genuine_price_sensitivity_evidence(intent_chain, user_profile=None, interaction_logs=None):
    """真正的价格敏感证据提取"""
    evidence = []

    if user_profile:
        bargain_freq = user_profile.get('bargain_frequency', 0)
        bargain_agg = user_profile.get('bargain_aggressiveness', 0)
        price_sens = user_profile.get('price_sensitivity', 0.5)

        evidence.append(f"砍价频率：{bargain_freq:.1%}（高）")
        evidence.append(f"砍价激进度：{bargain_agg:.1%}（高）")
        evidence.append(f"价格敏感度：{price_sens:.1%}（高）")
        evidence.append("这是真实的价格敏感，而非虚假砍价或心理寻求")

    return evidence


def genuine_price_sensitivity_strategy(intent_chain, user_profile=None, interaction_logs=None):
    """真正的价格敏感策略"""
    return (
        "给予实质性的价格优惠和灵活性。"
        "考虑分期付款、优惠券、包邮等价格相关方案。"
        "突出商品的性价比，而不是品质或品牌。"
        "快速直接地回答价格问题，不要拖沓。"
        "可以说：'我理解您关注价格，这个商品确实性价比很高，而且我们还可以...'。"
    )


# ============================================================
# 规则库
# ============================================================

CONFLICT_RULES_LIBRARY = {
    "bargain_paradox": ConflictRule(
        rule_id="bargain_paradox",
        conflict_type="bargain_paradox",
        name="砍价悖论",
        description="多次砍价但幅度小，表明用户需要被认可而不是真正的价格敏感",
        condition_check=bargain_paradox_condition,
        extract_evidence=bargain_paradox_evidence,
        recommended_strategy=bargain_paradox_strategy,
        severity="medium"
    ),

    "quality_anxiety": ConflictRule(
        rule_id="quality_anxiety",
        conflict_type="quality_anxiety",
        name="品质焦虑",
        description="用户从砍价忽然转向品质询问，可能发现了质量问题",
        condition_check=quality_anxiety_condition,
        extract_evidence=quality_anxiety_evidence,
        recommended_strategy=quality_anxiety_strategy,
        severity="high"
    ),

    "time_anxiety": ConflictRule(
        rule_id="time_anxiety",
        conflict_type="time_anxiety",
        name="时间焦虑",
        description="价格品质问题已解决，最后关注发货时间，表示已做出购买决策",
        condition_check=time_anxiety_condition,
        extract_evidence=time_anxiety_evidence,
        recommended_strategy=time_anxiety_strategy,
        severity="medium"
    ),

    "decision_coldness": ConflictRule(
        rule_id="decision_coldness",
        conflict_type="decision_coldness",
        name="决策冷淡",
        description="长时间对话但无明确购买决策，用户需要额外激励",
        condition_check=decision_coldness_condition,
        extract_evidence=decision_coldness_evidence,
        recommended_strategy=decision_coldness_strategy,
        severity="high"
    ),

    "genuine_price_sensitivity": ConflictRule(
        rule_id="genuine_price_sensitivity",
        conflict_type="genuine_price_sensitivity",
        name="真正的价格敏感",
        description="频繁且激进的砍价加上高价格敏感，表示真实的预算限制",
        condition_check=genuine_price_sensitivity_condition,
        extract_evidence=genuine_price_sensitivity_evidence,
        recommended_strategy=genuine_price_sensitivity_strategy,
        severity="medium"
    ),
}


def evaluate_all_rules(
    intent_chain,
    user_profile=None,
    interaction_logs=None
) -> List[Dict]:
    """
    评估所有规则，返回命中的规则列表

    参数:
        intent_chain: 意图链对象
        user_profile: 用户画像（可选）
        interaction_logs: 交互日志（可选）

    返回:
        匹配的规则报告列表
    """
    results = []

    for rule_id, rule in CONFLICT_RULES_LIBRARY.items():
        result = rule.evaluate(intent_chain, user_profile, interaction_logs)
        if result:
            results.append(result)

    # 按置信度降序排列
    results.sort(key=lambda x: x.get('confidence', 0), reverse=True)

    return results


def enable_rule(rule_id: str) -> bool:
    """启用指定规则"""
    if rule_id in CONFLICT_RULES_LIBRARY:
        CONFLICT_RULES_LIBRARY[rule_id].enabled = True
        return True
    return False


def disable_rule(rule_id: str) -> bool:
    """禁用指定规则"""
    if rule_id in CONFLICT_RULES_LIBRARY:
        CONFLICT_RULES_LIBRARY[rule_id].enabled = False
        return True
    return False


def list_rules() -> Dict[str, Dict]:
    """列出所有规则"""
    return {
        rule_id: {
            "name": rule.name,
            "description": rule.description,
            "severity": rule.severity,
            "enabled": rule.enabled
        }
        for rule_id, rule in CONFLICT_RULES_LIBRARY.items()
    }
