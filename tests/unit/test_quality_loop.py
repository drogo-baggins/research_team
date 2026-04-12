import pytest
from research_team.orchestrator.quality_loop import QualityLoop, QualityFeedback


def test_quality_feedback_pass():
    fb = QualityFeedback(passed=True, score=0.9, improvements=[], agent_instructions={})
    assert fb.passed
    assert fb.improvements == []


def test_quality_feedback_fail_with_improvements():
    fb = QualityFeedback(
        passed=False,
        score=0.4,
        improvements=["情報ソースを引用してください", "結論を冒頭に書いてください"],
        agent_instructions={"researcher": "各段落末に出典URLを追加してください"},
    )
    assert not fb.passed
    assert len(fb.improvements) == 2
    assert "researcher" in fb.agent_instructions


def test_quality_feedback_escalate_flag():
    fb = QualityFeedback(passed=False, score=0.2, improvements=[], escalate_to_user=True)
    assert fb.escalate_to_user


@pytest.mark.asyncio
async def test_quality_loop_respects_max_iterations():
    call_count = 0

    async def always_fail_evaluator(content: str) -> QualityFeedback:
        nonlocal call_count
        call_count += 1
        return QualityFeedback(
            passed=False, score=0.0,
            improvements=["always fail"],
            agent_instructions={},
        )

    loop = QualityLoop(max_iterations=3, evaluator=always_fail_evaluator)
    result = await loop.run(initial_content="test")

    assert call_count == 3, f"Expected 3 calls, got {call_count}"
    assert not result.passed
    assert result.escalate_to_user


@pytest.mark.asyncio
async def test_quality_loop_stops_on_pass():
    call_count = 0

    async def pass_on_second(content: str) -> QualityFeedback:
        nonlocal call_count
        call_count += 1
        passed = call_count >= 2
        return QualityFeedback(
            passed=passed,
            score=0.9 if passed else 0.3,
            improvements=[] if passed else ["改善してください"],
            agent_instructions={},
        )

    loop = QualityLoop(max_iterations=5, evaluator=pass_on_second)
    result = await loop.run(initial_content="test")

    assert call_count == 2, f"Expected 2 calls, got {call_count}"
    assert result.passed
    assert not result.escalate_to_user
