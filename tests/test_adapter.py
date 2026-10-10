"""D1: real compiled graphs and tools, deterministic models, no credentials/network."""

import asyncio
import builtins
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import RunnableLambda

from deep_research.observability import bind_observer, observation_scope, observe
from deep_research.states import EvaluationResult
from server.agent_adapter.events import EventBridge
from server.agent_adapter.runner import _run_graph


def tool_message(name, args=None, call_id="call"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


class AdapterGraphTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch("deep_research.llm.get_chat_model"):
            cls.builder = importlib.import_module("deep_research.agent_builder")
            cls.supervisor = importlib.import_module("deep_research.agents.supervisor")
            cls.draft = importlib.import_module("deep_research.agents.draft_agent")
            cls.research = importlib.import_module("deep_research.agents.research_agent")
            cls.red_team = importlib.import_module("deep_research.agents.red_team_agent")
            cls.tools = importlib.import_module("deep_research.tools.tool")

    def setUp(self):
        # These deterministic graph tests must never send external telemetry.
        self.environment = patch.dict(os.environ, {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING_V2": "false"})
        self.environment.start()
        from langsmith.utils import get_env_var
        get_env_var.cache_clear()
        self.addCleanup(self.environment.stop)
        self.addCleanup(get_env_var.cache_clear)

    async def test_real_graph_parallel_sync_tools_artifacts_and_private_boundary(self):
        events = []
        fast_saved = threading.Event()
        main_thread = threading.get_ident()
        tool_threads = []

        def emit(event):
            events.append(event)
            if event["type"] == "artifact.created" and event["payload"].get("markdown") == "compressed:fast":
                fast_saved.set()

        def decide(messages):
            if isinstance(messages[-1], ToolMessage):
                return AIMessage(content="PRIVATE_RESEARCH_DECISION")
            topic = messages[1].content
            return tool_message("tavily_search", {"query": topic}, "search-" + topic)

        def search(client, query, **kwargs):
            tool_threads.append(threading.get_ident())
            return {"results": [{"url": "https://example.com/" + query,
                                 "title": query, "content": "excerpt:" + query}]}

        def compress(messages):
            topic = messages[1].content
            if topic == "slow":
                if not fast_saved.wait(3):
                    raise AssertionError("Fast research was not published before slow research completed")
            return AIMessage(content="", additional_kwargs={"reasoning_content": "compressed:" + topic})

        draft_model = Mock()
        draft_model.with_structured_output.return_value.invoke.side_effect = [
            SimpleNamespace(research_brief="Brief"), SimpleNamespace(draft_report="Initial draft " * 8),
        ]
        dispatch = AIMessage(content="PRIVATE_SUPERVISOR_THOUGHT", tool_calls=[
            {"name": "ConductResearch", "args": {"research_topic": topic}, "id": topic}
            for topic in ("fast", "slow")
        ])
        dispatch.tool_calls.append({"name": "think_tool", "args": {"reflection": "PRIVATE_REFLECTION"}, "id": "think"})
        supervisor_model = FakeMessagesListChatModel(responses=[dispatch,
            tool_message("refine_draft_report", call_id="refine"), tool_message("ResearchComplete")])
        evaluation = EvaluationResult(comprehensiveness_score=8, accuracy_score=7, coherence_score=9, reason="Has evidence")
        with (
            patch.object(self.draft, "draft_model", draft_model),
            patch.object(self.supervisor, "supervisor_model_with_tools", supervisor_model),
            patch.object(self.research, "model_with_tools", RunnableLambda(decide)),
            patch.object(self.research, "compress_model", RunnableLambda(compress)),
            patch.object(self.tools, "search_provider", Mock(search=search)),
            patch.object(self.tools, "search_client", object()),
            patch.object(self.tools, "search_defaults", {"max_results": 3, "topic": "general"}),
            patch.object(self.tools, "writer_model", FakeMessagesListChatModel(responses=[AIMessage(content="Revised draft " * 8)])),
            patch.object(self.supervisor, "evaluate_draft_quality", return_value=evaluation),
            patch.object(self.red_team, "red_team_model", FakeMessagesListChatModel(responses=[AIMessage(content="A valid concern requiring more supporting sources.")])),
            patch.object(self.builder, "writer_model", FakeMessagesListChatModel(responses=[AIMessage(content="", additional_kwargs={"reasoning_content": "# Final report\nResult"})])),
        ):
            report = await _run_graph(self.builder.agent, "Topic", "Optional instruction", emit, lambda: False)

        self.assertEqual(report, "# Final report\nResult")
        self.assertTrue(tool_threads)
        self.assertTrue(all(thread != main_thread for thread in tool_threads))
        sources = [event for event in events if event["type"] == "source.discovered"]
        self.assertEqual({event["payload"]["query"] for event in sources}, {"fast", "slow"})
        self.assertEqual(len({event["agent_instance_id"] for event in sources}), 2)
        dispatches = [event for event in events if event["type"] == "research.dispatched"]
        self.assertEqual(len(dispatches), 2)
        self.assertTrue(all(event.get("parent_instance_id") for event in dispatches))
        self.assertEqual({event["agent_instance_id"] for event in dispatches}, {event["agent_instance_id"] for event in sources})
        dispatched_labels = {event["agent_instance_id"]: event["payload"]["label"] for event in dispatches}
        completed_labels = {event["agent_instance_id"]: event["payload"]["label"] for event in events if event["type"] == "research.completed"}
        self.assertEqual(completed_labels, dispatched_labels)
        artifacts = [event["payload"] for event in events if event["type"] == "artifact.created"]
        self.assertEqual({artifact["kind"] for artifact in artifacts},
                         {"brief", "draft", "research", "source_summary", "draft_revision", "critique", "final"})
        self.assertEqual({artifact["source_url"] for artifact in artifacts if artifact["kind"] == "source_summary"},
                         {"https://example.com/fast", "https://example.com/slow"})
        for stage in ("brief", "draft", "final"):
            self.assertEqual(sum(event["type"] == "stage.started" and event["payload"].get("stage") == stage for event in events), 1)
        revisions = [artifact for artifact in artifacts if artifact["kind"] == "draft_revision"]
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0]["id"], revisions[1]["id"])
        self.assertEqual([artifact["partial"] for artifact in revisions], [True, False])
        self.assertTrue(any(event["type"] == "quality.evaluated" for event in events))
        wire = json.dumps(events)
        for private in ("reasoning_content", "reasoning_fallback", "origin", "raw_notes", "PRIVATE_", "supervisor_messages"):
            self.assertNotIn(private, wire)
        self.assertFalse(any(event["type"] == "research.warning" for event in events))

    async def test_evaluator_failure_preserves_candidate_and_original_route(self):
        events = []
        bridge = EventBridge(events.append)
        state = {"research_brief": "Brief", "draft_report": "Old draft",
                 "research_iterations": 1, "supervisor_messages": [tool_message("refine_draft_report")]}
        with (
            bind_observer(bridge.observe),
            patch.object(self.supervisor, "_refine_draft_report_tool", Mock(invoke=Mock(return_value="Candidate draft"))),
            patch.object(self.supervisor, "evaluate_draft_quality", side_effect=RuntimeError("secret-provider-message")),
        ):
            result = await self.supervisor.supervisor_tools(state)
        self.assertEqual(result.goto, "__end__")
        self.assertNotIn("draft_report", result.update)
        candidates = [event["payload"] for event in events if event["type"] == "artifact.created"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["markdown"], "Candidate draft")
        self.assertTrue(candidates[0]["partial"])
        self.assertNotIn("secret-provider-message", json.dumps(events))
        self.assertTrue(any(event["type"] == "research.warning" for event in events))

    async def test_unchanged_refinement_does_not_duplicate_old_artifact(self):
        events = []
        with (
            bind_observer(EventBridge(events.append).observe),
            patch.object(self.supervisor, "_refine_draft_report_tool", Mock(invoke=Mock(return_value="Old"))),
        ):
            result = await self.supervisor.supervisor_tools({
                "draft_report": "Old", "research_iterations": 1,
                "supervisor_messages": [tool_message("refine_draft_report")],
            })
        self.assertEqual(result.goto, "supervisor")
        self.assertFalse(any(event["type"] == "artifact.created" for event in events))

    async def test_delivery_failure_cannot_claim_success(self):
        async def invoke(inputs, config):
            observe("source.discovered", url="https://example.com", title="Source", query="query")
            return {"final_report": "Report"}

        def broken_emit(event):
            raise OSError("IPC closed")

        with self.assertRaisesRegex(RuntimeError, "delivery failed"):
            await _run_graph(SimpleNamespace(ainvoke=invoke), "Topic", "", broken_emit, lambda: False)

    def test_source_published_before_summary_and_degraded_excerpt_preserved(self):
        events = []
        bridge = EventBridge(events.append)
        raw = "Evidence " * 200

        def fail_summary(messages):
            self.assertEqual(events[0]["type"], "source.discovered")
            raise RuntimeError("private provider failure details")

        model = Mock()
        model.with_structured_output.return_value.invoke.side_effect = fail_summary
        with (
            bind_observer(bridge.observe), observation_scope(instance_id="research-test"),
            patch.object(self.tools, "summarization_model", model),
            patch.object(self.tools, "search_provider", Mock(search=Mock(return_value={"results": [
                {"url": "https://example.com", "title": "Evidence", "raw_content": raw, "content": "excerpt"},
            ]}))),
            patch.object(self.tools, "search_client", object()),
            patch.object(self.tools, "search_defaults", {"max_results": 3}),
            patch.object(self.tools.logger, "error"),
        ):
            result = self.tools.tavily_search("query")
        excerpt = raw[:self.tools.DEFAULT_MAX_CONTEXT] + "..."
        self.assertIn(excerpt, result)
        self.assertEqual(next(event["payload"]["markdown"] for event in events if event["type"] == "artifact.created"), excerpt)
        self.assertTrue(any(event["type"] == "research.warning" for event in events))
        self.assertNotIn("private provider failure details", json.dumps(events))

    async def test_parallel_completion_does_not_change_gather_result_order(self):
        events = []
        fast_done = asyncio.Event()

        async def invoke(inputs):
            topic = inputs["research_topic"]
            if topic == "slow":
                await fast_done.wait()
            else:
                fast_done.set()
            return {"compressed_research": topic, "raw_notes": []}

        calls = AIMessage(content="", tool_calls=[
            {"name": "ConductResearch", "args": {"research_topic": topic}, "id": topic}
            for topic in ("slow", "fast")
        ])
        with bind_observer(EventBridge(events.append).observe), patch.object(self.supervisor, "researcher_agent", SimpleNamespace(ainvoke=invoke)):
            result = await self.supervisor.supervisor_tools({"supervisor_messages": [calls], "research_iterations": 1})
        artifacts = [event["payload"]["markdown"] for event in events if event["type"] == "artifact.created"]
        self.assertEqual(artifacts, ["fast", "slow"])
        self.assertEqual([message.content for message in result.update["supervisor_messages"]], ["slow", "fast"])

    async def test_empty_report_and_cancelled_entry_fail_without_retry(self):
        graph = SimpleNamespace(ainvoke=AsyncMock(return_value={"final_report": ""}))
        with self.assertRaisesRegex(RuntimeError, "未获得最终报告"):
            await _run_graph(graph, "Topic", "", lambda event: None, lambda: False)
        graph.ainvoke.assert_awaited_once()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await _run_graph(graph, "Topic", "", lambda event: None, lambda: True)
        graph.ainvoke.assert_awaited_once()

    async def test_graph_preserves_explicit_external_tracing_configuration(self):
        from langsmith.utils import get_env_var, tracing_is_enabled

        async def invoke(inputs, config):
            self.assertTrue(tracing_is_enabled())
            return {"final_report": "Report"}

        # A stub graph only reads the setting: no trace handler or model runs.
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true", "LANGSMITH_TRACING_V2": "true"}):
            get_env_var.cache_clear()
            self.assertEqual(await _run_graph(SimpleNamespace(ainvoke=invoke), "Topic", "", lambda event: None, lambda: False), "Report")


class AdapterEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wenli-env-test-")
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for key in ("WENLI_AGENT_ENV_FILE", "CONFIG_PATH", "LANGSMITH_TRACING", "LANGSMITH_TRACING_V2",
                    "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_PROJECT", "LANGSMITH_USE_DAEMON", "WENLI_TEST_ENV_VALUE"):
            os.environ.pop(key, None)
        from server.agent_adapter import runner
        self.runner = runner
        self.module_path = patch.object(runner, "__file__", str(self.root / "server" / "agent_adapter" / "runner.py"))
        self.module_path.start()
        self.addCleanup(self.module_path.stop)
        from langsmith.utils import get_env_var
        get_env_var.cache_clear()
        self.addCleanup(get_env_var.cache_clear)

    def write_env(self, relative, text):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def test_explicit_env_loaded_before_model_import_and_graph_execution(self):
        from langsmith.utils import get_env_var, tracing_is_enabled

        selected = self.write_env("settings/custom.env", "LANGSMITH_TRACING=true\nLANGSMITH_PROJECT=wenli-test\nWENLI_TEST_ENV_VALUE=explicit-file\n")
        os.environ["WENLI_AGENT_ENV_FILE"] = str(selected)
        os.environ["CONFIG_PATH"] = str(self.root / "config" / "config.yml")
        self.write_env("config/.env", "WENLI_TEST_ENV_VALUE=beside-config\n")
        self.write_env(".env", "WENLI_TEST_ENV_VALUE=repo-default\n")
        imported = []
        original_import = builtins.__import__

        async def invoke(inputs, config):
            self.assertEqual(os.environ["LANGSMITH_PROJECT"], "wenli-test")
            self.assertTrue(tracing_is_enabled())
            return {"final_report": "Test result"}

        def guarded_import(name, *args, **kwargs):
            if name == "deep_research.agent_builder":
                imported.append(name)
                self.assertEqual(os.environ["WENLI_TEST_ENV_VALUE"], "explicit-file")
                self.assertEqual(os.environ["LANGSMITH_TRACING"], "true")
                get_env_var.cache_clear()
                return SimpleNamespace(agent=SimpleNamespace(ainvoke=invoke))
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import), patch.object(self.runner, "_flush_traces"):
            result = self.runner.run_research("Topic", "", lambda event: None, lambda: False)
        self.assertEqual(result, "Test result")
        self.assertEqual(imported, ["deep_research.agent_builder"])

    def test_existing_process_values_take_precedence(self):
        selected = self.write_env(".env", "LANGSMITH_TRACING=true\nWENLI_TEST_ENV_VALUE=from-file\n")
        os.environ.update(WENLI_AGENT_ENV_FILE=str(selected), LANGSMITH_TRACING="false", WENLI_TEST_ENV_VALUE="from-process")
        self.runner._load_agent_environment()
        self.assertEqual(os.environ["LANGSMITH_TRACING"], "false")
        self.assertEqual(os.environ["WENLI_TEST_ENV_VALUE"], "from-process")

    def test_daemon_default_is_applied_before_model_import_and_respects_configuration(self):
        original_import = builtins.__import__
        cases = ((None, None, "true"), ("false", "true", "false"), (None, "false", "false"))
        for process_value, file_value, expected in cases:
            with self.subTest(process_value=process_value, file_value=file_value):
                os.environ.pop("LANGSMITH_USE_DAEMON", None)
                if process_value is not None:
                    os.environ["LANGSMITH_USE_DAEMON"] = process_value
                selected = self.write_env("daemon.env", "" if file_value is None else f"LANGSMITH_USE_DAEMON={file_value}\n")
                os.environ["WENLI_AGENT_ENV_FILE"] = str(selected)

                def guarded_import(name, *args, **kwargs):
                    if name == "deep_research.agent_builder":
                        self.assertEqual(os.environ["LANGSMITH_USE_DAEMON"], expected)
                        return SimpleNamespace(agent=object())
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=guarded_import), \
                     patch.object(self.runner, "_run_graph", new=AsyncMock(return_value="Report")), \
                     patch.object(self.runner, "_flush_traces"):
                    self.assertEqual(self.runner.run_research("Topic", "", lambda event: None, lambda: False), "Report")
                self.assertEqual(os.environ["LANGSMITH_USE_DAEMON"], expected)

    def test_config_sibling_precedes_repository_default(self):
        os.environ["CONFIG_PATH"] = str(self.root / "settings" / "config.yml")
        self.write_env("settings/.env", "WENLI_TEST_ENV_VALUE=beside-config\n")
        self.write_env(".env", "WENLI_TEST_ENV_VALUE=repo-default\n")
        self.runner._load_agent_environment()
        self.assertEqual(os.environ["WENLI_TEST_ENV_VALUE"], "beside-config")

    def test_missing_config_sibling_uses_repository_default(self):
        os.environ["CONFIG_PATH"] = str(self.root / "settings" / "config.yml")
        self.write_env(".env", "WENLI_TEST_ENV_VALUE=repo-default\n")
        self.runner._load_agent_environment()
        self.assertEqual(os.environ["WENLI_TEST_ENV_VALUE"], "repo-default")

    def test_missing_default_file_is_optional_but_explicit_file_is_required(self):
        self.runner._load_agent_environment()
        self.assertNotIn("WENLI_TEST_ENV_VALUE", os.environ)
        os.environ["WENLI_AGENT_ENV_FILE"] = str(self.root / "missing.env")
        with self.assertRaisesRegex(FileNotFoundError, "WENLI_AGENT_ENV_FILE"):
            self.runner.run_research("Topic", "", lambda event: None, lambda: False)

    def test_import_has_no_environment_file_or_model_initialization_side_effect(self):
        import dotenv
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            self.assertNotIn(name, {"deep_research.agent_builder", "deep_research.llm", "dotenv"})
            return original_import(name, *args, **kwargs)

        before = dict(os.environ)
        with patch.object(dotenv, "load_dotenv") as load, patch("builtins.__import__", side_effect=guarded_import):
            importlib.reload(self.runner)
        load.assert_not_called()
        self.assertEqual(dict(os.environ), before)


