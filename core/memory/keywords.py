# 关键词映射字典
# 用于识别用户的关注点和沟通特征

KEYWORDS_MAP = {
    'price': {
        'keywords': ['价格', '便宜', '多少钱', '贵了', '能便宜点吗', '划不划算', '优惠',
                    '减价', '打折', '便宜点', '最低', '低价', '降价', '砍价', '议价'],
        'weight': 1.0
    },
    'quality': {
        'keywords': ['成色', '新旧', '使用', '磨损', '品质', '完好', '有无缺陷', '新不新',
                    '磕碰', '划痕', '完美', '崭新', '如新', '轻微', '全新'],
        'weight': 0.9
    },
    'logistics': {
        'keywords': ['发货', '快递', '配送', '物流', '什么时候', '急', '赶紧', '快点',
                    '几天', '几小时', '立即', '今天', '明天', '周几', '何时'],
        'weight': 0.85
    },
    'authenticity': {
        'keywords': ['正品', '真实', '假', '鉴别', '证书', '保障', '防伪', '真不真',
                    '假不假', '官方', '认证', '假货', '副品'],
        'weight': 0.95
    },
    'time_sensitivity': {
        'keywords': ['急', '赶紧', '着急', '今天', '明天', '马上', '立即', '现在',
                    '快点', '时间', '来得及', '能否赶上', '几点'],
        'weight': 0.8
    },
    'politeness': {
        'keywords': ['谢谢', '麻烦您', '请问', '能否', '可以吗', '感谢', '谢了', '谢谢你',
                    '麻烦了', '感谢您', '谢谢您', '多谢', '敬请', '恳请'],
        'weight': 0.7
    },
    'urgency': {
        'keywords': ['急', '赶紧', '着急', '今天', '明天', '马上', '立即', '现在',
                    '快点', '立刻', '火急', '紧急', '时间紧'],
        'weight': 0.8
    },
    'parameter_inquiry': {
        'keywords': ['参数', '配置', '规格', '容量', '型号', '版本', '内存', '屏幕',
                    '摄像头', '电池', '性能', '功能', '怎么样', '怎样', '功能如何'],
        'weight': 0.85
    }
}

# 反向映射：给定关键词，获取类别
KEYWORD_TO_CATEGORY = {}
for category, data in KEYWORDS_MAP.items():
    for keyword in data['keywords']:
        KEYWORD_TO_CATEGORY[keyword] = category

def get_keyword_category(word: str) -> str:
    """
    获取关键词所属的类别

    Args:
        word: 要查询的关键词

    Returns:
        关键词所属的类别，如果不存在返回 None
    """
    return KEYWORD_TO_CATEGORY.get(word)

def extract_keywords_from_text(text: str) -> list:
    """
    从文本中提取关键词

    Args:
        text: 输入文本

    Returns:
        (关键词列表, 类别列表) 的元组
    """
    extracted_keywords = []
    categories = []

    for keyword in KEYWORD_TO_CATEGORY.keys():
        if keyword in text:
            extracted_keywords.append(keyword)
            category = KEYWORD_TO_CATEGORY[keyword]
            if category not in categories:
                categories.append(category)

    return extracted_keywords, categories

def count_keywords_by_category(text: str, category: str) -> int:
    """
    统计文本中特定类别关键词的数量

    Args:
        text: 输入文本
        category: 关键词类别

    Returns:
        该类别关键词的数量
    """
    if category not in KEYWORDS_MAP:
        return 0

    count = 0
    for keyword in KEYWORDS_MAP[category]['keywords']:
        count += text.count(keyword)

    return count

def get_all_keywords(category: str = None) -> list:
    """
    获取所有关键词或特定类别的关键词

    Args:
        category: 关键词类别，如果为 None 返回所有关键词

    Returns:
        关键词列表
    """
    if category and category in KEYWORDS_MAP:
        return KEYWORDS_MAP[category]['keywords']

    all_keywords = []
    for data in KEYWORDS_MAP.values():
        all_keywords.extend(data['keywords'])
    return all_keywords
