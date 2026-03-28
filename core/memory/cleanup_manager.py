"""
长期记忆清理管理器

负责定期清理过期或低价值的对话记录，维持数据量在50-100万条范围内
"""

import sqlite3
import json
from datetime import datetime, timedelta
from loguru import logger


class LongTermMemoryCleanupManager:
    """长期记忆清理管理器"""

    def __init__(self, db_path="data/chat_history.db"):
        self.db_path = db_path

        # 参数配置
        self.SHORT_TERM_LIMIT_PER_USER = 200  # 每个用户保留最近200条（L1）
        self.MID_TERM_DAYS = 30  # 30天内全保留（L2）
        self.LONG_TERM_DAYS = 60  # 30-60天内有选择保留（L3）
        self.DELETE_AFTER_DAYS = 60  # 60天以上全删（L4）

    def cleanup(self) -> dict:
        """
        执行完整的清理操作

        返回:
            清理统计信息
        """
        stats = {
            "deleted_old_conversations": 0,
            "deleted_low_value_conversations": 0,
            "deleted_duplicate_bargains": 0,
            "deleted_excess_per_user": 0,
            "total_deleted": 0,
            "timestamp": datetime.now().isoformat()
        }

        try:
            # 1. 删除 60 天以上的所有对话
            stats["deleted_old_conversations"] = self._cleanup_old_conversations()

            # 2. 删除 30-60 天窗口内的低价值对话
            stats["deleted_low_value_conversations"] = self._cleanup_low_value_conversations()

            # 3. 删除重复的砍价对话（保留最近5条）
            stats["deleted_duplicate_bargains"] = self._cleanup_duplicate_bargains()

            # 4. 删除每个用户超过200条的最老对话
            stats["deleted_excess_per_user"] = self._cleanup_excess_per_user()

            stats["total_deleted"] = (
                stats["deleted_old_conversations"] +
                stats["deleted_low_value_conversations"] +
                stats["deleted_duplicate_bargains"] +
                stats["deleted_excess_per_user"]
            )

            logger.info(f"✅ 长期记忆清理完成: 共删除 {stats['total_deleted']} 条对话")
            return stats

        except Exception as e:
            logger.error(f"❌ 长期记忆清理失败: {e}")
            return stats

    def _cleanup_old_conversations(self) -> int:
        """删除 60 天以上的所有对话"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff_time = (datetime.now() - timedelta(days=self.DELETE_AFTER_DAYS)).isoformat()

            # 删除消息表中的旧对话
            cursor.execute("""
                DELETE FROM messages
                WHERE timestamp < ?
            """, (cutoff_time,))

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted_count > 0:
                logger.info(f"🗑️ 删除了 {deleted_count} 条 60+ 天的对话")

            return deleted_count

        except Exception as e:
            logger.error(f"清理旧对话失败: {e}")
            return 0

    def _cleanup_low_value_conversations(self) -> int:
        """删除 30-60 天窗口内的低价值对话"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            mid_cutoff = (datetime.now() - timedelta(days=self.MID_TERM_DAYS)).isoformat()
            long_cutoff = (datetime.now() - timedelta(days=self.LONG_TERM_DAYS)).isoformat()

            # 低价值对话特征
            low_value_contents = [
                "你好", "在吗", "好的", "可以", "行", "没问题",
                "多少钱", "价格", "这个多少", "能便宜吗", "砍价"
            ]

            # 构建WHERE条件：在30-60天窗口内，且内容是低价值的
            condition_parts = []
            for content in low_value_contents:
                condition_parts.append(f"content LIKE '%{content}%'")

            where_clause = f"""
                timestamp >= ? AND timestamp < ? AND
                role = 'user' AND
                ({' OR '.join(condition_parts)})
            """

            cursor.execute(f"""
                DELETE FROM messages
                WHERE {where_clause}
            """, (mid_cutoff, long_cutoff))

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted_count > 0:
                logger.info(f"🗑️ 删除了 {deleted_count} 条 30-60 天窗口的低价值对话")

            return deleted_count

        except Exception as e:
            logger.error(f"清理低价值对话失败: {e}")
            return 0

    def _cleanup_duplicate_bargains(self) -> int:
        """删除重复的砍价对话，每个 chat_id 只保留最近 5 条"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 找出每个chat_id中砍价消息超过5条的情况
            cursor.execute("""
                SELECT chat_id, COUNT(*) as cnt
                FROM messages
                WHERE role = 'user' AND (
                    detected_intent = 'price' OR
                    content LIKE '%砍价%' OR
                    content LIKE '%便宜%'
                )
                GROUP BY chat_id
                HAVING cnt > 5
            """)

            chat_ids_with_excess = cursor.fetchall()
            total_deleted = 0

            for chat_id, _ in chat_ids_with_excess:
                # 获取该chat_id中砍价消息最早的5条之前的消息ID
                cursor.execute("""
                    SELECT id FROM messages
                    WHERE chat_id = ? AND (
                        detected_intent = 'price' OR
                        content LIKE '%砍价%' OR
                        content LIKE '%便宜%'
                    )
                    ORDER BY timestamp DESC
                    LIMIT -1 OFFSET 5
                """, (chat_id,))

                ids_to_delete = [row[0] for row in cursor.fetchall()]

                if ids_to_delete:
                    placeholders = ','.join('?' * len(ids_to_delete))
                    cursor.execute(f"""
                        DELETE FROM messages
                        WHERE id IN ({placeholders})
                    """, ids_to_delete)
                    total_deleted += cursor.rowcount

            conn.commit()
            conn.close()

            if total_deleted > 0:
                logger.info(f"🗑️ 删除了 {total_deleted} 条重复的砍价对话")

            return total_deleted

        except Exception as e:
            logger.error(f"清理重复砍价对话失败: {e}")
            return 0

    def _cleanup_excess_per_user(self) -> int:
        """删除每个用户超过 200 条的最老对话"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 找出消息数超过200的user_id
            cursor.execute("""
                SELECT user_id, COUNT(*) as cnt
                FROM messages
                GROUP BY user_id
                HAVING cnt > ?
            """, (self.SHORT_TERM_LIMIT_PER_USER,))

            users_with_excess = cursor.fetchall()
            total_deleted = 0

            for user_id, _ in users_with_excess:
                # 保留该user最近200条，删除更早的
                cursor.execute("""
                    SELECT id FROM messages
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT -1 OFFSET ?
                """, (user_id, self.SHORT_TERM_LIMIT_PER_USER))

                ids_to_delete = [row[0] for row in cursor.fetchall()]

                if ids_to_delete:
                    placeholders = ','.join('?' * len(ids_to_delete))
                    cursor.execute(f"""
                        DELETE FROM messages
                        WHERE id IN ({placeholders})
                    """, ids_to_delete)
                    total_deleted += cursor.rowcount

            conn.commit()
            conn.close()

            if total_deleted > 0:
                logger.info(f"🗑️ 删除了 {total_deleted} 条超出用户限额的对话")

            return total_deleted

        except Exception as e:
            logger.error(f"清理用户超额对话失败: {e}")
            return 0

    def get_stats(self) -> dict:
        """获取当前数据库统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 总消息数
            cursor.execute("SELECT COUNT(*) FROM messages")
            total_messages = cursor.fetchone()[0]

            # 按时间分布
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) as last_30_days,
                    SUM(CASE WHEN timestamp >= ? AND timestamp < ? THEN 1 ELSE 0 END) as days_30_60,
                    SUM(CASE WHEN timestamp < ? THEN 1 ELSE 0 END) as older_60_days
                FROM messages
            """, (
                (datetime.now() - timedelta(days=30)).isoformat(),
                (datetime.now() - timedelta(days=60)).isoformat(),
                (datetime.now() - timedelta(days=30)).isoformat(),
                (datetime.now() - timedelta(days=60)).isoformat()
            ))

            result = cursor.fetchone()

            # 用户数
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM messages")
            total_users = cursor.fetchone()[0]

            conn.close()

            return {
                "total_messages": total_messages,
                "last_30_days": result[0] or 0,
                "days_30_60": result[1] or 0,
                "older_60_days": result[2] or 0,
                "total_users": total_users,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}