class AdapterTraceFlushTests(unittest.TestCase):
    def test_flush_waits_for_existing_tracer_in_daemon_thread(self):
        from server.agent_adapter.runner import _flush_traces

        observed = []
        with patch("langchain_core.tracers.langchain.wait_for_all_tracers",
                   side_effect=lambda: observed.append(threading.current_thread().daemon)) as wait:
            _flush_traces(timeout=0.5)
        wait.assert_called_once_with()
        self.assertEqual(observed, [True])

    def test_flush_failure_only_logs_generic_internal_message(self):
        from server.agent_adapter.runner import _flush_traces

        with patch("langchain_core.tracers.langchain.wait_for_all_tracers", side_effect=RuntimeError("private credential detail")):
            with self.assertLogs("wenli.agent_adapter", level="WARNING") as logs:
                _flush_traces(timeout=0.5)
        self.assertIn("Trace flush failed", " ".join(logs.output))
        self.assertNotIn("private credential", " ".join(logs.output))

    def test_flush_timeout_does_not_wait_for_background_completion(self):
        from server.agent_adapter.runner import _flush_traces

        release, finished = threading.Event(), threading.Event()

        def blocked_flush():
            try:
                release.wait(5)
            finally:
                finished.set()

        try:
            with patch("langchain_core.tracers.langchain.wait_for_all_tracers", side_effect=blocked_flush):
                start = time.monotonic()
                with self.assertLogs("wenli.agent_adapter", level="WARNING") as logs:
                    _flush_traces(timeout=0.02)
                self.assertLess(time.monotonic() - start, 0.5)
                self.assertFalse(finished.is_set())
                self.assertIn("Trace flush timed out", " ".join(logs.output))
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_runner_flushes_after_success_and_preserves_original_exception(self):
        from server.agent_adapter import runner

        original_import = builtins.__import__
        outcomes = ["Report", RuntimeError("research failed")]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                async def invoke(inputs, config):
                    self.assertEqual(config["run_name"], "问砺深度研究")
                    if isinstance(outcome, Exception):
                        raise outcome
                    return {"final_report": outcome}

                def guarded_import(name, *args, **kwargs):
                    if name == "deep_research.agent_builder":
                        return SimpleNamespace(agent=SimpleNamespace(ainvoke=invoke))
                    return original_import(name, *args, **kwargs)

                with patch.object(runner, "_load_agent_environment"), patch.object(runner, "_flush_traces") as flush:
                    with patch("builtins.__import__", side_effect=guarded_import):
                        if isinstance(outcome, Exception):
                            with self.assertRaises(RuntimeError) as raised:
                                runner.run_research("Topic", "", lambda event: None, lambda: False)
                            self.assertIs(raised.exception, outcome)
                        else:
                            self.assertEqual(runner.run_research("Topic", "", lambda event: None, lambda: False), "Report")
                    flush.assert_called_once_with()


