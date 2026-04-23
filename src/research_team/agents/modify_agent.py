from pathlib import Path
from research_team.agents.base_agent import BaseResearchAgent

_SKILLS_DIR = Path(__file__).parent / "skills"


class ModifyAgent(BaseResearchAgent):
    name = "ModifyAgent"
    skill_path = _SKILLS_DIR / "modify_agent"
