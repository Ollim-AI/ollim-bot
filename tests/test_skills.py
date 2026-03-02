"""Tests for skills.py — skill parsing, listing, index building, and command expansion."""

import ollim_bot.skills as skills_mod
from ollim_bot.skills import (
    _expand_commands,
    _parse_skill,
    build_skill_index,
    build_skills_section,
    collect_skill_tools,
    list_skills,
    load_skills,
    read_skill,
)

# --- _parse_skill ---


def test_parse_skill_valid():
    text = "---\nname: email-triage\ndescription: Process emails by priority.\n---\n## Steps\n1. Read emails"

    skill = _parse_skill(text)

    assert skill is not None
    assert skill.name == "email-triage"
    assert skill.description == "Process emails by priority."
    assert skill.message == "## Steps\n1. Read emails"
    assert skill.allowed_tools is None


def test_parse_skill_with_tools():
    text = '---\nname: gmail\ndescription: Email tools.\nallowed-tools:\n  - "Bash(ollim-bot gmail *)"\n  - "Read(**.md)"\n---\nDo email stuff'

    skill = _parse_skill(text)

    assert skill is not None
    assert skill.allowed_tools == ["Bash(ollim-bot gmail *)", "Read(**.md)"]


def test_parse_skill_missing_delimiters():
    assert _parse_skill("no frontmatter here") is None


def test_parse_skill_invalid_yaml():
    assert _parse_skill("---\n{{{bad yaml\n---\nbody") is None


def test_parse_skill_not_a_mapping():
    assert _parse_skill("---\n- list item\n---\nbody") is None


def test_parse_skill_missing_name():
    assert _parse_skill("---\ndescription: stuff\n---\nbody") is None


def test_parse_skill_missing_description():
    assert _parse_skill("---\nname: test\n---\nbody") is None


def test_parse_skill_extra_fields_ignored():
    text = '---\nname: test\ndescription: desc\nextra: ignored\nversion: "1.0"\n---\nbody'

    skill = _parse_skill(text)

    assert skill is not None
    assert skill.name == "test"
    assert skill.description == "desc"


def test_parse_skill_multiline_body():
    body = "First paragraph.\n\nSecond paragraph.\n\n- bullet one\n- bullet two"
    text = f"---\nname: test\ndescription: desc\n---\n{body}"

    skill = _parse_skill(text)

    assert skill is not None
    assert skill.message == body


# --- list_skills ---


def test_list_skills_missing_dir(data_dir):
    result = list_skills()

    assert result == []


def test_list_skills_empty_dir(data_dir):
    (data_dir / "skills").mkdir()

    result = list_skills()

    assert result == []


def test_list_skills_reads_skill_dirs(data_dir):
    skills_dir = data_dir / "skills"
    skill_dir = skills_dir / "email-triage"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: email-triage\ndescription: Process emails.\n---\nDo email stuff")

    result = list_skills()

    assert len(result) == 1
    assert result[0].name == "email-triage"
    assert result[0].description == "Process emails."
    assert result[0].message == "Do email stuff"


def test_list_skills_skips_non_directories(data_dir):
    skills_dir = data_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "stray-file.md").write_text("not a skill dir")

    result = list_skills()

    assert result == []


def test_list_skills_skips_dirs_without_skill_md(data_dir):
    skills_dir = data_dir / "skills"
    (skills_dir / "empty-dir").mkdir(parents=True)

    result = list_skills()

    assert result == []


def test_list_skills_skips_corrupt(data_dir):
    skills_dir = data_dir / "skills"
    good_dir = skills_dir / "good"
    good_dir.mkdir(parents=True)
    (good_dir / "SKILL.md").write_text("---\nname: good\ndescription: works\n---\nbody")
    bad_dir = skills_dir / "bad"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("not valid {{{")

    result = list_skills()

    assert len(result) == 1
    assert result[0].name == "good"


def test_list_skills_sorted_by_dir_name(data_dir):
    skills_dir = data_dir / "skills"
    for name in ["zebra", "alpha", "middle"]:
        d = skills_dir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: desc\n---\nbody")

    result = list_skills()

    assert [s.name for s in result] == ["alpha", "middle", "zebra"]


# --- read_skill ---


def test_read_skill_found(data_dir):
    skill_dir = data_dir / "skills" / "task-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: task-review\ndescription: Review tasks.\n---\nCheck deadlines")

    skill = read_skill("task-review")

    assert skill is not None
    assert skill.name == "task-review"
    assert skill.message == "Check deadlines"


def test_read_skill_path_traversal(data_dir):
    (data_dir / "skills").mkdir(parents=True)

    assert read_skill("../../etc") is None


def test_read_skill_not_found(data_dir):
    (data_dir / "skills").mkdir()

    assert read_skill("nonexistent") is None


def test_read_skill_corrupt(data_dir):
    skill_dir = data_dir / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("garbage")

    assert read_skill("broken") is None


# --- build_skill_index ---


