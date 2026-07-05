"""Conversational build intake — request parsing, questions, and readiness."""

from core.agents.intake import intake_turn, parse_build_request


def test_parse_build_request_extracts_what_and_agent():
    what, agent = parse_build_request("hey Jardo, let's build a bakery website with claude")
    assert agent == "claude"
    assert "bakery website" in what

    what2, agent2 = parse_build_request("build me an inventory app with gemini")
    assert agent2 == "gemini"
    assert "inventory app" in what2


def test_default_agent_is_claude():
    _, agent = parse_build_request("create a landing page")
    assert agent == "claude"


async def test_intake_asks_a_question():
    async def model(messages):
        return "Nice — a bakery site! Who's the audience, and do you want online ordering?"

    turn = await intake_turn("claude", [], "a bakery website", model)
    assert turn.ready is False
    assert "audience" in turn.reply


async def test_intake_ready_produces_brief():
    async def model(messages):
        return "READY\n\n# Bakery site\n- Hero, menu, hours\n- Contact form\n- React + Vite"

    turn = await intake_turn("claude", [{"role": "user", "content": "..."}],
                             "yes that's everything", model)
    assert turn.ready is True
    assert turn.brief and "Bakery site" in turn.brief
    assert "READY" not in turn.brief  # marker stripped


async def test_history_is_threaded_into_the_prompt():
    seen = {}

    async def model(messages):
        seen["messages"] = messages
        return "another question?"

    history = [{"role": "user", "content": "a bakery site"},
               {"role": "assistant", "content": "who is it for?"}]
    await intake_turn("claude", history, "local customers", model)
    roles = [m["role"] for m in seen["messages"]]
    assert roles[0] == "system"
    # system + 2 history + latest user
    assert len(seen["messages"]) == 4