class AdapterBoundaryTests(unittest.TestCase):
    def test_research_failure_keeps_its_dispatched_topic(self):
        events = []
        bridge = EventBridge(events.append)
        bridge.observe({"event": "research.dispatched", "instance_id": "child", "topic": "储能技术的成本比较"})
        bridge.observe({"event": "research.failed", "instance_id": "child"})
        self.assertEqual(events[-1]["payload"], {"label": "储能技术的成本比较", "stage": "research", "status": "failed"})

    def test_partial_writer_upserts_same_artifact_and_ignores_reasoning_tokens(self):
        events = []
        bridge = EventBridge(events.append)
        node, model = uuid4(), uuid4()
        bridge.on_chain_start(None, {}, run_id=node, name="final_report_generation", metadata={"langgraph_node": "final_report_generation"})
        bridge.on_chat_model_start(None, [], run_id=model, parent_run_id=node)
        bridge.on_llm_new_token("PRIVATE", run_id=model, chunk=ChatGenerationChunk(message=AIMessageChunk(content="", additional_kwargs={"reasoning_content": "PRIVATE"})))
        bridge.on_llm_new_token("Hello", run_id=model, chunk=ChatGenerationChunk(message=AIMessageChunk(content="Hello")))
        bridge.on_chain_end({"final_report": "Hello world"}, run_id=node)
        artifacts = [event["payload"] for event in events if event["type"] == "artifact.created"]
        self.assertEqual([artifact["markdown"] for artifact in artifacts], ["Hello", "Hello world"])
        self.assertEqual(artifacts[0]["id"], artifacts[1]["id"])
        self.assertNotIn("PRIVATE", json.dumps(events))

    def test_internal_origins_are_never_public_even_for_admin(self):
        events = []
        bridge = EventBridge(events.append)
        bridge.observe({"event": "internal.text_origin", "origin": "reasoning_fallback", "context": "research_raw_notes"})
        self.assertEqual(events, [])
        self.assertEqual(bridge.text_origins[0]["origin"], "reasoning_fallback")

    def test_observer_exception_does_not_change_engine_return_or_message(self):
        from deep_research.llm import get_llm_response_text
        message = AIMessage(content="", additional_kwargs={"reasoning_content": "Report"})
        before = message.model_dump()
        with bind_observer(Mock(side_effect=RuntimeError("broken observation"))):
            self.assertEqual(get_llm_response_text(message), "Report")
        self.assertEqual(before, message.model_dump())


if __name__ == "__main__":
    unittest.main()
