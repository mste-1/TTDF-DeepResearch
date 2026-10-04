# Deep Research Agent

## 项目简介

本项目基于 LangGraph 和 LangChain 构建多智能体深度研究工作流。用户输入研究问题后，系统生成研究简报和报告初稿，由 Supervisor 拆分研究任务、协调多个 Research Agent 进行网络检索与资料整理，最后汇总研究结果并生成报告。

研究过程中，系统结合 Red Team 质疑、草稿修订和质量评估形成反馈循环，用于发现论证缺口、补充证据并改善报告质量。这里的“自进化”指当前研究任务中的迭代改进，不涉及模型权重训练。

主要流程：

```text
研究问题 → 研究简报 → 报告初稿 → 多智能体研究与反馈迭代 → 最终报告
```

- **模型与搜索**：示例配置使用 DeepSeek 和 Tavily，可通过配置文件设置模型角色、接口地址、超时和搜索参数。
- **运行入口**：[run.ipynb](run.ipynb)，用于加载环境变量、构建研究工作流、发起研究并保存报告。
- **核心实现**：[deep_research/](deep_research/)，包含工作流、智能体、提示词和工具。
- **报告示例**：[results/](results/)。
- **架构图**：[SVG 架构图](docs/architecture/deep-research-architecture.svg) 与 [交互式架构说明](docs/architecture/index.html)。

## 本地 clone 后的配置

仓库只提供配置模板。首次 clone 后，需要在项目根目录手动创建以下两个本地配置文件，并填写自己的配置：

| 仓库中的模板 | 本地配置文件 | 用途 |
| --- | --- | --- |
| `comfig.yml.example` | `config.yml` | 模型服务、搜索服务及各智能体角色配置 |
| `env.example` | `.env` | LangSmith 追踪相关环境变量 |

> 模板文件名为 `comfig.yml.example`；程序默认读取的文件名为 `config.yml`。复制时请使用下方的准确名称。

### 1. 复制配置模板

在项目根目录执行。以下命令适用于首次配置；已有本地配置时直接编辑对应文件，避免覆盖已有内容。

Windows PowerShell：

```powershell
Copy-Item comfig.yml.example config.yml
Copy-Item env.example .env
```

macOS / Linux：

```bash
cp comfig.yml.example config.yml
cp env.example .env
```

### 2. 填写 `config.yml`

将模板中的 API key 占位符替换为自己的真实密钥：

| 配置路径 | 需要填写的内容 |
| --- | --- |
| `stages.prod.cognition.openai.api_key` | DeepSeek API key，替换 `YOUR_DEEPSEEK_API_KEY` |
| `stages.prod.search.tavily.api_key` | Tavily API key，替换 `YOUR_TAVILY_API_KEY` |

`cognition.openai` 是当前配置中的后端名称，其 `base_url` 和 `model_provider` 指向 DeepSeek。请根据实际使用的服务检查接口地址、模型名称、`organization` 和模型参数；更换模型时，同步检查 `default_model`、`models` 下的模型配置以及 `roles` 中各角色的 `handle`。

程序默认读取项目根目录的 `config.yml`，使用 `stages.prod` 配置。也可以通过环境变量 `CONFIG_PATH` 和 `STAGE` 指定其他配置路径与环境。

### 3. 填写 `.env`

如需使用 LangSmith 查看运行追踪，将以下字段替换为自己的配置，去掉模板中的中文占位符和花括号：

```dotenv
LANGCHAIN_TRACING_V2=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=YOUR_LANGSMITH_API_KEY
LANGCHAIN_PROJECT=YOUR_LANGSMITH_PROJECT_NAME
```

如不使用 LangSmith，可将 `LANGCHAIN_TRACING_V2` 设置为 `false`，并删除 `LANGCHAIN_API_KEY` 和 `LANGCHAIN_PROJECT` 两行。模型与搜索服务的 API key 仍需在 `config.yml` 中填写。

### 4. 加载配置并运行

安装 `requirements.txt` 中的依赖后，在项目根目录打开 `run.ipynb`，按顺序运行单元格。Notebook 会先通过 `load_dotenv()` 加载 `.env`，随后初始化模型和研究工作流。可以修改研究请求单元格中的问题，生成自己的研究报告。

`.env` 和 `config.yml` 已加入 `.gitignore`，只保存在本地。需要共享配置结构时，请更新对应的 example 模板，并仅保留占位符。
