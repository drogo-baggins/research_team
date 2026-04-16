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


@pytest.mark.asyncio
async def test_quality_loop_passes_previous_content_to_iteration():
    """on_iteration が previous_content を受け取れる（マージ戦略）。"""
    received_previous: list[str] = []

    async def fail_once_evaluator(content: str) -> QualityFeedback:
        passed = "IMPROVED" in content
        return QualityFeedback(passed=passed, score=0.9 if passed else 0.3, improvements=["add more"])

    async def merge_iteration(iteration: int, feedback: QualityFeedback, previous_content: str) -> str:
        received_previous.append(previous_content)
        return previous_content + "\nIMPROVED"

    loop = QualityLoop(max_iterations=3, evaluator=fail_once_evaluator)
    result = await loop.run(initial_content="INITIAL", on_iteration=merge_iteration)

    assert result.passed
    assert len(received_previous) == 1
    assert received_previous[0] == "INITIAL"


@pytest.mark.asyncio
async def test_quality_loop_backward_compat_two_arg_on_iteration():
    """既存の 2引数 on_iteration も引き続き動く（後方互換）。"""

    async def old_style_iteration(iteration: int, feedback: QualityFeedback) -> str:
        return "new content"

    loop = QualityLoop(max_iterations=2, evaluator=None)
    result = await loop.run(initial_content="test", on_iteration=old_style_iteration)
    assert result.passed
