# AI 饮食助手

基于大模型的饮食推荐系统，支持本地模型（Ollama/llama.cpp）和云端 API（DeepSeek），根据用户个人信息、天气、季节和二十四节气提供个性化饮食推荐。

---

## 快速启动

### 方式一：一键启动（推荐）

双击 `launcher/启动项目.exe`，启动器会自动：
1. 定位 Python 环境（优先 conda，其次系统 Python）
2. 安装缺失依赖
3. 启动 Web 服务
4. 打开浏览器 `http://localhost:8080`

### 方式二：命令行启动

```bash
PYTHONUTF8=1 python server/run_server.py
```

浏览器访问 `http://localhost:8080`

---

## 配置

### 首次使用设置

启动后浏览器会自动打开配置向导，需要配置：

| 配置项 | 说明 | 获取方式 |
|--------|------|---------|
| API Key | 模型调用的密钥 | [DeepSeek 开放平台](https://platform.deepseek.com/) |
| 天气 AK | 百度天气 API 密钥 | [百度地图开放平台](https://lbsyun.baidu.com/) |

### API Key 安全性

V0.3 版本起，API Key 不再存储在 `Config.json` 中，而是存入**系统环境变量**：
- `AI_DIET_PRIMARY_API_KEY` — 一级模型 Key
- `AI_DIET_SECONDARY_API_KEY` — 二级模型 Key
- `AI_DIET_WEATHER_AK` — 天气 API Key

配置一次后重启仍有效，`Config.json` 中仅保留非敏感配置项。

### 模型配置

支持三种模型后端：

| 后端 | 模型 ID 格式 | 说明 |
|------|-------------|------|
| **Ollama** | `ollama:模型名` | 本地运行，需安装 [Ollama](https://ollama.com/) |
| **DeepSeek API** | `deepseek:模型名` | 云端 API，需配置 Key |
| **llama.cpp** | `llamacpp:` | 本地运行，需启动 llama-server |

---

## V0.3 更新内容

相较于 V0.2，本次更新对项目架构进行了全面重整：

### 架构重构
- **模块拆分**：`nutrition_kb.py`（1878 行）拆分为 5 个独立子模块，每模块职责单一
- **Provider 抽象**：统一 Ollama/DeepSeek/llama.cpp 调用接口，新增模型只需实现基类
- **后端统一**：使用 Python/Flask 作为唯一后端，原 C++ 后端已标记 deprecated
- **前端模块化**：`script.js`（1361 行）拆分为 8 个 ES Module，状态管理集中化

### 安全增强
- **密钥隐性存储**：API Key 存入系统环境变量，Config.json 不再存明文
- **输入净化**：新增 prompt injection 过滤
- **日志脱敏**：日志中自动隐藏年龄、身高体重等隐私信息
- **统一隐私层**：所有隐私模糊逻辑集中在 `privacy.py`，消除重复

### 知识库改进
- **节气自动识别**：根据系统日期自动判断当前节气（太阳历，非农历）
- **XLS 跨平台解析**：新增 `xlrd` 后备方案，不再依赖 Windows Excel
- **数据外置**：食谱数据从代码中提取为 `data/recipes.json`

### 质量保障
- 新增 **21 个单元测试**覆盖隐私模糊、Provider 注册、模块导入
- 代码总行数减少约 1000 行，可维护性显著提升

---

## 免责声明

本项目仅供学习、研究目的使用。

**禁止任何形式的商业用途**，包括但不限于：
- 将本项目或修改后的版本用于收费服务、商业产品
- 以盈利为目的分发、托管或提供本项目的衍生作品

本项目按"现状"提供，不提供任何担保，作者不对使用后果承担任何责任。
