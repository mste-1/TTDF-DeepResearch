import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deep_research import llm


class LLMResponseTextTests(unittest.TestCase):
    def test_prefers_content_then_reasoning_without_mutating_message(self):
        cases = [
            (AIMessage(content=" Report ", additional_kwargs={"reasoning_content": "Reasoning"}), " Report "),
            (AIMessage(content="", additional_kwargs={"reasoning_content": "Reasoning"}), "Reasoning"),
            (AIMessage(content=" \n", additional_kwargs={"reasoning_content": "Reasoning"}), "Reasoning"),
            ("Plain text", "Plain text"),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected), patch.object(llm.logger, "error") as error:
                before = response.model_dump() if isinstance(response, AIMessage) else response
                self.assertEqual(llm.get_llm_response_text(response), expected)
                after = response.model_dump() if isinstance(response, AIMessage) else response
                self.assertEqual(before, after)
                error.assert_not_called()

    def test_empty_response_logs_once_and_returns_empty_string(self):
        responses = [
            AIMessage(content=""),
            AIMessage(content=" \n", additional_kwargs={"reasoning_content": "\t "}),
            AIMessage(content="", additional_kwargs={"reasoning_content": None}),
            SimpleNamespace(content=None, additional_kwargs={}),
            None,
            "",
        ]
        for response in responses:
            with self.subTest(response=response), patch.object(llm.logger, "error") as error:
                self.assertEqual(llm.get_llm_response_text(response, context="test-stage"), "")
                error.assert_called_once()
                self.assertIn("test-stage", str(error.call_args))


class LLMTextConsumerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch("deep_research.llm.get_chat_model"):
            cls.research = importlib.import_module("deep_research.agents.research_agent")
            cls.red_team = importlib.import_module("deep_research.agents.red_team_agent")
            cls.builder = importlib.import_module("deep_research.agent_builder")

    async def test_final_report_uses_reasoning_or_continues_with_empty_text(self):
        for text in ("Final report from reasoning", ""):
            response = AIMessage(content="", additional_kwargs={"reasoning_content": text})
            model = Mock(ainvoke=AsyncMock(return_value=response))
            with (
                self.subTest(text=text),
                patch.object(self.builder, "writer_model", model),
                patch.object(llm.logger, "error") as error,
            ):
                update = await self.builder.final_report_generation({"draft_report": "Old draft"})
                self.assertEqual(update["final_report"], text)
                self.assertEqual(update["messages"], ["最终的报告: " + text])
                self.assertEqual(error.call_count, 0 if text else 1)

    def test_compression_preserves_reasoning_in_summary_and_raw_notes(self):
        response = AIMessage(content="", additional_kwargs={"reasoning_content": "Compressed findings"})
        history = [
            HumanMessage(content="Question"),
            AIMessage(content="", additional_kwargs={"reasoning_content": "Research findings"}),
            ToolMessage(content="Search evidence", tool_call_id="search-1"),
        ]
        model = Mock(invoke=Mock(return_value=response))
        with patch.object(self.research, "compress_model", model):
            update = self.research.compress_research({"researcher_messages": history})
        self.assertEqual(update["compressed_research"], "Compressed findings")
        self.assertEqual(update["raw_notes"], ["Research findings\nSearch evidence"])
        self.assertEqual(history[1].content, "")

    def test_empty_compression_logs_and_continues(self):
        model = Mock(invoke=Mock(return_value=AIMessage(content="")))
        with (
            patch.object(self.research, "compress_model", model),
            patch.object(llm.logger, "error") as error,
        ):
            update = self.research.compress_research({"researcher_messages": []})
        self.assertEqual(update["compressed_research"], "")
        error.assert_called_once()

    async def test_red_team_uses_reasoning_for_critique_and_pass(self):
        state = {"draft_report": "Draft report with enough text to be evaluated by the red team.", "research_brief": "Brief"}
        concern = "The report needs evidence to support its cost estimates."
        for text in (concern, "PASS", ""):
            model = Mock(ainvoke=AsyncMock(return_value=AIMessage(
                content="", additional_kwargs={"reasoning_content": text},
            )))
            with (
                self.subTest(text=text),
                patch.object(self.red_team, "red_team_model", model),
                patch.object(llm.logger, "error") as error,
            ):
                update = await self.red_team.red_team_node(state)
                if text == concern:
                    self.assertEqual(update["pending_critiques"][0].concern, concern)
                else:
                    self.assertEqual(update, {})
                self.assertEqual(error.call_count, 0 if text else 1)


if __name__ == "__main__":
    unittest.main()
