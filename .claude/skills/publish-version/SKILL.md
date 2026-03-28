---
name: publish-version
description: Publish a new semver release of ollim-bot. Use when the user wants to release, bump the version, or ship changes to downstream users.
argument-hint: [patch|minor|major] — bump type, or omit to auto-suggest from commits
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(gh *), Bash(sleep *), Read, Grep, Write, AskUserQuestion
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

## Draft release notes

Read the commits since the last tag and write human-readable release notes. These replace the auto-generated changelog on the GitHub Release.

Rules for drafting:
- Write from the user's perspective — what changed for them, not what code changed
- Group into **Features** and **Fixes & Improvements** (skip empty sections)
- One bullet per user-visible change — merge related commits into a single bullet
- Skip internal/dev-only changes (skills, CI, docs, chore)
- Keep it concise — 1-2 sentences per bullet max
- No commit hashes in the notes

Write the draft to `/tmp/release-notes.md`, then show it to the user via AskUserQuestion. Let them request edits. Update the file until they approve.

Example:

```markdown
### Features
- Version display: new `/version` command shows the current bot version. Version also appears in the startup greeting.
- Semver releases: the bot now tracks versions with semver tags instead of raw git commits. Auto-update detects new releases by tag.

### Fixes & Improvements
- Fixed version numbers showing a double `v` prefix in update messages.
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

On failure, show `gh run view <id> --log-failed` and abort.

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

- **Bootstrap**: the very first release requires `git tag v0.1.0 && git push origin v0.1.0` before this workflow works. If no `v*` tags exist, tell the user.
- **Checks run in-workflow**: lint and tests run inside the release workflow before committing. If they fail, no version bump or tag is created.
- **Duplicate tags**: if the tag already exists, the workflow aborts with a clear error.
- **Push first**: any commits not yet pushed to `origin/main` won't be included in the release. The preflight check catches this.