def test_build_skill_index_empty(data_dir):
    assert build_skill_index() == ""


def test_build_skill_index_with_skills(data_dir):
    skills_dir = data_dir / "skills"
    for name, desc in [("alpha", "Does alpha things"), ("beta", "Does beta things")]:
        d = skills_dir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\nbody")

    index = build_skill_index()

    assert "Available skills:" in index
    assert "**alpha**: Does alpha things" in index
    assert "**beta**: Does beta things" in index


# --- collect_skill_tools ---


def test_collect_skill_tools_empty():
    assert collect_skill_tools([]) == []


def test_collect_skill_tools_from_skills(data_dir):
    skills_dir = data_dir / "skills"
    d = skills_dir / "gmail"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        '---\nname: gmail\ndescription: Email.\nallowed-tools:\n  - "Bash(ollim-bot gmail *)"\n  - "Read(**.md)"\n---\nbody'
    )

    tools = collect_skill_tools(load_skills(["gmail"]))

    assert tools == ["Bash(ollim-bot gmail *)", "Read(**.md)"]


def test_collect_skill_tools_deduplicates(data_dir):
    skills_dir = data_dir / "skills"
    for name in ["a", "b"]:
        d = skills_dir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f'---\nname: {name}\ndescription: desc\nallowed-tools:\n  - "Read(**.md)"\n  - "Bash(ollim-bot help)"\n---\nbody'
        )

    tools = collect_skill_tools(load_skills(["a", "b"]))

    assert tools == ["Read(**.md)", "Bash(ollim-bot help)"]


def test_collect_skill_tools_skips_missing(data_dir):
    (data_dir / "skills").mkdir(parents=True)

    tools = collect_skill_tools(load_skills(["nonexistent"]))

    assert tools == []


def test_collect_skill_tools_skips_skills_without_tools(data_dir):
    skills_dir = data_dir / "skills"
    d = skills_dir / "no-tools"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: no-tools\ndescription: desc\n---\nbody")

    tools = collect_skill_tools(load_skills(["no-tools"]))

    assert tools == []


# --- _expand_commands ---


def test_expand_commands_no_commands():
    text = "Plain text with no commands."

    result = _expand_commands(text)

    assert result == text


def test_expand_commands_single():
    text = "Today: !`echo hello`"

    result = _expand_commands(text)

    assert result == "Today: hello"


def test_expand_commands_multiple():
    text = "A: !`echo alpha` B: !`echo beta`"

    result = _expand_commands(text)

    assert result == "A: alpha B: beta"


def test_expand_commands_mixed_content():
    text = "## Status\n\nTasks: !`echo 3 pending`\n\n- bullet one\n- bullet two"

    result = _expand_commands(text)

    assert "3 pending" in result
    assert "!`" not in result
    assert "- bullet one" in result


def test_expand_commands_failure():
    result = _expand_commands("!`false`")

    assert "[command failed (exit 1)" in result


def test_expand_commands_failure_with_stderr():
    result = _expand_commands("!`sh -c 'echo oops >&2; exit 1'`")

    assert "[command failed (exit 1)" in result
    assert "oops" in result


def test_expand_commands_not_found():
    result = _expand_commands("!`nonexistent-xyz-cmd-12345`")

    assert "[command not found" in result


def test_expand_commands_parse_error():
    result = _expand_commands("!`echo 'unclosed`")

    assert "[command parse error" in result


def test_expand_commands_timeout(monkeypatch):
    monkeypatch.setattr(skills_mod, "_COMMAND_TIMEOUT", 0.5)
    monkeypatch.setattr(skills_mod, "_TOTAL_TIMEOUT", 5)

    result = _expand_commands("!`sleep 10`")

    assert "[command timed out" in result


def test_expand_commands_total_timeout(monkeypatch):
    monkeypatch.setattr(skills_mod, "_COMMAND_TIMEOUT", 5)
    monkeypatch.setattr(skills_mod, "_TOTAL_TIMEOUT", 0.5)

    result = _expand_commands("!`sleep 5` then !`echo second`")

    assert "[command timed out" in result
    assert "[command skipped (total timeout): echo second]" in result


def test_expand_commands_output_truncation(monkeypatch):
    monkeypatch.setattr(skills_mod, "_MAX_OUTPUT", 50)

    result = _expand_commands("!`seq 1 10000`")

    assert len(result) < 200
    assert "[...truncated]" in result


def test_expand_commands_deduplicates():
    text = "!`echo same` and !`echo same`"

    result = _expand_commands(text)

    assert result == "same and same"


# --- build_skills_section with commands ---


def test_build_skills_section_expands_commands(data_dir):
    skills_dir = data_dir / "skills"
    d = skills_dir / "status"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: status\ndescription: Current status.\n---\nTasks: !`echo 5 pending`")

    result = build_skills_section(load_skills(["status"]))

    assert "SKILL INSTRUCTIONS:" in result
    assert "5 pending" in result
    assert "!`" not in result
