"""
用户画像分析器

根据用户的交互日志，计算用户的各个维度特征，生成完整的用户画像
"""

import json
import re
from datetime import datetime
from loguru import logger

from core.memory.keywords import (
    KEYWORDS_MAP, count_keywords_by_category, extract_keywords_from_text
)


class UserProfileAnalyzer:
    """用户画像分析器"""

    def __init__(self, db=None):
        self.db = db
        self.max_price = 100000  # 最高价格参考

    def compute_full_profile(self, user_id, interaction_logs):
        """
        计算用户的完整画像

        参数:
            user_id: 用户ID
            interaction_logs: 用户交互日志列表

        返回:
            完整的用户画像字典
        """
        if not interaction_logs:
            return self._get_default_profile()

        # 分别计算各个维度
        bargain_features = self.analyze_bargain_features(interaction_logs)
        interest_profile = self.analyze_interest_profile(interaction_logs)
        communication_style = self.analyze_communication_style(interaction_logs)
        purchasing_power = self.analyze_purchasing_power(interaction_logs)
        stats = self.calculate_statistics(interaction_logs)

        # 生成用户标签
        user_type = self.classify_user_type(
            bargain_features, interest_profile, communication_style
        )

        # 合并所有结果
        profile = {
            'user_id': user_id,
            **bargain_features,
            **interest_profile,
            **communication_style,
            **purchasing_power,
            'user_type': user_type,
            **stats,
            'profile_updated': datetime.now().isoformat()
        }

        return profile

    def analyze_bargain_features(self, interaction_logs):
        """
        分析砍价特征

        返回:
            {
                'bargain_count': 砍价次数,
                'bargain_frequency': 砍价频率,
                'bargain_aggressiveness': 砍价激进度,
                'bargain_patience': 砍价耐心度
            }
        """
        # 筛选用户消息
        user_messages = [log for log in interaction_logs if log.get('message_role') == 'user']
        total_messages = len(user_messages)

        if total_messages == 0:
            return {
                'bargain_count': 0,
                'bargain_frequency': 0.0,
                'bargain_aggressiveness': 0.0,
                'bargain_patience': 0
            }

        # 统计砍价次数
        bargain_count = sum(1 for log in user_messages if log.get('detected_intent') == 'price')

        # 砍价频率 = 砍价消息数 / 总消息数
        bargain_frequency = min(bargain_count / total_messages if total_messages > 0 else 0, 1.0)

        # 砍价激进度 = 价格关键词频率 * 砍价频率的平方
        price_keyword_count = sum(count_keywords_by_category(log.get('message_text', ''), 'price')
                                 for log in user_messages)
        aggressiveness = min((price_keyword_count / total_messages * bargain_frequency ** 0.5) if total_messages > 0 else 0, 1.0)

        # 砍价耐心度 = 砍价次数的轮数
        # 简化处理：看砍价持续的消息数
        bargain_indices = [i for i, log in enumerate(user_messages) if log.get('detected_intent') == 'price']
        if bargain_indices:
            bargain_patience = len(bargain_indices)  # 砍价轮数
        else:
            bargain_patience = 0

        return {
            'bargain_count': bargain_count,
            'bargain_frequency': round(bargain_frequency, 3),
            'bargain_aggressiveness': round(aggressiveness, 3),
            'bargain_patience': bargain_patience
        }

    def analyze_interest_profile(self, interaction_logs):
        """
        分析用户的关注点

        返回:
            {
                'price_sensitivity': 价格敏感度,
                'quality_focus': 品质关注度,
                'logistics_concern': 物流关注度,
                'time_sensitivity': 时间敏感度,
                'authenticity_focus': 真实性关注
            }
        """
        user_messages = [log for log in interaction_logs if log.get('message_role') == 'user']
        total_messages = len(user_messages)

        if total_messages == 0:
            return {
                'price_sensitivity': 0.5,
                'quality_focus': 0.5,
                'logistics_concern': 0.5,
                'time_sensitivity': 0.5,
                'authenticity_focus': 0.5
            }

        # 统计各类别关键词频次
        total_text = ' '.join([log.get('message_text', '') for log in user_messages])

        price_count = count_keywords_by_category(total_text, 'price')
        quality_count = count_keywords_by_category(total_text, 'quality')
        logistics_count = count_keywords_by_category(total_text, 'logistics')
        time_count = count_keywords_by_category(total_text, 'time_sensitivity')
        authenticity_count = count_keywords_by_category(total_text, 'authenticity')

        # 计算敏感度（0-1）
        max_count = max(price_count, quality_count, logistics_count, time_count, authenticity_count, 1)

        return {
            'price_sensitivity': round(min(price_count / (max_count * 1.5), 1.0) if max_count > 0 else 0.5, 3),
            'quality_focus': round(min(quality_count / (max_count * 1.5), 1.0) if max_count > 0 else 0.5, 3),
            'logistics_concern': round(min(logistics_count / (max_count * 1.5), 1.0) if max_count > 0 else 0.5, 3),
            'time_sensitivity': round(min(time_count / (max_count * 1.5), 1.0) if max_count > 0 else 0.5, 3),
            'authenticity_focus': round(min(authenticity_count / (max_count * 1.5), 1.0) if max_count > 0 else 0.5, 3)
        }

    def analyze_communication_style(self, interaction_logs):
        """
        分析沟通风格

        返回:
            {
                'politeness_level': 礼貌度,
                'directness_level': 直接度,
                'patience_level': 耐心度,
                'emotionality_level': 情感表达度
            }
        """
        user_messages = [log for log in interaction_logs if log.get('message_role') == 'user']
        total_messages = len(user_messages)

        if total_messages == 0:
            return {
                'politeness_level': 0.5,
                'directness_level': 0.5,
                'patience_level': 0.5,
                'emotionality_level': 0.5
            }

        all_text = ' '.join([log.get('message_text', '') for log in user_messages])

        # 礼貌度：敬语/谢谢等词汇的频率
        politeness_count = count_keywords_by_category(all_text, 'politeness')
        politeness_level = min(politeness_count / (total_messages * 2), 1.0)

        # 直接度：疑问句 vs 陈述句/命令句的比例
        question_count = sum(1 for msg in user_messages if '?' in msg.get('message_text', '') or '？' in msg.get('message_text', ''))
        directness_level = 1.0 - min(question_count / total_messages, 1.0)

        # 耐心度：对话轮次越多表示耐心越好
        patience_level = min(total_messages / 20, 1.0)  # 20轮对话作为参考

        # 情感表达度：感叹号、表情符号等
        emoticon_count = sum(all_text.count(c) for c in ['！', '!', '😄', '😊', '😍', '🤔', '👍'])
        exclamation_count = all_text.count('！') + all_text.count('!')
        emotionality_level = min((emoticon_count + exclamation_count) / (total_messages * 2), 1.0)

        return {
            'politeness_level': round(politeness_level, 3),
            'directness_level': round(directness_level, 3),
            'patience_level': round(patience_level, 3),
            'emotionality_level': round(emotionality_level, 3)
        }

    def analyze_purchasing_power(self, interaction_logs):
        """
        分析购买力估计

        返回:
            {
                'expected_price_min': 预期价格最小值,
                'expected_price_max': 预期价格最大值,
                'purchase_intent_score': 购买意愿度,
                'decision_speed': 决策速度,
                'budget_flexibility': 预算灵活性
            }
        """
        user_messages = [log for log in interaction_logs if log.get('message_role') == 'user']

        if not user_messages:
            return {
                'expected_price_min': 0.0,
                'expected_price_max': 10000.0,
                'purchase_intent_score': 0.5,
                'decision_speed': 999,
                'budget_flexibility': 0.5
            }

        # 从消息中提取价格信息
        all_text = ' '.join([log.get('message_text', '') for log in user_messages])
        prices = self._extract_prices_from_text(all_text)

        if prices:
            expected_price_min = min(prices) * 0.8  # 预留20%空间
            expected_price_max = max(prices) * 1.2
        else:
            expected_price_min = 0.0
            expected_price_max = 10000.0

        # 购买意愿度 = 咨询轮次比例
        total_messages = len(user_messages)
        purchase_intent_score = min(total_messages / 15, 1.0)  # 15轮作为高意愿的参考

        # 决策速度 = 首次咨询到最后咨询的轮数（越少越快）
        decision_speed = total_messages if total_messages > 0 else 999

        # 预算灵活性：看是否提到砍价以及砍价幅度
        budget_flexibility = 0.5
        if any(log.get('detected_intent') == 'price' for log in user_messages):
            # 有砍价行为，说明预算有灵活性
            bargain_count = sum(1 for log in user_messages if log.get('detected_intent') == 'price')
            budget_flexibility = min(0.5 + bargain_count / 10, 1.0)

        return {
            'expected_price_min': round(max(expected_price_min, 0), 2),
            'expected_price_max': round(expected_price_max, 2),
            'purchase_intent_score': round(purchase_intent_score, 3),
            'decision_speed': decision_speed,
            'budget_flexibility': round(budget_flexibility, 3)
        }

    def classify_user_type(self, bargain_features, interest_profile, communication_style):
        """
        根据各维度特征分类用户类型

        返回:
            用户类型字符串
        """
        bf = bargain_features
        ip = interest_profile

        # 优先级排序：砍价达人 > 品质追求者 > 急速购手 > 慎重型 > 综合型

        if bf['bargain_frequency'] > 0.6 and bf['bargain_aggressiveness'] > 0.5:
            return "砍价达人"
        elif ip['quality_focus'] > 0.6:
            return "品质追求者"
        elif ip['logistics_concern'] > 0.6 or ip['time_sensitivity'] > 0.6:
            return "急速购手"
        elif communication_style['patience_level'] < 0.3:
            return "慎重型"
        else:
            return "综合型"

    def calculate_statistics(self, interaction_logs):
        """
        计算统计数据

        返回:
            {
                'total_chats': 总对话数,
                'total_items': 咨询过的商品数,
                'last_interaction': 最后交互时间,
                'reliability_score': 可信度,
                'repeat_rate': 复购率
            }
        """
        total_chats = len(interaction_logs)

        # 统计不同的商品ID
        item_ids = set()
        for log in interaction_logs:
            if log.get('item_id'):
                item_ids.add(log['item_id'])
        total_items = len(item_ids)

        # 最后交互时间
        last_interaction = None
        if interaction_logs:
            last_interaction = interaction_logs[0].get('timestamp')

        # 可信度分数（基于交互活跃度）
        reliability_score = min(total_chats / 10, 1.0)

        # 复购率（重复询问商品的比例）
        if total_items > 0:
            repeat_rate = 1.0 - (total_items / total_chats) if total_chats > 0 else 0.0
        else:
            repeat_rate = 0.0

        return {
            'total_chats': total_chats,
            'total_items': total_items,
            'last_interaction': last_interaction,
            'reliability_score': round(reliability_score, 3),
            'repeat_rate': round(repeat_rate, 3)
        }

    def _extract_prices_from_text(self, text):
        """从文本中提取价格信息"""
        # 匹配 数字元 或 数字块 的模式
        price_pattern = r'(\d+)(?:元|块|￥|¥)?'
        matches = re.findall(price_pattern, text)

        prices = []
        for match in matches:
            try:
                price = int(match)
                # 过滤掉明显不合理的价格
                if 0 < price < self.max_price:
                    prices.append(price)
            except ValueError:
                pass

        return prices

    def _get_default_profile(self):
        """获取默认的用户画像"""
        return {
            'bargain_count': 0,
            'bargain_frequency': 0.0,
            'bargain_aggressiveness': 0.0,
            'bargain_patience': 0,
            'price_sensitivity': 0.5,
            'quality_focus': 0.5,
            'logistics_concern': 0.5,
            'time_sensitivity': 0.5,
            'authenticity_focus': 0.5,
            'politeness_level': 0.5,
            'directness_level': 0.5,
            'patience_level': 0.5,
            'emotionality_level': 0.5,
            'expected_price_min': 0.0,
            'expected_price_max': 10000.0,
            'purchase_intent_score': 0.5,
            'decision_speed': 999,
            'budget_flexibility': 0.5,
            'user_type': 'unknown',
            'total_chats': 0,
            'total_items': 0,
            'last_interaction': None,
            'reliability_score': 0.5,
            'repeat_rate': 0.0,
            'profile_updated': datetime.now().isoformat()
        }
