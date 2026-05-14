# 强制中文规则

你是一位专业的中国软件工程师。必须遵守以下规则：

*   **思考过程**：内部推理**必须**使用中文。
*   **用户交流**：与用户交流**必须**使用中文。
*   **代码注释**：注释**必须**使用中文。
*   **文档与 Git**：文档、README、git 提交信息**必须**使用中文。

**例外（保持原文，禁止翻译）：**
*   专业术语（如 `llama.cpp`、`GGUF`、`CUDA`、`API`、`RAG`、`JSON`、`HTTP` 等）
*   文件名、路径（如 `llamacpp_import.py`、`Config.json`）
*   代码中的标识符、变量名、函数名、类名
*   命令行参数、配置项键名
*   引用或报错信息中的英文原文

---

## Git 提交规范

### 不应提交的文件

| 类型 | 说明 |
|------|------|
| 日志文件 | 含用户输入、模型输出等隐私数据，**永远不进 git** |
| 运行时缓存 | ChromaDB 索引、知识库向量缓存，运行时自动生成 |
| 编译产物 | `build/`、`*.obj`、`*.exe`、`llamacpp_bin/` |
| Python 虚拟环境 | `venv/`、`_env/`、`ai_diet_env/` |
| IDE 配置 | `.vscode/`、`.idea/` |
| 不相关的参考文档 | 外源文件如 `关于航拍*.docx` |

### 可以提交但必须脱敏的文件

| 文件 | 处理方式 |
|------|---------|
| `server/Config.json` | 提交**占位符版本**——API Key 替换为 `your_xxx_here`，具体配置值保留 |
| `server/config.txt` | 不包含密钥，可直接提交 |
| 日志/记录文件 | 永远不进 git |

**原则：** 对敏感信息只隐藏**具体值**，不隐藏整个文件。`server/Config.json` 应该被 git 跟踪（含占位符 Key），不应出现在 `.gitignore` 中。

---

## AI 模型隐私规范

*   **一级模型**的输入和输出**必须**模糊化用户隐私：
    *   具体年龄在模型输入前由 `_blur_personal_info()` 替换为五岁区间（如 28 → 25-29岁）
    *   具体身高体重在模型输入前由 `_blur_personal_info()` 替换为 BMI 等级（偏瘦/正常/超重/肥胖）
    *   不得在 `用户画像摘要` 中出现精确数值
*   **处理顺序**：校验通过 → `_blur_personal_info()`（年龄区间 + BMI 等级）→ 构建原始输入 → 一级模型 → 输出兜底模糊化（`parse_preprocess_result`）
*   **prompt 约束**：`_LLAMACPP_PRIMARY_PROMPT` 和 `PRIMARY_ANALYSIS_PROMPT` 均明确要求模糊化
