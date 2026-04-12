import os
from collections.abc import Callable, Awaitable
from pydantic import BaseModel


class QualityFeedback(BaseModel):
    passed: bool
    score: float
    improvements: list[str] = []
    agent_instructions: dict[str, str] = {}
    escalate_to_user: bool = False


class QualityLoop:
    def __init__(
        self,
        max_iterations: int | None = None,
        evaluator: Callable[[str], Awaitable[QualityFeedback]] | None = None,
    ):
        self.max_iterations = max_iterations or int(
            os.environ.get("MAX_QUALITY_ITERATIONS", "3")
        )
        self._evaluator = evaluator

    async def run(
        self,
        initial_content: str,
        on_iteration: Callable[[int, QualityFeedback], Awaitable[str]] | None = None,
    ) -> QualityFeedback:
        content = initial_content
        last_result = QualityFeedback(passed=False, score=0.0, improvements=["未評価"])

        for iteration in range(1, self.max_iterations + 1):
            if self._evaluator:
                last_result = await self._evaluator(content)
            else:
                last_result = QualityFeedback(passed=True, score=1.0)

            if last_result.passed:
                return last_result

            if iteration == self.max_iterations:
                last_result = last_result.model_copy(update={"escalate_to_user": True})
                break

            if on_iteration:
                content = await on_iteration(iteration, last_result)

        return last_result
