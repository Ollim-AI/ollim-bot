"""Tests for webhook.py — spec parsing, validation, prompt construction, auth."""

from ollim_bot.webhook import (  # noqa: F401
    WebhookSpec,
    build_webhook_prompt,
    list_webhooks,
    load_webhook,
    validate_payload,
)


def test_parse_webhook_spec(data_dir):
    webhooks_dir = data_dir / "webhooks"
    webhooks_dir.mkdir()
    (webhooks_dir / "test-hook.md").write_text(
        "---\n"
        'id: "test-hook"\n'
        "isolated: true\n"
        'model: "haiku"\n'
        "fields:\n"
        "  type: object\n"
        "  required:\n"
        "    - repo\n"
        "  properties:\n"
        "    repo:\n"
        "      type: string\n"
        "  additionalProperties: false\n"
        "---\n"
        "CI result for {repo}.\n"
    )

    specs = list_webhooks()

    assert len(specs) == 1
    spec = specs[0]
    assert spec.id == "test-hook"
    assert spec.isolated is True
    assert spec.model == "haiku"
    assert spec.fields["type"] == "object"
    assert "repo" in spec.fields["properties"]
    assert spec.message == "CI result for {repo}."


def test_load_webhook_by_slug(data_dir):
    webhooks_dir = data_dir / "webhooks"
    webhooks_dir.mkdir()
    (webhooks_dir / "my-hook.md").write_text(
        "---\n"
        'id: "my-hook"\n'
        "fields:\n"
        "  type: object\n"
        "  properties:\n"
        "    msg:\n"
        "      type: string\n"
        "---\n"
        "Handle: {msg}\n"
    )

    spec = load_webhook("my-hook")

    assert spec is not None
    assert spec.id == "my-hook"
    assert spec.isolated is False
    assert spec.model is None


def test_load_webhook_not_found(data_dir):
    assert load_webhook("nonexistent") is None


def test_list_webhooks_empty(data_dir):
    assert list_webhooks() == []


def test_webhook_defaults(data_dir):
    webhooks_dir = data_dir / "webhooks"
    webhooks_dir.mkdir()
    (webhooks_dir / "minimal.md").write_text(
        '---\nid: "minimal"\nfields:\n  type: object\n  properties: {}\n---\nHello.\n'
    )

    spec = list_webhooks()[0]

    assert spec.thinking is True
    assert spec.allow_ping is True
    assert spec.update_main_session == "on_ping"
    assert spec.isolated is False


def test_validate_payload_valid():
    schema = {
        "type": "object",
        "required": ["repo"],
        "properties": {
            "repo": {"type": "string", "maxLength": 200},
            "status": {"type": "string", "enum": ["success", "failure"]},
        },
        "additionalProperties": False,
    }

    errors = validate_payload(schema, {"repo": "ollim-bot", "status": "failure"})

    assert errors == []


def test_validate_payload_missing_required():
    schema = {
        "type": "object",
        "required": ["repo"],
        "properties": {"repo": {"type": "string"}},
        "additionalProperties": False,
    }

    errors = validate_payload(schema, {})

    assert len(errors) > 0
    assert any("repo" in e for e in errors)


def test_validate_payload_extra_field_rejected():
    schema = {
        "type": "object",
        "properties": {"repo": {"type": "string"}},
        "additionalProperties": False,
    }

    errors = validate_payload(schema, {"repo": "test", "evil": "injection"})

    assert len(errors) > 0


def test_validate_payload_wrong_type():
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }

    errors = validate_payload(schema, {"count": "not-a-number"})

    assert len(errors) > 0


def test_validate_payload_enum_mismatch():
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "failure"]},
        },
    }

    errors = validate_payload(schema, {"status": "maybe"})

    assert len(errors) > 0


def test_validate_payload_default_max_length_injected():
    """String fields without explicit maxLength get default 500."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }

    errors = validate_payload(schema, {"name": "x" * 501})

    assert len(errors) > 0


def test_validate_payload_explicit_max_length_preserved():
    """Explicit maxLength is not overridden by default."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "maxLength": 1000}},
    }

    errors = validate_payload(schema, {"name": "x" * 800})

    assert errors == []


def test_validate_payload_too_many_properties():
    schema = {
        "type": "object",
        "properties": {f"f{i}": {"type": "string"} for i in range(25)},
    }

    errors = validate_payload(schema, {"f0": "test"})

    assert len(errors) > 0
    assert any("properties" in e.lower() for e in errors)


def test_build_webhook_prompt_has_tag(data_dir):
    spec = WebhookSpec(
        id="test-hook",
        message="Check {repo}.",
        fields={"type": "object", "properties": {"repo": {"type": "string"}}},
    )

    prompt = build_webhook_prompt(spec, {"repo": "ollim-bot"})

    assert "[webhook:test-hook]" in prompt


def test_build_webhook_prompt_data_section(data_dir):
    spec = WebhookSpec(
        id="ci",
        message="Check build.",
        fields={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    )

    prompt = build_webhook_prompt(spec, {"repo": "myrepo", "status": "failure"})

    assert "WEBHOOK DATA" in prompt
    assert "untrusted" in prompt.lower()
    assert "repo: myrepo" in prompt
    assert "status: failure" in prompt


def test_build_webhook_prompt_task_section(data_dir):
    spec = WebhookSpec(
        id="ci",
        message="Check {repo} build status.",
        fields={"type": "object", "properties": {"repo": {"type": "string"}}},
    )

    prompt = build_webhook_prompt(spec, {"repo": "ollim-bot"})

    assert "TASK" in prompt
    assert "Check ollim-bot build status." in prompt


def test_build_webhook_prompt_includes_preamble(data_dir):
    spec = WebhookSpec(
        id="ci",
        message="Check.",
        fields={"type": "object", "properties": {}},
    )

    prompt = build_webhook_prompt(spec, {})

    assert "ping_user" in prompt or "discarded" in prompt


def test_build_webhook_prompt_optional_fields_omitted(data_dir):
    """Optional fields not in payload should not appear in data section."""
    spec = WebhookSpec(
        id="ci",
        message="Check.",
        fields={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "branch": {"type": "string"},
            },
        },
    )

    prompt = build_webhook_prompt(spec, {"repo": "test"})

    assert "repo: test" in prompt
    assert "branch" not in prompt
