"""Optional, read-only engine observations; no web or storage dependencies.

Context variables are copied by asyncio tasks and LangChain's sync-node executor.
An observer must not change the engine's values, routing, or exception handling.
"""

from asyncio import CancelledError
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator
from uuid import uuid4

_observer: ContextVar[Callable[[dict], None] | None] = ContextVar("research_observer", default=None)
_scope: ContextVar[dict] = ContextVar("research_observation_scope", default={})


@contextmanager
def bind_observer(observer: Callable[[dict], None]) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


@contextmanager
def observation_scope(**fields: Any) -> Iterator[None]:
    token = _scope.set({**_scope.get(), **fields})
    try:
        yield
    finally:
        _scope.reset(token)


def observe(event: str, **fields: Any) -> None:
    observer = _observer.get()
    if observer is not None:
        try:
            observer({**_scope.get(), "event": event, **fields})
        except Exception:
            # Adapters retain delivery failures and fail the outer website task.
            # Notebook execution and the original graph's control flow are unchanged.
            pass


def current_observation_scope() -> dict:
    return dict(_scope.get())


async def observed_research(tool_call: dict, invoke: Callable, inputs: dict) -> Any:
    if _observer.get() is None:
        return await invoke(inputs)
    instance_id = uuid4().hex
    observe("research.dispatched", instance_id=instance_id,
            tool_call_id=tool_call["id"], topic=tool_call["args"]["research_topic"])
    with observation_scope(instance_id=instance_id):
        observe("research.started", topic=tool_call["args"]["research_topic"])
        try:
            result = await invoke(inputs)
        except (Exception, CancelledError):
            observe("research.failed")
            raise
        observe("research.completed", markdown=result.get("compressed_research", ""))
        return result
