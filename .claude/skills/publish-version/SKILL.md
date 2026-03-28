---
name: publish-version
description: Publish a new semver release of ollim-bot. Use when the user wants to release, bump the version, or ship changes to downstream users.
argument-hint: [patch|minor|major] — bump type, or omit to auto-suggest from commits
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(gh *), Read, Grep, Write
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

# Has commits since last tag (re-run safety)
CURRENT=$(git describe --tags --abbrev=0 2>/dev/null)
if [ -n "$CURRENT" ] && [ -z "$(git log --oneline "$CURRENT..HEAD")" ]; then
  echo "no new commits since $CURRENT — nothing to release"
  exit 1
fi
```

If no `v*` tags exist at all, tell the user to bootstrap: `git tag v0.1.0 && git push origin v0.1.0`.

## Determine bump type

If the user provided a bump type (`/publish-version minor`), use it.

Otherwise, analyze commits since the last tag:

```bash
git log --oneline "$CURRENT..HEAD"
```

Suggest based on commit prefixes:
- Any `breaking:` or `BREAKING CHANGE` in commit body → **major**
- Any `feat:` → **minor**
- Only `fix:`, `chore:`, `docs:`, `refactor:` → **patch**

Present the suggestion with the commit list. Use `AskUserQuestion` to confirm the bump type before proceeding.

## Draft release notes

Read the commits since the last tag and write human-readable release notes.

**Drafting rules:**
- Write from the user's perspective — what changed for them, not what code changed
- Group into **Features** and **Fixes & Improvements** (skip empty sections)
- One bullet per user-visible change — merge related commits into a single bullet
- Skip internal/dev-only changes (skills, CI, docs, chore)
- Keep it concise — 1-2 sentences per bullet max
- No commit hashes in the notes

Write the draft to `/tmp/release-notes.md`.

**Terminology grounding**: before revising, read the terminology table in `~/ollim-bot-docs/CLAUDE.md` (the "Terminology" section). These are canonical terms that must not be simplified or rewritten — they are consistent across code and docs.

**Revise pass**: invoke `/revise` on `/tmp/release-notes.md` (audience: non-technical end users, genre: release notes, tone: match `~/ollim-bot-docs/` — direct, conversational, ADHD-aware). Constraint: preserve all terms from the terminology table exactly (e.g. "background fork", "interactive fork", "ping budget", "routine", "reminder"). This catches filler and vague language while keeping domain terminology consistent.

Then use `AskUserQuestion` to show the revised draft and let the user request further edits. Update the file until approved.

Example:

```markdown
### Features
- Version display: new `/version` command shows the current bot version. Version also appears in the startup greeting.
- Semver releases: the bot now tracks versions with semver tags instead of raw git commits. Auto-update detects new releases by tag.

### Fixes & Improvements
- Fixed version numbers showing a double `v` prefix in update messages.
```

## Trigger the release workflow

**This step is irreversible** — it commits a version bump to main, creates a git tag, and publishes a GitHub Release. There is no undo.

Use `AskUserQuestion` to confirm: show the exact command and the version that will be created. Only proceed on explicit approval.

```bash
gh workflow run release.yml -f bump_type=<TYPE>
```

## Wait for completion

Poll until the workflow finishes:

```bash
RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId -q '.[0].databaseId')
gh run watch --exit-status "$RUN_ID"
```

On failure, show `gh run view "$RUN_ID" --log-failed` and abort.

## Replace release notes

After the workflow succeeds, replace the auto-generated notes with the drafted ones:

```bash
TAG=$(gh release list --limit 1 --json tagName -q '.[0].tagName')
gh release edit "$TAG" --notes-file /tmp/release-notes.md
```

Verify:

```bash
git fetch origin --tags
gh release view "$TAG"
```

Report the release URL.

## Gotchas

- **Bootstrap**: the very first release requires `git tag v0.1.0 && git push origin v0.1.0` before this workflow works.
- **Checks run in-workflow**: lint and tests run inside the release workflow before committing. If they fail, no version bump or tag is created.
- **Duplicate tags**: if the tag already exists, the workflow aborts with a clear error.
- **Push first**: any commits not yet pushed to `origin/main` won't be included in the release. The preflight check catches this.
