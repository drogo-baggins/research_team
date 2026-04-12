import pytest
from research_team.agents.dynamic.factory import (
    DynamicAgentFactory,
    DynamicSpecialistAgent,
    MAX_AGENTS,
)
from research_team.agents.base_agent import BaseResearchAgent


def test_dynamic_specialist_is_base_research_agent():
    agent = DynamicSpecialistAgent("expert", "finance", "You analyze markets.")
    assert isinstance(agent, BaseResearchAgent)


def test_dynamic_specialist_name_and_expertise():
    agent = DynamicSpecialistAgent("Alice", "biology", "You study cells.")
    assert agent.name == "Alice"
    assert agent._expertise == "biology"


def test_dynamic_specialist_system_prompt_rendered():
    agent = DynamicSpecialistAgent("Bob", "physics", "You study quantum mechanics.")
    prompt = agent._load_system_prompt()
    assert "Bob" in prompt
    assert "physics" in prompt
    assert "You study quantum mechanics." in prompt


def test_factory_create_specialist_returns_agent():
    factory = DynamicAgentFactory()
    agent = factory.create_specialist("Dr. Smith", "chemistry", "You study reactions.")
    assert isinstance(agent, DynamicSpecialistAgent)
    assert agent.name == "Dr. Smith"


def test_factory_enforces_max_agents_limit():
    factory = DynamicAgentFactory()
    for i in range(MAX_AGENTS):
        factory.create_specialist(f"expert_{i}", "general", "You are an expert.")
    with pytest.raises(ValueError, match=f"maximum of {MAX_AGENTS} agents"):
        factory.create_specialist("overflow", "overflow", "overflow")


def test_factory_raises_on_duplicate_name():
    factory = DynamicAgentFactory()
    factory.create_specialist("Alice", "biology", "You study cells.")
    with pytest.raises(ValueError, match="already exists"):
        factory.create_specialist("Alice", "chemistry", "You study molecules.")


def test_factory_remove_specialist():
    factory = DynamicAgentFactory()
    factory.create_specialist("Alice", "biology", "You study cells.")
    factory.remove_specialist("Alice")
    assert "Alice" not in factory.agents


def test_factory_remove_nonexistent_raises():
    factory = DynamicAgentFactory()
    with pytest.raises(KeyError, match="not found"):
        factory.remove_specialist("nobody")


def test_factory_clear_removes_all():
    factory = DynamicAgentFactory()
    for i in range(3):
        factory.create_specialist(f"expert_{i}", "general", "You are an expert.")
    factory.clear()
    assert len(factory.agents) == 0


def test_factory_slot_freed_after_remove_allows_new_agent():
    factory = DynamicAgentFactory()
    for i in range(MAX_AGENTS):
        factory.create_specialist(f"expert_{i}", "general", "You are an expert.")
    factory.remove_specialist("expert_0")
    agent = factory.create_specialist("new_expert", "new_field", "You are new.")
    assert agent.name == "new_expert"
