# Webhook Spec Format

External services can trigger background tasks via pre-approved webhook specs.
Webhook specs are markdown files with YAML frontmatter in `webhooks/`.

## File format

```markdown
---
id: "github-ci"
isolated: true
model: "haiku"
allow_ping: true
update_main_session: "on_ping"
fields:
  type: object
  required:
    - repo
    - status
  properties:
    repo:
      type: string
      maxLength: 200
    status:
      type: string
      enum: [success, failure, cancelled]
  additionalProperties: false
---
CI result for {{repo}}: {{status}}. Check the build and decide if it warrants attention.
```

## Creating webhook specs

Write a `.md` file to `webhooks/`. The body is a prompt template with `{{field}}`
placeholders filled from the webhook payload. External callers can ONLY pass
declared field values -- the prompt template (your instructions) is in the file.

## Security

- Prefer `enum` over free `string` wherever values are known.
- Use `integer`/`boolean` for non-text data.
- Always set `maxLength` on string fields.
- Always set `additionalProperties: false`.

## Config fields

Config fields match routine/reminder YAML: `isolated`, `model`, `allow_ping`,
`update_main_session`.
