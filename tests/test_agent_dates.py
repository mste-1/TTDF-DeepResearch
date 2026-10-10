"""Actual prompt assembly with model doubles; no external requests."""
import importlib
from datetime import datetime
import unittest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage
from deep_research.utils import get_today_str


class AgentDateTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch("deep_research.llm.get_chat_model"):
            cls.red_team = importlib.import_module("deep_research.agents.red_team_agent")
            cls.evaluator = importlib.import_module("deep_research.agents.evaluator_agent")

    def test_beijing_date_changes_at_utc_1600(self):
        for instant, day in [("2026-10-10T15:59:59+00:00", 10),
                             ("2026-10-10T16:00:00+00:00", 11)]:
            current = datetime.fromisoformat(instant)
            with self.subTest(instant=instant), patch("deep_research.utils.datetime") as clock:
                clock.now.side_effect = lambda tz: current.astimezone(tz)
                result = get_today_str()
                self.assertIn(f"{day}, 2026", result)
                self.assertIn("北京时间 UTC+8", result)
                self.assertEqual(clock.now.call_args.args[0].utcoffset(None).total_seconds(), 28800)

    async def test_red_team_receives_fresh_date_on_every_call(self):
        model = Mock(ainvoke=AsyncMock(return_value=AIMessage(content="PASS")))
        state = {"research_brief": "近两个月的价格", "draft_report": "已有证据的研究草稿。" * 12}
        dates = ["Sat Oct 10, 2026（北京时间 UTC+8）", "Sun Oct 11, 2026（北京时间 UTC+8）"]
        with patch.object(self.red_team, "red_team_model", model), patch.object(self.red_team, "get_today_str", side_effect=dates):
            for date in dates:
                await self.red_team.red_team_node(state)
                prompt = model.ainvoke.call_args.args[0][0].content
                self.assertIn(date, prompt)
                self.assertIn(state["research_brief"], prompt)
                self.assertIn(state["draft_report"], prompt)
                self.assertNotIn("{date}", prompt)

    def test_evaluator_receives_fresh_date_on_every_call(self):
        model = Mock()
        dates = ["Sat Oct 10, 2026（北京时间 UTC+8）", "Sun Oct 11, 2026（北京时间 UTC+8）"]
        with patch.object(self.evaluator, "judge_model", model), patch.object(self.evaluator, "get_today_str", side_effect=dates):
            for date in dates:
                self.evaluator.evaluate_draft_quality("研究简报", "待评估草稿")
                prompt = model.with_structured_output.return_value.invoke.call_args.args[0][0].content
                self.assertIn(date, prompt)
                self.assertIn("研究简报", prompt)
                self.assertIn("待评估草稿", prompt)
                self.assertNotIn("{date}", prompt)


if __name__ == "__main__":
    unittest.main()
