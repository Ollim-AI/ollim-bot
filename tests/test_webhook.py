"""Tests for webhook.py — spec parsing, validation, prompt construction, auth."""

from ollim_bot.webhook import WebhookSpec, list_webhooks, load_webhook  # noqa: F401


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
