import logging
import os
import inspect
from collections.abc import Callable, Awaitable
from pydantic import BaseModel

logger = logging.getLogger(__name__)


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
        on_iteration: Callable[..., Awaitable[str]] | None = None,
    ) -> QualityFeedback:
        content = initial_content
        last_result = QualityFeedback(passed=False, score=0.0, improvements=["未評価"])

        for iteration in range(1, self.max_iterations + 1):
            if self._evaluator:
                try:
                    last_result = await self._evaluator(content)
                except Exception as exc:
                    logger.error("QualityLoop: evaluator failed on iteration %d: %s", iteration, exc, exc_info=True)
                    last_result = QualityFeedback(
                        passed=False,
                        score=0.0,
                        improvements=[f"評価エラー（イテレーション{iteration}）: {exc}"],
                        escalate_to_user=True,
                    )
                    break
            else:
                last_result = QualityFeedback(passed=True, score=1.0)

            if last_result.passed:
                return last_result

            if iteration == self.max_iterations:
                last_result = last_result.model_copy(update={"escalate_to_user": True})
                break

            if on_iteration:
                try:
                    sig = inspect.signature(on_iteration)
                    if len(sig.parameters) >= 3:
                        # 新スタイル: (iteration, feedback, previous_content) -> str
                        content = await on_iteration(iteration, last_result, content)
                    else:
                        # 旧スタイル: (iteration, feedback) -> str（後方互換）
                        content = await on_iteration(iteration, last_result)
                except Exception as exc:
                    logger.error("QualityLoop: on_iteration failed on iteration %d: %s", iteration, exc)
                    break

        return last_result
