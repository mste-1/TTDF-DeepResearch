"""Worker-only entry point. Importing this module does not initialize the Agent."""

import asyncio
import logging
import os
from pathlib import Path
import threading
from typing import Callable
from uuid import uuid4

LOGGER = logging.getLogger("wenli.agent_adapter")


class ResearchCancelled(RuntimeError):
    pass


def _load_agent_environment() -> None:
    """Load the selected worker .env without overriding its process environment."""
    from dotenv import load_dotenv

    explicit = os.environ.get("WENLI_AGENT_ENV_FILE")
    if explicit:
        env_file = Path(explicit).expanduser()
        if not env_file.is_file():
            raise FileNotFoundError("WENLI_AGENT_ENV_FILE must point to an existing .env file")
    else:
        config_path = os.environ.get("CONFIG_PATH")
        beside_config = Path(config_path).expanduser().parent / ".env" if config_path else None
        env_file = beside_config if beside_config and beside_config.is_file() else Path(__file__).resolve().parents[2] / ".env"
        if not env_file.is_file():
            return
    load_dotenv(dotenv_path=env_file, override=False)


def _flush_traces(timeout: float = 5.0) -> None:
    """Give the existing SDK tracer a bounded chance to submit its last events."""
    def drain():
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()
        except Exception:
            LOGGER.warning("Trace flush failed; research results are unchanged")

    thread = threading.Thread(target=drain, name="wenli-trace-flush", daemon=True)
    try:
        thread.start()
        thread.join(timeout=max(0.0, timeout))
        if thread.is_alive():
            LOGGER.warning("Trace flush timed out; research results are unchanged")
    except Exception:
        LOGGER.warning("Trace flush could not start; research results are unchanged")


async def _run_graph(graph, topic: str, instructions: str, emit: Callable[[dict], None],
                     cancelled: Callable[[], bool]) -> str:
    from langchain_core.messages import HumanMessage

    from deep_research.iteration_config import GRAPH_RECURSION_LIMIT
    from deep_research.observability import bind_observer
    from server.agent_adapter.events import EventBridge

    if cancelled():
        raise ResearchCancelled("Research was cancelled")
    bridge = EventBridge(emit)
    query = topic.strip()
    if instructions.strip():
        query += "\n\n补充研究要求：\n" + instructions.strip()
    with bind_observer(bridge.observe):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config={"run_name": "问砺深度研究", "callbacks": [bridge], "recursion_limit": GRAPH_RECURSION_LIMIT,
                    "configurable": {"thread_id": uuid4().hex}},
        )
    bridge.check_delivery()
    if cancelled():
        raise ResearchCancelled("Research was cancelled")
    report = result.get("final_report", "")
    if not isinstance(report, str) or not report.strip():
        raise RuntimeError("未获得最终报告，已有阶段成果已保留。")
    return report


def run_research(topic: str, instructions: str, emit: Callable[[dict], None],
                 cancelled: Callable[[], bool]) -> str:
    """Run a fresh original graph; process supervision handles hard cancellation."""
    if cancelled():
        raise ResearchCancelled("Research was cancelled")
    _load_agent_environment()
    # Bounded shutdown is the default for one-process-per-task workers. An
    # explicit process or .env setting still takes precedence over this default.
    os.environ.setdefault("LANGSMITH_USE_DAEMON", "true")
    try:
        # These imports read model configuration, so they belong exclusively here,
        # inside a worker process, never at API-module import time.
        from deep_research.agent_builder import agent

        return asyncio.run(_run_graph(agent, topic, instructions, emit, cancelled))
    finally:
        _flush_traces()
