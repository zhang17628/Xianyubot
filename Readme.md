# 🐟 Xianyu AI Agent | 闲鱼多模态智能客服机器人

![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![LLM](https://img.shields.io/badge/LLM-OpenAI%20%7C%20Qwen%20%7C%20Local-green)
![RAG](https://img.shields.io/badge/RAG-LightRAG-orange)
![License](https://img.shields.io/badge/License-MIT-brightgreen)

> **⚠️ 免责声明**：本项目是个人学习使用，仅供学习与技术交流使用。请勿用于商业用途或恶意刷单、发广告等违反平台规则的行为。

基于大语言模型 (LLM) 与长短期记忆检索增强生成 (RAG) 构建的全自动闲鱼智能客服机器人。本项目逆向接入了闲鱼底层 WebSocket 接口，支持多模态（文本+图像）交互，并借助LightRAG增加了长期记忆功能，能够存储历史记录当中的文本及图片信息，目前还有许多不足，后续将会不断更新改进。

---

## ✨ 核心特性
- 👁️ **多模态图像理解 (VLM)**：自动抓取并解析买家发送的图片，结合视觉大模型判断图片内容与售卖商品的关联性，实现精准看图回复。
- 🧠 **长短期双轨记忆系统**：
  - **短期记忆 (SQLite)**：极速追踪最近的会话上下文，记录用户的“议价频次”、“防抖/去重”状态，实现丝滑的多轮对话。
  - **长期记忆 (LightRAG + BGE Embedding)**：将会话历史、图片描述与商品详情向量化存储，解决长周期沟通中的“灾难性遗忘”问题。
- 🎯 **多意图精准路由**：通过 LangChain 动态 Prompt 注入，自动识别用户当前意图（如：常规咨询、恶意砍价、技术支持），并自动切换应对策略。
---


## 🚀 快速开始

### 1. 环境准备

本项目需要python3.10+,首先克隆项目并安装依赖库：

```bash
git clone 
cd Xianyubot
pip install -r requirements.txt
```
### 2. 配置文件设置
在项目根目录创建一个 .env 文件，填入你的大模型 API 密钥以及闲鱼网页版抓取到的 Cookie：
```ENV
# 大模型配置 (支持 OpenAI 格式的接口，如 DeepSeek, Qwen 等)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
# 向量模型配置 (可填入你的 Embedding 接口，留空则默认使用本地 BGE 模型)
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
# 闲鱼COOKIES配置 (在闲鱼网页版登录后，按 F12 任选一个.json，查看网络抓取请求头中的 Cookie)
COOKIES_STR="你的闲鱼完整Cookie字符串"
```
 ### 3. 添加你的物品基础信息
```commandline
修改项目根目录下的文件item_info.txt 添加物品id等。从而添加物品的详细信息
物品id可以从手机端分享链接，之后网页端打开id=后字符就为对应的id
https://www.goofish.com/item?id=1028460358996
最后形式如下：
物品id: 1028460358996
物品名称：星巴克优雅粉紫浪漫马克杯
价格：90.06
是否包邮：可以包邮
是否降价：不接受降价
是否全新：全新但无盒子
之后运行,将物品信息添加到数据库
python add_item_info.py
```

### 4. 运行命令
```bash
python main.py
```


## 🙏 致谢 (Acknowledgments)

本项目的顺利诞生离不开开源社区的伟大贡献。特别感谢以下优秀的开源项目为本项目提供了坚实的技术底座：

- 🌟 **[shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent)**
 
本项目在开发初期，关于 **闲鱼底层通信协议逆向**（如 `msgpack` 二进制解码、API 签名伪造、WebSocket 握手与心跳保活逻辑）的核心实现，深度参考了该项目。感谢原作者 [@shaxiu](https://github.com/shaxiu) 提供的扎实逆向工程底座。

- 🌟 **[HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)**
  感谢香港大学数据智能实验室 (HKUDS) 开源的 LightRAG 框架。本项目中的**长短期记忆系统（长期记忆部分）** 核心接入了该框架。

站在巨人的肩膀上，本项目才得以将 **逆向工程通信、多模态视觉处理、图谱RAG记忆** 有机结合在一起。再次向以上项目的开发者表达最诚挚的敬意！

## 🤝 贡献与交流

如果你对大模型 Agent 或逆向工程感兴趣，欢迎提交 Pull Request 或者提出 Issue 探讨！

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

