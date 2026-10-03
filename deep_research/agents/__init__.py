#***********************************************
#      Filename: __init__.py
#   Description: 智能体定义 
#***********************************************

from importlib import import_module

__all__ = ["write_research_brief", "write_draft_report", "supervisor_agent"]


def __getattr__(name):
    # 按需加载，避免运行单个 Agent 时提前初始化其他模型。
    if name in ("write_research_brief", "write_draft_report"):
        module = import_module("deep_research.agents.draft_agent")
    elif name == "supervisor_agent":
        module = import_module("deep_research.agents.supervisor")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(module, name)
    globals()[name] = value
    return value
