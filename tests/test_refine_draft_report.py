import importlib
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage


class RefineDraftReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import the real tool without initializing model clients or credentials.
        with patch("deep_research.llm.get_chat_model"):
            cls.tools = importlib.import_module("deep_research.tools.tool")

    def test_response_fallback_order(self):
        original = "Original draft must survive empty model output."
        cases = [
            ("prefer_content", AIMessage(content="Refined report", additional_kwargs={"reasoning_content": "Reasoning report"}), "Refined report"),
            ("reasoning_fallback", AIMessage(content="", additional_kwargs={"reasoning_content": "Reasoning report"}), "Reasoning report"),
            ("both_empty", AIMessage(content="", additional_kwargs={"reasoning_content": ""}), original),
            ("reasoning_missing", AIMessage(content=""), original),
            ("blank_content", AIMessage(content=" \n", additional_kwargs={"reasoning_content": "Reasoning report"}), "Reasoning report"),
            ("both_blank", AIMessage(content=" \n", additional_kwargs={"reasoning_content": "\t "}), original),
            ("plain_string", "Plain text report", "Plain text report"),
        ]
        for name, response, expected in cases:
            with self.subTest(name=name):
                writer = Mock()
                writer.invoke.return_value = response
                with patch.object(self.tools, "writer_model", writer):
                    result = self.tools._refine_draft_report_tool.invoke({
                        "research_brief": "Research brief",
                        "findings": "Research findings",
                        "draft_report": original,
                    })
                self.assertEqual(result, expected)
                writer.invoke.assert_called_once()
                self.assertIn(original, writer.invoke.call_args.args[0][0].content)


if __name__ == "__main__":
    unittest.main()
