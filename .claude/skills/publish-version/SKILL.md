---
name: publish-version
description: Publish a new semver release of ollim-bot. Use when the user wants to release, bump the version, or ship changes to downstream users.
argument-hint: [patch|minor|major] — bump type, or omit to auto-suggest from commits
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(gh *), Bash(sleep *), Read, Grep
---

# Publish Version

Trigger the release workflow to create a versioned release of ollim-bot.

## Preflight

Run all checks before triggering. Abort on any failure.

```bash
# Must be on main
[ "$(git branch --show-current)" = "main" ] || { echo "not on main"; exit 1; }

# No uncommitted changes
git diff --quiet && git diff --cached --quiet || { echo "uncommitted changes"; exit 1; }

# Up to date with remote
git fetch origin --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "not up to date with origin/main"; exit 1; }
```

## Determine bump type

If the user provided a bump type (`/publish-version minor`), use it.

Otherwise, analyze commits since the last tag to suggest one:

```bash
CURRENT=$(git describe --tags --abbrev=0)
git log --oneline "$CURRENT..HEAD"
```

Suggest based on commit prefixes:
- Any `breaking:` or `BREAKING CHANGE` in commit body → **major**
- Any `feat:` → **minor**
- Only `fix:`, `chore:`, `docs:`, `refactor:` → **patch**
- If no commits since last tag → abort, nothing to release

Present the suggestion with the commit list and ask the user to confirm.

## Show release preview

Before triggering, show:

```
Current version: v0.1.0
Bump type: minor
Next version: v0.2.0

Changes:
  abc1234 feat: add /version command
  def5678 fix: double v prefix in messages
```

## Trigger the release workflow

```bash
gh workflow run release.yml -f bump_type=<TYPE>
```

Wait for the workflow run to appear, then show the link:

```bash
sleep 3
gh run list --workflow=release.yml --limit=1 --json databaseId,status,url
```

## Wait for completion

Poll until the workflow finishes:

```bash
gh run watch --exit-status $(gh run list --workflow=release.yml --limit=1 --json databaseId -q '.[0].databaseId')
```

On success, verify the release:

```bash
git fetch origin --tags
gh release list --limit 1
```

Report the release URL. On failure, show `gh run view <id> --log-failed`.

## Gotchas

- **Bootstrap**: the very first release requires `git tag v0.1.0 && git push origin v0.1.0` before this workflow works. If no `v*` tags exist, tell the user.
- **Checks run in-workflow**: lint and tests run inside the release workflow before committing. If they fail, no version bump or tag is created.
- **Duplicate tags**: if the tag already exists, the workflow aborts with a clear error.
- **Push first**: any commits not yet pushed to `origin/main` won't be included in the release. The preflight check catches this.
