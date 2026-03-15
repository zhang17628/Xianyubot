import sqlite3
import os
import json

from datetime import  datetime
from  loguru import logger

from xianyu_agent.xianyubot.memory_manager import LongTermMemorySync


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
        logger.info(f"📦 长期记忆(LightRAG)已初始化")
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

    def search_long_term_memory(self, query, chat_id=None, mode="hybrid", top_k=5) -> str:
        """
        从长期记忆中检索相关历史信息

        参数:
            query: 用户当前的问题
            chat_id: 限定会话（可选）
            mode: "naive"/"local"/"global"/"hybrid"
            top_k: 返回数量
        返回:
            检索到的历史信息文本
        """
        try:
            return self.long_term_memory.search_memory(
                query=query, chat_id=chat_id, mode=mode, top_k=top_k
            )
        except Exception as e:
            logger.error(f"长期记忆检索失败: {e}")
            return ""

    def get_enriched_context(self,chat_id,current_message="",use_long_term=True):
        """
                获取融合后的完整上下文（短期记忆 + 长期记忆）

                策略：
                1. 始终获取短期记忆（最近10条）
                2. 如果短期记忆条数 >= short_term_limit，说明可能有更早的重要信息
                   → 触发长期记忆RAG检索，将相关结果作为system提示注入
                3. 如果用户提到了之前聊过的话题，也触发检索

                参数:
                    chat_id: 会话ID
                    current_message: 用户当前发送的消息（用于RAG查询）
                    use_long_term: 是否启用长期记忆

                返回:
                    messages列表，可直接喂给LLM
                """
        short_term = self.get_short_term_context(chat_id)
        if not use_long_term or not current_message:
            return short_term
        need_long_term = False

        actual_msg_count = len([m for m in short_term if m.get("role") in ("user","assistant")])
        if actual_msg_count >= self.short_term_limit:
            need_long_term = True
            logger.info(f"短期记忆已经满了，触发长期记忆检索")

        recall_keywords = [
            "之前", "上次", "以前", "刚才说的", "你说过", "前面", "最开始",
            "还记得", "我们聊过", "历史", "之前聊", "前面说", "一开始"
        ]
        if any(kw in current_message for kw in recall_keywords):
            need_long_term = True
            logger.info(f"检测到关键回忆词")

        if not need_long_term:
            return short_term

        long_term_result = self.search_long_term_memory(
            query=current_message,
            chat_id=chat_id,
            mode="hybrid",
            top_k=5
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

    def get_context_by_chat(self,chat_id:str):
        """获取信息"""
        return self.get_short_term_context(chat_id)

    def get_image_description(self,image_url:str ,context="")->str:
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
            data_json = json.dumps(item_data,ensure_ascii=False)#将“obj”序列化为JSON格式的“str”。
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