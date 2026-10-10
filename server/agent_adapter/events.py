"""Allowlisted graph observations, deliberately separate from raw model traces."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler

from deep_research.observability import current_observation_scope


STAGES = {
    "write_research_brief": ("brief", "研究简报"),
    "write_draft_report": ("draft", "草稿撰写"),
    "supervisor_subgraph": ("supervisor", "研究统筹"),
    "supervisor": ("supervisor_dispatch", "研究决策"),
    "supervisor_tools": ("supervisor_tools", "分发与汇总"),
    "red_team": ("red_team", "对抗审阅"),
    "final_report_generation": ("final", "最终总结"),
}


class EventBridge(BaseCallbackHandler):
    """One bridge per job; a lock serializes sync callback threads and async tasks.

Only accepted node fields or explicit engine observations become public data.
Prompts, tool arguments, message histories, and raw model traces never do.
"""

    run_inline = True

    def __init__(self, emit: Callable[[dict], None]):
        self._emit = emit
        self._lock = threading.RLock()
        self._runs: dict[str, dict] = {}
        self._instances: dict[str, dict] = {}
        self._refinements: dict[tuple[str, str], str] = {}
        self._last_root: str | None = None
        self._delivery_error: Exception | None = None
        self._partial: dict[str, str] = {}
        self._partial_sent: dict[str, tuple[float, int]] = {}
        # Internal metadata is not handed to emit or returned to the browser.
        self.text_origins: list[dict] = []

    def check_delivery(self) -> None:
        if self._delivery_error is not None:
            raise RuntimeError("Research event delivery failed") from self._delivery_error

    def _send(self, event_type: str, payload: dict, instance: str | None = None) -> None:
        record = self._instances.get(instance or "", {})
        if event_type in {"stage.started", "research.started"}:
            record["status"] = "running"
        elif event_type in {"stage.completed", "research.completed"}:
            record["status"] = payload.get("status", "completed")
        event = {"type": event_type, "payload": payload}
        if instance:
            event["agent_instance_id"] = instance
        if record.get("parent"):
            event["parent_instance_id"] = record["parent"]
        if isinstance(record.get("iteration"), int):
            event["iteration"] = record["iteration"]
        try:
            self._emit(event)
        except Exception as exc:
            # Observations must not change the old engine's exception handling.
            # The outer runner fails instead of claiming unpersisted success.
            self._delivery_error = self._delivery_error or exc

    def _artifact(self, instance: str, kind: str, title: str, markdown: Any,
                  *, suffix: str = "", partial: bool = False, source_url: str | None = None) -> None:
        if not isinstance(markdown, str) or not markdown.strip():
            return
        artifact_id = hashlib.sha256(f"{instance}:{kind}:{suffix}".encode()).hexdigest()[:32]
        payload = {
            "id": artifact_id, "kind": kind, "title": title,
            "markdown": markdown, "partial": partial, "agent_instance_id": instance,
        }
        if source_url:
            payload["source_url"] = source_url
        self._send("artifact.created", payload, instance)

    def _ancestor(self, run_id: Any) -> str | None:
        seen = set()
        while run_id and str(run_id) not in seen:
            key = str(run_id)
            seen.add(key)
            item = self._runs.get(key, {})
            if item.get("instance"):
                return item["instance"]
            run_id = item.get("parent")
        return None

    def _context_instance(self) -> str | None:
        scoped = current_observation_scope().get("instance_id")
        if scoped:
            return scoped
        try:
            from langgraph.config import get_config
            manager = get_config().get("callbacks")
            return self._ancestor(getattr(manager, "parent_run_id", None))
        except RuntimeError:
            return None

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None,
                       metadata=None, name=None, **kwargs):
        with self._lock:
            key = str(run_id)
            parent = self._ancestor(parent_run_id)
            scope_instance = current_observation_scope().get("instance_id")
            record = {"parent": str(parent_run_id) if parent_run_id else None,
                      "instance": scope_instance or parent, "name": name}
            self._runs[key] = record
            # A compiled subgraph's internal wrappers can share node metadata.
            # Only the actual named node starts a public stage.
            if name not in STAGES or (metadata or {}).get("langgraph_node") != name:
                return
            instance = uuid4().hex
            stage, label = STAGES[name]
            input_state = inputs if isinstance(inputs, dict) else {}
            record.update(instance=instance, public_stage=True,
                          old_critiques=len(input_state.get("pending_critiques", [])))
            self._instances[instance] = {
                "parent": parent or self._last_root, "stage": stage, "label": label,
                "iteration": input_state.get("research_iterations"),
            }
            if not parent:
                self._last_root = instance
            self._send("stage.started", {"stage": stage, "label": label}, instance)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        with self._lock:
            record = self._runs.get(str(run_id), {})
            if not record.get("public_stage"):
                return
            instance, name = record["instance"], record["name"]
            output = getattr(outputs, "update", outputs)
            # dict.update is a method, not a LangGraph Command.update value.
            if isinstance(outputs, dict):
                output = outputs
            if isinstance(output, dict):
                if name == "write_research_brief":
                    self._artifact(instance, "brief", "研究简报", output.get("research_brief"))
                elif name == "write_draft_report":
                    self._artifact(instance, "draft", "初稿", output.get("draft_report"))
                elif name == "red_team":
                    for index, critique in enumerate(output.get("pending_critiques", [])[record["old_critiques"]:]):
                        concern = critique.get("concern") if isinstance(critique, dict) else getattr(critique, "concern", None)
                        self._artifact(instance, "critique", "审阅意见", concern, suffix=str(index))
                elif name == "final_report_generation":
                    self._artifact(instance, "final", "研究报告", output.get("final_report"))
            item = self._instances[instance]
            self._send("stage.completed", {"stage": item["stage"], "label": item["label"]}, instance)

    def on_chain_error(self, error, *, run_id, **kwargs):
        with self._lock:
            record = self._runs.get(str(run_id), {})
            if record.get("public_stage"):
                instance = record["instance"]
                if self._partial.get(instance):
                    self._artifact(instance, "final", "研究报告（未完成）", self._partial[instance], partial=True)
                item = self._instances[record["instance"]]
                self._send("stage.completed", {"stage": item["stage"], "label": item["label"],
                                               "status": "failed"}, record["instance"])

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        with self._lock:
            self._runs[str(run_id)] = {"parent": str(parent_run_id) if parent_run_id else None,
                                      "instance": self._ancestor(parent_run_id)}

    def on_llm_new_token(self, token, *, run_id, chunk=None, **kwargs):
        with self._lock:
            instance = self._ancestor(run_id)
            if not instance or self._instances.get(instance, {}).get("stage") != "final":
                return
            # Never trust the untyped token argument: only a known final-writer
            # message's actual content is eligible, with no reasoning blocks.
            content = getattr(getattr(chunk, "message", None), "content", None)
            if not isinstance(content, str) or not content or content != token:
                return
            self._partial[instance] = self._partial.get(instance, "") + content
            now = time.monotonic()
            sent_at, sent_size = self._partial_sent.get(instance, (0.0, 0))
            if now - sent_at >= 0.25 or len(self._partial[instance]) - sent_size >= 2000:
                self._artifact(instance, "final", "研究报告（生成中）", self._partial[instance], partial=True)
                self._partial_sent[instance] = (now, len(self._partial[instance]))

    def observe(self, observation: dict) -> None:
        with self._lock:
            event = observation.get("event")
            parent = self._context_instance()
            instance = observation.get("instance_id") or parent
            if event == "internal.text_origin":
                self.text_origins.append({
                    "instance_id": instance, "context": observation.get("context"),
                    "model_call_id": observation.get("model_call_id"), "origin": observation.get("origin"),
                })
                return
            if event == "research.dispatched":
                self._instances[instance] = {"parent": parent, "stage": "research", "label": observation.get("topic") or "资料研究",
                                             "iteration": self._instances.get(parent or "", {}).get("iteration")}
                self._send(event, {"label": self._instances[instance]["label"], "stage": "research"}, instance)
            elif event == "research.started":
                self._send(event, {"label": observation.get("topic", "资料研究"), "stage": "research"}, instance)
            elif event == "research.completed":
                self._artifact(instance, "research", "子研究成果", observation.get("markdown"))
                self._send(event, {"label": self._instances.get(instance, {}).get("label", "资料研究"), "stage": "research"}, instance)
            elif event == "research.failed":
                self._send("stage.completed", {"label": self._instances.get(instance, {}).get("label", "资料研究"), "stage": "research", "status": "failed"}, instance)
            elif event == "source.discovered":
                self._send(event, {"url": observation.get("url", ""), "title": observation.get("title", ""),
                                   "query": observation.get("query", "")}, instance)
            elif event == "source.summary" and instance:
                self._artifact(instance, "source_summary", observation.get("title") or "资料摘要",
                               observation.get("markdown"), suffix=observation.get("url", ""), source_url=observation.get("url"))
            elif event == "summary.degraded":
                self._send("research.warning", {"code": "summary_degraded", "message": "一份资料摘要未完成，已保留可用的摘录。"}, instance)
            elif event and event.startswith(("refinement.", "evaluation.")):
                self._refinement(observation, parent)
            elif event == "supervisor.error":
                # Plain evaluator/refinement functions are not graph nodes, so
                # their failures do not have a framework on_chain_error event.
                for child, record in list(self._instances.items()):
                    if record.get("stage") in {"refine", "evaluation"} and record.get("status") == "running":
                        self._send("stage.completed", {"stage": record["stage"], "label": record["label"], "status": "failed"}, child)
                self._send("research.warning", {"code": "research_ended_early", "message": "一项研究步骤未完成，智能体将基于已有成果收尾。"}, instance)
            elif event == "supervisor.finished" and observation.get("reason") == "iteration_limit":
                self._send("research.warning", {"code": "iteration_limit", "message": "已达到研究轮次上限，将基于已有成果生成报告。"}, instance)

    def _refinement(self, observation: dict, parent: str | None) -> None:
        event = observation["event"]
        key = (parent or "", observation.get("tool_call_id", ""))
        if event == "refinement.started":
            instance = uuid4().hex
            self._refinements[key] = instance
            self._instances[instance] = {"parent": parent, "stage": "refine", "label": "草稿修订"}
            self._send("stage.started", {"stage": "refine", "label": "草稿修订"}, instance)
            return
        instance = self._refinements.get(key)
        if not instance:
            return
        if event == "refinement.candidate":
            self._artifact(instance, "draft_revision", "修订候选（尚未完成评价）", observation.get("markdown"), partial=True)
        elif event == "refinement.accepted":
            self._artifact(instance, "draft_revision", "修订稿", observation.get("markdown"))
            self._send("stage.completed", {"stage": "refine", "label": "草稿修订"}, instance)
        elif event == "refinement.unchanged":
            self._send("stage.completed", {"stage": "refine", "label": "草稿未变化"}, instance)
        elif event == "evaluation.started":
            evaluation = instance + "-evaluation"
            self._instances[evaluation] = {"parent": instance, "stage": "evaluation", "label": "质量评价"}
            self._send("stage.started", {"stage": "evaluation", "label": "质量评价"}, evaluation)
        elif event == "evaluation.completed":
            evaluation = instance + "-evaluation"
            self._send("quality.evaluated", {"scores": observation.get("scores", {}),
                                             "feedback": observation.get("feedback", "")}, evaluation)
            self._send("stage.completed", {"stage": "evaluation", "label": "质量评价"}, evaluation)
