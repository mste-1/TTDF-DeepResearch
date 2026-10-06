import importlib
import unittest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from deep_research.states import Critique, EvaluationResult


class CritiqueQueueTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Load the real nodes and graph without model clients or credentials.
        with patch("deep_research.llm.get_chat_model"):
            cls.supervisor_module = importlib.import_module("deep_research.agents.supervisor")
            cls.red_team_module = importlib.import_module("deep_research.agents.red_team_agent")
            cls.tools_module = importlib.import_module("deep_research.tools.tool")

    def setUp(self):
        self.critique = Critique(author="Red Team Adversary", concern="Add evidence for the cost comparison.")
        self.original = "Original report with a cost comparison that needs supporting evidence."
        self.revised = "Revised report with a cost comparison and supporting evidence from the research."
        self.evaluation = EvaluationResult(
            comprehensiveness_score=8,
            accuracy_score=8,
            coherence_score=8,
            reason="The draft is coherent.",
        )

    def tool_call(self, name, args=None, call_id="call-1"):
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args or {}, "id": call_id,
        }])

    def state(self, name="refine_draft_report", args=None):
        return {
            "research_brief": "Compare costs using evidence.",
            "draft_report": self.original,
            "pending_critiques": [self.critique],
            "supervisor_messages": [self.tool_call(name, args)],
            "research_iterations": 1,
        }

    def test_critique_has_no_addressed_field(self):
        self.assertNotIn("addressed", Critique.model_fields)

    async def test_red_team_enqueues_without_persistent_system_message(self):
        state = self.state()
        model = Mock(ainvoke=AsyncMock(return_value=AIMessage(
            content="Explain how the cost estimate changes under higher demand."
        )))
        with patch.object(self.red_team_module, "red_team_model", model):
            update = await self.red_team_module.red_team_node(state)
        self.assertEqual(len(update["pending_critiques"]), 2)
        self.assertEqual(update["pending_critiques"][0], self.critique)
        self.assertEqual(state["pending_critiques"], [self.critique])
        self.assertEqual(update["critique_nums"], 1)
        self.assertNotIn("supervisor_messages", update)

    async def test_red_team_pass_and_budget_limit_leave_queue_unchanged(self):
        state = self.state()
        model = Mock(ainvoke=AsyncMock(return_value=AIMessage(content="PASS")))
        with patch.object(self.red_team_module, "red_team_model", model):
            self.assertEqual(await self.red_team_module.red_team_node(state), {})
            state["critique_nums"] = self.red_team_module.iteration_config.MAX_RED_TEAM_CRITIQUES
            self.assertEqual(await self.red_team_module.red_team_node(state), {})
        model.ainvoke.assert_awaited_once()
        self.assertEqual(state["pending_critiques"], [self.critique])

    async def test_supervisor_injects_pending_only_and_preserves_history(self):
        state = self.state()
        unrelated = SystemMessage(content="Keep this unrelated instruction.")
        reflection = ToolMessage(content="Keep the research plan.", tool_call_id="think-1")
        state["supervisor_messages"] = [unrelated, reflection]
        model = Mock(ainvoke=AsyncMock(return_value=self.tool_call("think_tool", {"reflection": "Plan"})))
        with patch.object(self.supervisor_module, "supervisor_model_with_tools", model):
            await self.supervisor_module.supervisor(state)
            messages = model.ainvoke.call_args.args[0]
            self.assertTrue(any(self.critique.concern in m.content for m in messages))
            self.assertIn(unrelated, messages)
            self.assertIn(reflection, messages)
            self.assertEqual(state["pending_critiques"], [self.critique])

            state["pending_critiques"] = []
            await self.supervisor_module.supervisor(state)
            messages = model.ainvoke.call_args.args[0]
            self.assertFalse(any(self.critique.concern in m.content for m in messages))
            self.assertIn(unrelated, messages)
            self.assertIn(reflection, messages)

    async def test_successful_refinement_consumes_queue_even_with_low_score(self):
        state = self.state()
        low_score = self.evaluation.model_copy(update={"accuracy_score": 0, "coherence_score": 0})
        with (
            patch.object(self.supervisor_module, "_refine_draft_report_tool", Mock(invoke=Mock(return_value=self.revised))),
            patch.object(self.supervisor_module, "evaluate_draft_quality", return_value=low_score),
        ):
            command = await self.supervisor_module.supervisor_tools(state)
        self.assertEqual(command.update["pending_critiques"], [])
        self.assertEqual(command.update["draft_report"], self.revised)
        self.assertTrue(command.update["needs_quality_repair"])
        self.assertEqual(command.goto, "red_team")
        self.assertEqual(state["pending_critiques"], [self.critique])

    async def test_empty_writer_response_preserves_draft_and_queue(self):
        state = self.state()
        writer = Mock(invoke=Mock(return_value=AIMessage(content="")))
        with (
            patch.object(self.tools_module, "writer_model", writer),
            patch.object(self.supervisor_module, "evaluate_draft_quality", return_value=self.evaluation) as evaluate,
        ):
            command = await self.supervisor_module.supervisor_tools(state)
        self.assertNotIn("pending_critiques", command.update)
        self.assertNotIn("draft_report", command.update)
        self.assertEqual(command.goto, "supervisor")
        self.assertEqual(command.update["supervisor_messages"][0].tool_call_id, "call-1")
        evaluate.assert_not_called()

    async def test_blank_or_unchanged_refinement_preserves_queue(self):
        for result in (None, "", " \n", self.original, "\n" + self.original + "\n"):
            with (
                self.subTest(result=result),
                patch.object(self.supervisor_module, "_refine_draft_report_tool", Mock(invoke=Mock(return_value=result))),
                patch.object(self.supervisor_module, "evaluate_draft_quality", return_value=self.evaluation) as evaluate,
            ):
                command = await self.supervisor_module.supervisor_tools(self.state())
                self.assertNotIn("pending_critiques", command.update)
                self.assertNotIn("draft_report", command.update)
                self.assertEqual(command.goto, "supervisor")
                evaluate.assert_not_called()

    async def test_refinement_or_evaluation_exception_does_not_consume_queue(self):
        for failing_stage in ("writer", "evaluator"):
            with (
                self.subTest(failing_stage=failing_stage),
                patch.object(self.supervisor_module, "_refine_draft_report_tool") as refine,
                patch.object(self.supervisor_module, "evaluate_draft_quality") as evaluate,
            ):
                refine.invoke.return_value = self.revised
                evaluate.return_value = self.evaluation
                (refine.invoke if failing_stage == "writer" else evaluate).side_effect = RuntimeError("test failure")
                state = self.state()
                command = await self.supervisor_module.supervisor_tools(state)
                self.assertNotIn("pending_critiques", command.update)
                self.assertNotIn("draft_report", command.update)
                self.assertEqual(state["pending_critiques"], [self.critique])

    async def test_think_preserves_queue_and_supplies_findings_to_later_refinement(self):
        reflection = "Fix the red-team concern by adding cost evidence."
        state = self.state("think_tool", {"reflection": reflection})
        thought = await self.supervisor_module.supervisor_tools(state)
        self.assertNotIn("pending_critiques", thought.update)
        state["supervisor_messages"] += thought.update["supervisor_messages"]
        state["supervisor_messages"].append(self.tool_call("refine_draft_report", call_id="refine-1"))
        with (
            patch.object(self.supervisor_module, "_refine_draft_report_tool", Mock(invoke=Mock(return_value=self.revised))) as refine,
            patch.object(self.supervisor_module, "evaluate_draft_quality", return_value=self.evaluation),
        ):
            await self.supervisor_module.supervisor_tools(state)
        self.assertIn(reflection, refine.invoke.call_args.args[0]["findings"])

    async def test_research_does_not_consume_queue(self):
        researcher = Mock(ainvoke=AsyncMock(return_value={"compressed_research": "Evidence", "raw_notes": []}))
        with patch.object(self.supervisor_module, "researcher_agent", researcher):
            command = await self.supervisor_module.supervisor_tools(
                self.state("ConductResearch", {"research_topic": "Find cost evidence"})
            )
        self.assertNotIn("pending_critiques", command.update)
        self.assertEqual(command.goto, "supervisor")

    async def test_compiled_graph_consumes_queue_and_does_not_reinject_feedback(self):
        # Exercise real state merging and routing over discovery, think, refinement, PASS, and exit.
        supervisor_model = Mock(ainvoke=AsyncMock(side_effect=[
            self.tool_call("refine_draft_report", call_id="initial-refine"),
            self.tool_call("think_tool", {"reflection": "Add cost evidence."}, "think"),
            self.tool_call("refine_draft_report", call_id="repair"),
            self.tool_call("ResearchComplete", call_id="complete"),
        ]))
        red_team_model = Mock(ainvoke=AsyncMock(side_effect=[
            AIMessage(content=self.critique.concern), AIMessage(content="PASS"),
        ]))
        with (
            patch.object(self.supervisor_module, "supervisor_model_with_tools", supervisor_model),
            patch.object(self.red_team_module, "red_team_model", red_team_model),
            patch.object(self.supervisor_module, "_refine_draft_report_tool", Mock(invoke=Mock(side_effect=[
                self.original + " More detail.", self.revised,
            ]))),
            patch.object(self.supervisor_module, "evaluate_draft_quality", return_value=self.evaluation),
        ):
            result = await self.supervisor_module.supervisor_agent.ainvoke({
                "research_brief": "Compare costs.", "draft_report": self.original,
                "supervisor_messages": [],
            })
        self.assertEqual(result["pending_critiques"], [])
        self.assertEqual(result["draft_report"], self.revised)
        self.assertEqual(result["critique_nums"], 1)
        invocations = supervisor_model.ainvoke.call_args_list
        for index in (1, 2):
            self.assertTrue(any(self.critique.concern in m.content for m in invocations[index].args[0]))
        self.assertFalse(any(self.critique.concern in m.content for m in invocations[-1].args[0]))
        self.assertFalse(any(isinstance(m, SystemMessage) for m in result["supervisor_messages"]))


if __name__ == "__main__":
    unittest.main()
