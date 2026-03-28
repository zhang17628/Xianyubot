import os
import re

from core.memory.context_manager import ChatContextManager


def import_items_from_txt(filepath="item_info.txt"):
    # 检查文件是否存在
    if not os.path.exists(filepath):
        print(f"错误：找不到文件 {filepath}")
        return

    # 初始化你的数据库管家
    manager = ChatContextManager()

    items_parsed = 0
    current_item_id = None
    current_item_data = {}
    current_desc_lines = []

    def save_current_item():
        """内部辅助函数：将当前暂存的商品信息写入数据库"""
        nonlocal items_parsed
        if current_item_id and current_item_data:
            # 将收集到的所有描述行合并成一段完整的文本，喂给大模型
            current_item_data['desc'] = "\n".join(current_desc_lines)
            # 保存到数据库
            manager.save_item_info(current_item_id, current_item_data)
            print(f"✅ 成功导入: [{current_item_id}] {current_item_data.get('title', '未知名称')}")
            items_parsed += 1


    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()


            if not line:
                if current_item_id:
                    save_current_item()

                    current_item_id = None
                    current_item_data = {}
                    current_desc_lines = []
                continue


            parts = re.split(r'[:：]', line, maxsplit=1)

            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()

                if key.lower() == '物品id':
                    # 如果之前没空行直接连续写了下一个物品的ID，也强制保存上一个
                    if current_item_id:
                        save_current_item()
                        current_item_data = {}
                        current_desc_lines = []
                    current_item_id = value

                elif key == '物品名称':
                    current_item_data['title'] = value
                    current_desc_lines.append(line)  # 也加入到描述中给LLM看

                elif key == '价格':
                    try:
                        current_item_data['soldPrice'] = float(value)
                    except ValueError:
                        current_item_data['soldPrice'] = value
                    current_desc_lines.append(line)

                else:

                    current_desc_lines.append(line)
            else:

                current_desc_lines.append(line)


    if current_item_id:
        save_current_item()

    print(f"\n🎉 导入完成！共将 {items_parsed} 个商品的信息预热进了本地数据库。")


if __name__ == "__main__":
    import_items_from_txt("item_info.txt")
