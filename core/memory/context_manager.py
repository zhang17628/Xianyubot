import sqlite3
import os
import json

from datetime import  datetime
from  loguru import logger

from core.memory.memory_manager import LongTermMemorySync
from core.memory.cleanup_manager import LongTermMemoryCleanupManager


class ChatContextManager:
    """
    聊天管家
    主要作用为：
    1. 记住谁跟你聊过天
    2. 记住聊了什么
    3. 记住这个人砍了几次价
    """

    def __init__(self,short_term_limit=10,max_history=10,db_path= "data/chat_history.db"):
        self.max_history = max_history
        self.db_path = db_path
        self._init_db()
        self.short_term_limit = short_term_limit
        self.long_term_memory = LongTermMemorySync(working_dir="data/lightrag_memory")
        self.cleanup_manager = LongTermMemoryCleanupManager(db_path=db_path)
        self._cleanup_counter = 0  # 计数器：每100条新消息触发清理
        logger.info(f"📦 长期记忆(LightRAG)已初始化")
        logger.info(f"🗑️ 长期记忆清理管理器已初始化")
    def _init_db(self):
        """看是否有数据库，如果没有就创建一个新的数据库"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        #创建消息列表 存对话
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            chat_id TEXT
            )
            '''
        )
        #兼容性检查 确保有chat_id 字段
        cursor.execute("PRAGMA table_info (messages)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'chat_id' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN chat_id TEXT')

        if 'image_url' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN image_url TEXT')

        #加速查询速度
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_if ON messages (chat_id)')


        cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_bargain_counts(
                chat_id TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    item_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    price REAL,
                    description TEXT,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')

        # 用户画像表
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,

                    -- 砍价特征
                    bargain_count INTEGER DEFAULT 0,
                    bargain_frequency REAL DEFAULT 0.0,
                    bargain_aggressiveness REAL DEFAULT 0.0,
                    bargain_patience INTEGER DEFAULT 0,

                    -- 关注点识别
                    price_sensitivity REAL DEFAULT 0.5,
                    quality_focus REAL DEFAULT 0.5,
                    logistics_concern REAL DEFAULT 0.5,
                    time_sensitivity REAL DEFAULT 0.5,
                    authenticity_focus REAL DEFAULT 0.5,

                    -- 沟通风格
                    politeness_level REAL DEFAULT 0.5,
                    directness_level REAL DEFAULT 0.5,
                    patience_level REAL DEFAULT 0.5,
                    emotionality_level REAL DEFAULT 0.5,

                    -- 购买力评估
                    expected_price_min REAL DEFAULT 0.0,
                    expected_price_max REAL DEFAULT 10000.0,
                    purchase_intent_score REAL DEFAULT 0.5,
                    decision_speed REAL DEFAULT 999,
                    budget_flexibility REAL DEFAULT 0.5,

                    -- 用户标签
                    user_type TEXT DEFAULT 'unknown',
                    reliability_score REAL DEFAULT 0.5,
                    repeat_rate REAL DEFAULT 0.0,

                    -- 统计数据
                    total_chats INTEGER DEFAULT 0,
                    total_items INTEGER DEFAULT 0,
                    last_interaction DATETIME,
                    profile_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')

        # 用户交互日志表
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_interaction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    item_id TEXT,

                    -- 交互特征
                    message_text TEXT,
                    message_role TEXT,
                    keywords TEXT,
                    detected_intent TEXT,

                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')

        # 意图链表
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS intent_chain (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,

                    -- 链的元数据
                    chain_data TEXT NOT NULL,          -- JSON格式的完整意图链数据
                    chain_summary TEXT,                -- 人类可读的链摘要
                    total_intents INTEGER DEFAULT 0,   -- 链中的意图数量
                    unique_intents INTEGER DEFAULT 0,  -- 不同的意图类型数

                    -- 分析结果
                    dominant_intent TEXT,              -- 主要意图
                    intent_switches INTEGER DEFAULT 0, -- 意图切换次数
                    overall_emotion TEXT,              -- 整体情感趋势

                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')

        # 冲突检测表
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS conflict_detection (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,

                    -- 冲突信息
                    conflict_type TEXT NOT NULL,       -- 冲突类型
                    confidence REAL DEFAULT 0.5,       -- 检测置信度
                    surface_intent TEXT,               -- 表面诉求
                    underlying_intent TEXT,            -- 潜在真实需求
                    evidence TEXT,                     -- 证据（JSON列表）
                    recommended_strategy TEXT,         -- 建议策略

                    severity TEXT DEFAULT 'medium',    -- 严重程度：low/medium/high

                    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')

        # 为索引单独创建
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_time ON user_interaction_log (user_id, timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_profiles ON user_profiles (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_intent_chain ON intent_chain (chat_id, user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_conflict_detection ON conflict_detection (chat_id, user_id)')

        conn.commit()
        conn.close()
        logger.info(f"聊天数据已就绪：{self.db_path}")

    def add_message_by_chat(self, chat_id, user_id, item_id, role, content,
                            image_url=None,image_desc=None,item_info=None):
        """
               存一条新信息
               同时写入：
               1. SQLite（短期记忆，保留max_history条）
               2. LightRAG（长期记忆，永久保存，语义可检索）

               参数:
                   image_desc: 图片的文字描述（由LLM生成）
                   item_info: 商品信息dict（可选，丰富长期记忆上下文）
               """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO messages (user_id, item_id, role, content, timestamp, chat_id, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                           (user_id, item_id, role, content, datetime.now().isoformat(), chat_id, image_url))
            cursor.execute(
                '''SELECT id FROM messages WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?,1''',
                (chat_id, self.max_history))
            oldest_to_keep = cursor.fetchone()
            if oldest_to_keep:
                cursor.execute("DELETE FROM messages WHERE chat_id = ? AND id < ?",
                               (chat_id, oldest_to_keep[0]))
            conn.commit()

            # 触发清理检查：每100条新消息执行一次清理
            self._cleanup_counter += 1
            if self._cleanup_counter >= 100:
                self._trigger_cleanup()
                self._cleanup_counter = 0

        except Exception as e:
            logger.error(f"存消息出错：{e}")
        finally:
            conn.close()
        #写入长期记忆
        try:
            self.long_term_memory.add_conversation(
                chat_id=chat_id,
                user_id=user_id,
                item_id=item_id,
                role=role,
                content=content,
                image_description=image_desc,
                item_info=item_info
            )
        except Exception as e:
            # 长期记忆写入失败不影响主流程
            logger.warning(f"⚠️ 长期记忆写入失败（不影响主流程）: {e}")

        # 新增：只在用户消息时记录交互日志
        if role == 'user':
            try:
                # 提取关键词（简单实现）
                from core.memory.keywords import extract_keywords_from_text
                keywords, categories = extract_keywords_from_text(content)
                self.log_user_interaction(
                    user_id=user_id,
                    chat_id=chat_id,
                    item_id=item_id,
                    message_text=content,
                    message_role=role,
                    detected_intent=None,  # 由handler传入
                    keywords=keywords
                )
            except Exception as e:
                logger.warning(f"⚠️ 记录交互日志失败: {e}")

    def _trigger_cleanup(self):
        """触发长期记忆清理"""
        try:
            logger.info("🧹 触发长期记忆清理...")
            stats = self.cleanup_manager.cleanup()
            logger.info(f"✅ 清理完成: {stats['total_deleted']} 条对话被删除")
        except Exception as e:
            logger.error(f"❌ 清理过程出错: {e}")

    def get_memory_stats(self) -> dict:
        """获取长期记忆统计信息"""
        try:
            return self.cleanup_manager.get_stats()
        except Exception as e:
            logger.error(f"获取内存统计失败: {e}")
            return {}

    def manual_cleanup(self) -> dict:
        """手动触发清理"""
        logger.info("📋 开始手动清理...")
        return self.cleanup_manager.cleanup()

    def get_short_term_context(self, chat_id):
        """
        获取短期记忆（最近N条对话）
        这是喂给LLM的主要上下文
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        messages = []
        try:
            cursor.execute("PRAGMA table_info(messgae)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'image_url' in columns:
                cursor.execute(
                    """SELECT role, content, image_url FROM messages
                    WHERE chat_id = ?
                    ORDER BY timestamp DESC LIMIT ?""",
                    (chat_id, self.short_term_limit))
                rows = cursor.fetchall()
                rows.reverse()
                for row in rows:
                    role = row[0]
                    content = row[1]
                    image_url = row[2]
                    if image_url:
                        messages.append({
                            "role":role,
                            "content":[
                                {"type":"text","text":content if content else "[发送了一张图片]"},
                                {"type":"image_url","image_url":{"url":image_url}}
                            ]
                        })
                    else:
                        messages.append({"role":role,"content":content})
            else:
                cursor.execute("""
                SELECT role, content FROM messages
                WHERE chat_id = ?
                ORDER BY timestamp DESC LIMIT?
                """,
                (chat_id,self.short_term_limit))
                rows = cursor.fetchall()
                rows.reverse()
                for row in rows:
                    messages.append({"role":row[0],"content":row[1]})
                bargin_count = self.get_bargain_count_by_chat(chat_id)
                if bargin_count > 0:
                    messages.append({"role":"system",
                                     "content":f"系统提示，该用户砍价次数{bargin_count}"})
        except Exception as e:
            logger.error(f"短期记忆获取出错{e}")
        finally:
            conn.close()
        return  messages

    def search_long_term_memory(self, query, chat_id=None, mode="hybrid", top_k=5, use_reranker=True) -> str:
        """
        从长期记忆中检索相关历史信息

        参数:
            query: 用户当前的问题
            chat_id: 限定会话（可选）
            mode: "naive"/"local"/"global"/"hybrid"
            top_k: 返回数量
            use_reranker: 是否使用reranker重排序结果
        返回:
            检索到的历史信息文本
        """
        try:
            return self.long_term_memory.search_memory(
                query=query, chat_id=chat_id, mode=mode, top_k=top_k, use_reranker=use_reranker
            )
        except Exception as e:
            logger.error(f"长期记忆检索失败: {e}")
            return ""

    def get_enriched_context(self,chat_id,current_message="",use_long_term=True):
        """
        获取融合后的完整上下文（短期记忆 + 长期记忆）

        新策略：智能激活长期记忆，避免不必要的RAG检索
        1. 优先检查是否是招呼语 → 不激活
        2. 检查商品变化 → 不激活
        3. 检查关键词 → 激活
        4. 检查消息间隔 → 激活

        参数:
            chat_id: 会话ID
            current_message: 用户当前发送的消息（用于激活判断）
            use_long_term: 是否启用长期记忆
        """
        short_term = self.get_short_term_context(chat_id)

        if not use_long_term or not current_message:
            return short_term

        need_long_term = False

        # ===== 第一优先级：招呼语检测 =====
        if self._is_greeting(current_message):
            logger.debug(f"检测到招呼语，不激活长期记忆")
            return short_term

        # ===== 第二优先级：商品变化检测 =====
        if not self._should_activate_by_product_change(chat_id):
            # 商品变了，不需要历史
            logger.debug(f"商品已变化，不激活长期记忆")
            return short_term

        # ===== 第三优先级：关键词检测 =====
        if self._has_history_keywords(current_message):
            need_long_term = True
            logger.info(f"检测到历史相关关键词，激活长期记忆")

        # ===== 第四优先级：消息间隔检测 =====
        if not need_long_term and self._check_message_interval(chat_id):
            need_long_term = True
            logger.info(f"消息间隔过长，激活长期记忆")

        if not need_long_term:
            return short_term

        # 执行长期记忆检索（使用reranker提高相关性）
        long_term_result = self.search_long_term_memory(
            query=current_message,
            chat_id=chat_id,
            mode="hybrid",
            top_k=5,
            use_reranker=True  # 启用reranker重排序
        )

        if not long_term_result or not long_term_result.strip():
            return short_term

        long_term_system_msg  = {
            "role":"system",
            "content":(
                f"以下是与该用户的历史对话摘要（从长期记忆中检索）：\n"
                f"---\n"
                f"{long_term_result}\n"
                f"---\n"
                f"请参考以上历史信息来回答用户的问题。如果历史信息与当前问题无关，可以忽略。"
            )
        }

        enriched = [long_term_system_msg] + short_term
        logger.info("获取到融合长期和短期记忆的信息")
        return enriched

    def _is_greeting(self, message: str) -> bool:
        """
        检测是否是纯招呼语或简单确认

        参数:
            message: 用户消息

        返回:
            True 如果是招呼语，False 否则
        """
        if not message:
            return False

        # 清理消息：去掉标点符号，转小写
        cleaned = message.strip().lower()
        # 去掉常见标点
        for char in ['，', '。', '！', '？', ',', '.', '!', '?', '~', '～']:
            cleaned = cleaned.replace(char, '')
        cleaned = cleaned.strip()

        # 招呼类关键词
        greeting_keywords = [
            '你好', 'hi', 'hello', '嗨', '怎么样', '在吗', '在不在', '在干嘛',
            '你在吗', '还在吗', '醒了吗'
        ]

        # 简单确认
        confirm_keywords = [
            '好', '好的', '可以', '行', 'ok', '对', '是的', '是', '嗯',
            '确定', '没问题', '没事'
        ]

        # 简单否定
        deny_keywords = [
            '不', '不行', '不要', 'no', '不对', '没有', '没',
            '算了', '别了'
        ]

        all_keywords = greeting_keywords + confirm_keywords + deny_keywords

        # 如果消息完全匹配任一关键词，认为是招呼语
        if cleaned in all_keywords:
            return True

        # 如果消息很短且完全由关键词组成（允许一些变化）
        if len(cleaned) <= 10:
            # 检查是否大部分是关键词
            for keyword in all_keywords:
                if keyword in cleaned and len(cleaned) - len(keyword) <= 2:
                    return True

        return False

    def _should_activate_by_product_change(self, chat_id: str) -> bool:
        """
        检查商品是否变化了

        参数:
            chat_id: 会话ID

        返回:
            True 如果商品未变化（继续判断），False 如果商品变化了（不激活）
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 获取最后两条消息
            cursor.execute("""
                SELECT item_id FROM messages
                WHERE chat_id = ? AND item_id IS NOT NULL AND item_id != '0'
                ORDER BY timestamp DESC LIMIT 2
            """, (chat_id,))

            results = cursor.fetchall()
            conn.close()

            if len(results) < 2:
                # 消息太少，继续判断其他维度
                return True

            # 获取最后一条和倒数第二条的item_id
            current_item_id = results[0][0] if results else None
            previous_item_id = results[1][0] if len(results) > 1 else None

            if current_item_id != previous_item_id:
                # 商品变化了
                logger.debug(f"商品变化: {previous_item_id} → {current_item_id}")
                return False  # 商品变化，不激活长期记忆

            return True  # 商品未变化，继续判断

        except Exception as e:
            logger.error(f"检查商品变化失败: {e}")
            return True  # 出错时，继续判断其他维度

    def _has_history_keywords(self, message: str) -> bool:
        """
        检测消息中是否包含需要激活长期记忆的关键词

        参数:
            message: 用户消息

        返回:
            True 如果包含相关关键词，False 否则
        """
        if not message:
            return False

        message_lower = message.lower()

        # 【历史回忆词】
        history_keywords = [
            '之前', '上次', '那个', '还记得', '你说过', '前面', '刚才',
            '之前提到', '之前聊', '前面说', '之前说', '记得吗', '还有吗',
            '之前那'
        ]

        # 【否定/批评词】
        criticism_keywords = [
            '不对', '有问题', '不满意', '不好', '坏了', '破了', '有缺陷',
            '有损伤', '有划痕', '褪色', '掉漆', '不新', '旧', '磨损',
            '怎么', '这样', '这么', '这个样子'
        ]

        # 【价格对比词】
        comparison_keywords = [
            '太贵', '能不能便宜', '能便宜吗', '便宜点', '给个优惠',
            '便宜', '比...便宜', '划不划算', '贵不贵', '值不值'
        ]

        all_keywords = history_keywords + criticism_keywords + comparison_keywords

        # 检查是否包含任何关键词
        for keyword in all_keywords:
            if keyword in message_lower:
                logger.debug(f"检测到关键词: {keyword}")
                return True

        return False

    def _check_message_interval(self, chat_id: str, interval_minutes: int = 30) -> bool:
        """
        检查消息间隔是否超过指定时间

        参数:
            chat_id: 会话ID
            interval_minutes: 时间间隔（分钟），默认30分钟

        返回:
            True 如果间隔超过指定时间，False 否则
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 获取最后一条消息的时间
            cursor.execute("""
                SELECT timestamp FROM messages
                WHERE chat_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (chat_id,))

            result = cursor.fetchone()
            conn.close()

            if not result:
                return False

            last_timestamp_str = result[0]

            # 解析时间戳
            try:
                from datetime import datetime
                last_timestamp = datetime.fromisoformat(last_timestamp_str.replace('Z', '+00:00'))
                current_time = datetime.now()

                time_diff = (current_time - last_timestamp).total_seconds() / 60  # 转换为分钟

                if time_diff > interval_minutes:
                    logger.debug(f"消息间隔: {time_diff:.1f}分钟 > {interval_minutes}分钟，激活长期记忆")
                    return True

            except Exception as e:
                logger.warning(f"解析时间戳失败: {e}")
                return False

            return False

        except Exception as e:
            logger.error(f"检查消息间隔失败: {e}")
            return False

    def get_context_by_chat(self,chat_id:str):
        """获取信息"""
        return self.get_short_term_context(chat_id)

    def generate_image_description(self,image_url:str ,context="")->str:
        try:
            return self.long_term_memory.describe_image(image_url, context)
        except Exception as e:
            logger.error(f"生成图片描述失败: {e}")
            return ""

    def save_item_info(self,item_id,item_data):
        """保存商品详情到数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            price = float(item_data.get('soldPrice',0))
            description = item_data.get('desc','')
            data_json = json.dumps(item_data,ensure_ascii=False)#将"obj"序列化为JSON格式的"str"。
            cursor.execute("""
            INSERT INTO items (item_id, data, price, description, last_updated)
            VALUES(?,?,?,?,?)
            ON CONFLICT (item_id)
            DO UPDATE SET data = ?, price =  ?,description = ?, last_updated = ?
            """,
            (item_id, data_json,price, description,datetime.now().isoformat(),
             data_json,price,description,datetime.now().isoformat()
                           ))
            conn.commit()
        except Exception as e:
            logger.error(f"保存商品信息出错{e}")

    def get_item_info(self,item_id):
        """读取商品信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT data FROM items WHERE item_id = ?",(item_id,))
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        finally:
            conn.close()

    def get_latest_item_id_by_chat(self, chat_id):
        """获取该对话中最近一次出现的商品ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # 查找该 chat_id 下，item_id 不是 '0' 且不为空的最新一条记录
            cursor.execute('''
                SELECT item_id FROM messages
                WHERE chat_id = ? AND item_id != '0' AND item_id != ''
                ORDER BY timestamp DESC LIMIT 1
            ''', (chat_id,))
            result = cursor.fetchone()
            return result[0] if result else "0"
        except Exception as e:
            logger.error(f"获取最近商品ID出错：{e}")
            return "0"
        finally:
            conn.close()

    def get_context_by_chat(self, chat_id):
        """获取对话上下文（支持图片多模态格式）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        messages = []
        try:
            # 兼容性检查：确保本次查询包含 image_url
            cursor.execute("PRAGMA table_info(messages)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'image_url' in columns:

                cursor.execute(
                    "SELECT role, content, image_url FROM messages WHERE chat_id = ? ORDER BY timestamp ASC LIMIT ?",
                    (chat_id, self.max_history))
                rows = cursor.fetchall()
                for row in rows:
                    role = row[0]
                    content = row[1]
                    image_url = row[2]

                    if image_url:
                        # 组装给大模型看的多模态格式
                        messages.append({
                            "role": role,
                            "content": [
                                {"type": "text", "text": content if content else "[发送了一张图片]"},
                                {"type": "image_url", "image_url": {"url": image_url}}
                            ]
                        })
                    else:
                        messages.append({"role": role, "content": content})
            else:
                # 兜底：如果数据库还没更新字段，只查 2 个字段
                cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp ASC LIMIT ?",
                               (chat_id, self.max_history))
                rows = cursor.fetchall()
                for row in rows:
                    messages.append({"role": row[0], "content": row[1]})

            # 处理议价次数
            bargin_count = self.get_bargain_count_by_chat(chat_id)
            if bargin_count > 0:
                messages.append({
                    "role": "system",
                    "content": f"系统提示：该用户历史议价次数：{bargin_count}次"
                })
        except Exception as e:
            logger.error(f"读取历史出错：{e}")
        finally:
            conn.close()
        return messages

    def increment_bargain_count_by_chat(self,chat_id):
        "议价次数+1"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
            INSERT INTO chat_bargain_counts (chat_id, count, last_updated)
            VALUES(?,1,?)
            ON CONFLICT(chat_id)
            DO UPDATE SET count = count + 1, last_updated = ?""",
                        (chat_id,datetime.now().isoformat(),datetime.now().isoformat()))
            conn.commit()
        except Exception as e:
            logger.error(f"更新议价次数出错：{e}")
        finally:
            conn.close()
    def get_bargain_count_by_chat(self,chat_id):
        """查议价次数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT count FROM chat_bargain_counts WHERE chat_id = ?",
                           (chat_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
        finally:
            conn.close()

    # ========== 用户画像管理方法 ==========

    def log_user_interaction(self, user_id, chat_id, item_id, message_text, message_role,
                            detected_intent=None, keywords=None):
        """
        记录用户交互日志

        参数:
            user_id: 用户ID
            chat_id: 会话ID
            item_id: 商品ID
            message_text: 消息文本
            message_role: 消息角色 ('user' 或 'assistant')
            detected_intent: 检测到的意图 ('price', 'quality', 'logistics' 等)
            keywords: 提取的关键词列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # 将关键词列表转换为JSON字符串
            keywords_json = json.dumps(keywords) if keywords else None

            cursor.execute("""
                INSERT INTO user_interaction_log
                (user_id, chat_id, item_id, message_text, message_role, keywords, detected_intent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, chat_id, item_id, message_text, message_role, keywords_json,
                  detected_intent, datetime.now().isoformat()))
            conn.commit()
            logger.debug(f"交互日志已记录: user_id={user_id}, intent={detected_intent}")
        except Exception as e:
            logger.error(f"记录交互日志失败: {e}")
        finally:
            conn.close()

    def get_user_profile(self, user_id):
        """
        获取用户画像

        参数:
            user_id: 用户ID

        返回:
            用户画像字典，如果用户不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM user_profiles WHERE user_id = ?
            """, (user_id,))

            result = cursor.fetchone()
            if not result:
                return None

            # 获取列名
            cursor.execute("PRAGMA table_info(user_profiles)")
            columns = [col[1] for col in cursor.fetchall()]

            # 将结果转换为字典
            profile = dict(zip(columns, result))
            return profile
        except Exception as e:
            logger.error(f"获取用户画像失败: {e}")
            return None
        finally:
            conn.close()

    def update_user_profile(self, user_id, profile_data):
        """
        更新或创建用户画像

        参数:
            user_id: 用户ID
            profile_data: 画像数据字典
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # 先检查用户是否存在
            cursor.execute("SELECT user_id FROM user_profiles WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone() is not None

            if exists:
                # 更新现有用户
                # 动态构建UPDATE语句
                update_fields = []
                values = []
                for key, value in profile_data.items():
                    if key != 'user_id':
                        update_fields.append(f"{key} = ?")
                        values.append(value)

                update_fields.append("profile_updated = ?")
                values.append(datetime.now().isoformat())
                values.append(user_id)

                update_sql = f"""
                    UPDATE user_profiles
                    SET {', '.join(update_fields)}
                    WHERE user_id = ?
                """
                cursor.execute(update_sql, values)
            else:
                # 创建新用户画像
                profile_data['user_id'] = user_id
                profile_data['profile_updated'] = datetime.now().isoformat()

                columns = ', '.join(profile_data.keys())
                placeholders = ', '.join(['?' for _ in profile_data])
                insert_sql = f"""
                    INSERT INTO user_profiles ({columns})
                    VALUES ({placeholders})
                """
                cursor.execute(insert_sql, list(profile_data.values()))

            conn.commit()
            logger.debug(f"用户画像已更新: user_id={user_id}")
        except Exception as e:
            logger.error(f"更新用户画像失败: {e}")
        finally:
            conn.close()

    def get_user_interaction_log(self, user_id, limit=100):
        """
        获取用户的交互日志

        参数:
            user_id: 用户ID
            limit: 返回的最大记录数

        返回:
            交互日志列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM user_interaction_log
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))

            rows = cursor.fetchall()

            # 获取列名
            cursor.execute("PRAGMA table_info(user_interaction_log)")
            columns = [col[1] for col in cursor.fetchall()]

            # 转换为字典列表
            logs = []
            for row in rows:
                log_dict = dict(zip(columns, row))
                # 解析JSON格式的keywords
                if log_dict['keywords']:
                    try:
                        log_dict['keywords'] = json.loads(log_dict['keywords'])
                    except:
                        pass
                logs.append(log_dict)

            return logs
        except Exception as e:
            logger.error(f"获取交互日志失败: {e}")
            return []
        finally:
            conn.close()

    def init_user_profile(self, user_id):
        """
        初始化用户画像（如果不存在）

        参数:
            user_id: 用户ID
        """
        profile = self.get_user_profile(user_id)
        if profile is None:
            default_profile = {
                'user_id': user_id,
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
                'reliability_score': 0.5,
                'repeat_rate': 0.0,
                'total_chats': 0,
                'total_items': 0,
                'profile_updated': datetime.now().isoformat()
            }
            self.update_user_profile(user_id, default_profile)
            logger.info(f"为用户 {user_id} 初始化了画像")

    # ========== 意图链管理方法 ==========

    def save_intent_chain(self, chat_id, user_id, intent_chain_obj):
        """
        保存意图链到数据库

        参数:
            chat_id: 会话ID
            user_id: 用户ID
            intent_chain_obj: IntentChain对象（从intent_chain_analyzer模块）
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            chain_data = intent_chain_obj.to_dict()
            chain_data_json = json.dumps(chain_data, ensure_ascii=False)

            # 获取分析结果
            patterns = intent_chain_obj.detect_intent_pattern()
            emotion_analysis = intent_chain_obj.analyze_emotional_trajectory()

            cursor.execute("""
                INSERT INTO intent_chain
                (chat_id, user_id, chain_data, chain_summary, total_intents, unique_intents,
                 dominant_intent, intent_switches, overall_emotion, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chat_id,
                user_id,
                chain_data_json,
                intent_chain_obj.generate_chain_summary(),
                patterns.get("total_intents", 0),
                patterns.get("unique_intents", 0),
                patterns.get("dominant_intent"),
                patterns.get("intent_switches", 0),
                emotion_analysis.get("overall_trend"),
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))

            conn.commit()
            logger.debug(f"意图链已保存: chat_id={chat_id}, user_id={user_id}")
        except Exception as e:
            logger.error(f"保存意图链失败: {e}")
        finally:
            conn.close()

    def get_intent_chain(self, chat_id):
        """
        获取会话的意图链

        参数:
            chat_id: 会话ID

        返回:
            意图链字典，包含完整的链数据
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT chain_data, chain_summary, dominant_intent, overall_emotion
                FROM intent_chain
                WHERE chat_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (chat_id,))

            result = cursor.fetchone()
            if not result:
                return None

            chain_data = json.loads(result[0])
            return {
                "chain_data": chain_data,
                "chain_summary": result[1],
                "dominant_intent": result[2],
                "overall_emotion": result[3]
            }
        except Exception as e:
            logger.error(f"获取意图链失败: {e}")
            return None
        finally:
            conn.close()

    # ========== 冲突检测管理方法 ==========

    def save_conflict_detection(self, chat_id, user_id, conflicts_list):
        """
        保存冲突检测结果到数据库

        参数:
            chat_id: 会话ID
            user_id: 用户ID
            conflicts_list: ConflictReport对象列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            for conflict in conflicts_list:
                evidence_json = json.dumps(conflict.evidence, ensure_ascii=False)

                cursor.execute("""
                    INSERT INTO conflict_detection
                    (chat_id, user_id, conflict_type, confidence, surface_intent,
                     underlying_intent, evidence, recommended_strategy, severity, detected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chat_id,
                    user_id,
                    conflict.conflict_type.value,
                    conflict.confidence,
                    conflict.surface_intent,
                    conflict.underlying_intent,
                    evidence_json,
                    conflict.recommended_strategy,
                    getattr(conflict, 'severity', 'medium'),
                    datetime.now().isoformat()
                ))

            conn.commit()
            logger.debug(f"冲突检测结果已保存: chat_id={chat_id}, 检测到{len(conflicts_list)}个冲突")
        except Exception as e:
            logger.error(f"保存冲突检测失败: {e}")
        finally:
            conn.close()

    def get_conflicts(self, chat_id, limit=10):
        """
        获取会话的冲突检测结果

        参数:
            chat_id: 会话ID
            limit: 返回的最大记录数

        返回:
            冲突检测结果列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT conflict_type, confidence, surface_intent, underlying_intent,
                       evidence, recommended_strategy, severity
                FROM conflict_detection
                WHERE chat_id = ?
                ORDER BY detected_at DESC
                LIMIT ?
            """, (chat_id, limit))

            rows = cursor.fetchall()
            conflicts = []

            for row in rows:
                evidence = json.loads(row[4]) if row[4] else []
                conflicts.append({
                    "conflict_type": row[0],
                    "confidence": row[1],
                    "surface_intent": row[2],
                    "underlying_intent": row[3],
                    "evidence": evidence,
                    "recommended_strategy": row[5],
                    "severity": row[6]
                })

            return conflicts
        except Exception as e:
            logger.error(f"获取冲突检测结果失败: {e}")
            return []
        finally:
            conn.close()

    def get_latest_conflicts(self, chat_id):
        """
        获取最近一次的冲突检测结果

        参数:
            chat_id: 会话ID

        返回:
            最新的冲突检测结果列表
        """
        conflicts = self.get_conflicts(chat_id, limit=1)
        return conflicts[0] if conflicts else None
