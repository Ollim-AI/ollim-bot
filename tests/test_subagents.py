"""Tests for file-based subagent spec loading."""

from textwrap import dedent

from ollim_bot.storage import parse_md
from ollim_bot.subagents import SubagentSpec, build_agent_definitions, load_subagent_specs

VALID_SPEC = dedent("""\
    ---
    name: test-agent
    description: "A test subagent"
    model: haiku
    allowed-tools:
      - "Read(**.md)"
      - "Bash(ollim-bot help)"
    ---
    You are {USER_NAME}'s test agent.
""")


# --- parse_md with SubagentSpec ---


def test_parse_valid_spec():
    spec = parse_md(VALID_SPEC, SubagentSpec)

    assert spec.name == "test-agent"
    assert spec.description == "A test subagent"
    assert spec.model == "haiku"
    assert spec.allowed_tools == ["Read(**.md)", "Bash(ollim-bot help)"]
    assert "{USER_NAME}" in spec.message


def test_parse_spec_without_optional_fields():
    text = dedent("""\
        ---
        name: minimal
        description: "Minimal spec"
        ---
        Just a prompt.
    """)

    spec = parse_md(text, SubagentSpec)

    assert spec.name == "minimal"
    assert spec.model is None
    assert spec.allowed_tools is None


def test_parse_spec_ignores_unknown_fields():
    text = dedent("""\
        ---
        name: extended
        description: "Has extra fields"
        custom_field: "should be ignored"
        ---
        Prompt body.
    """)

    spec = parse_md(text, SubagentSpec)

    assert spec.name == "extended"
    assert not hasattr(spec, "custom_field")


# --- load_subagent_specs ---


def test_load_source_defaults():
    specs = load_subagent_specs()

    assert "guide" in specs
    assert "gmail-reader" in specs
    assert "history-reviewer" in specs
    assert "responsiveness-reviewer" in specs
    assert "user-proxy" in specs
    assert len(specs) == 5


def test_source_specs_have_required_fields():
    specs = load_subagent_specs()

    for name, spec in specs.items():
        assert spec.name == name
        assert spec.description
        assert spec.message
        assert spec.allowed_tools is not None and len(spec.allowed_tools) > 0


# --- build_agent_definitions ---


def test_build_agent_definitions_expands_templates():
    specs = {
        "test": SubagentSpec(
            name="test",
            description="Helps {USER_NAME}",
            message="You are {USER_NAME}'s assistant. {BOT_NAME} is the bot.",
            model="haiku",
            allowed_tools=["Read(**.md)"],
        )
    }

    definitions = build_agent_definitions(specs)

    defn = definitions["test"]
    assert "{USER_NAME}" not in defn.prompt
    assert "{BOT_NAME}" not in defn.prompt
    assert "{USER_NAME}" not in defn.description


def test_build_agent_definitions_preserves_tools_and_model():
    specs = {
        "test": SubagentSpec(
            name="test",
            description="Test",
            message="Prompt",
            model="sonnet",
            allowed_tools=["Bash(ollim-bot gmail *)", "Read(**.md)"],
        )
    }

    definitions = build_agent_definitions(specs)

    defn = definitions["test"]
    assert defn.model == "sonnet"
    assert defn.tools == ["Bash(ollim-bot gmail *)", "Read(**.md)"]


def test_build_agent_definitions_none_tools_becomes_empty_list():
    specs = {
        "test": SubagentSpec(
            name="test",
            description="Test",
            message="Prompt",
            allowed_tools=None,
        )
    }

    definitions = build_agent_definitions(specs)

    assert definitions["test"].tools == []
