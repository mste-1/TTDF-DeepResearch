"""统一管理研究流程的迭代、搜索预算与相关停止条件。

修改后需重启 Python 进程或 Notebook 内核，再重新运行。
这里仅定义配置，不初始化模型，也不读取包含密钥的 config.yml。
"""

# Supervisor 节点调用轮数；每次调用加 1，工具节点在 >= 上限时结束研究。
# 一轮可能包含多个工具调用，因此该值不是单个工具的调用次数。
MAX_SUPERVISOR_ITERATIONS = 15

# 提示词建议的每轮并行研究数；当前代码没有强制截断或并发限流。
MAX_CONCURRENT_RESEARCHERS = 3

# 红队累计返回有效批评的次数上限；PASS / 过短回复不增加计数。
MAX_RED_TEAM_CRITIQUES = 3

# LangGraph 执行步数上限，与业务迭代轮数不同；达到时由框架抛出异常。
# 用于 run.ipynb 和 draft_agent 的独立运行入口，必须传在 config 顶层。
GRAPH_RECURSION_LIMIT = 50

# 以下搜索预算和提前停止条件仅通过 Research Agent 提示词约束模型。
# 简单查询保留原来的“最多 2-3 次”预算范围。
SIMPLE_SEARCH_CALLS_MIN = 2
SIMPLE_SEARCH_CALLS_MAX = 3
MAX_SEARCH_CALLS = 5

# 相关示例/资源数量超过此值时停止；最近连续这么多次搜索相似时停止。
SEARCH_RESOURCE_THRESHOLD = 3
MAX_REPEATED_SEARCHES = 2
