# UX Principles — Scoring Rubric

Yes/no checklist for evaluating user-facing features and changes. Each item maps to a principle in SKILL.md. Score after designing, implementing, or reviewing anything the user sees.

## Responsiveness

- [ ] User gets a visible signal (reaction, typing, embed) within 500ms of their action
- [ ] New user input takes priority over in-progress bot output (no queuing behind bot)
- [ ] Interrupted responses leave no residual status messages or error artifacts

## Communication

- [ ] System messages are lowercase, one-line, minimal (no chatbot enthusiasm)
- [ ] Bot presents one recommended action, not a list of options (unless user asked for options)
- [ ] No mention of tools, integrations, or capabilities the bot doesn't actually have
- [ ] Embed titles contain no emoji (stripped, not just avoided in the prompt)

## Proactive Outreach

- [ ] Every new proactive notification path goes through ping budget
- [ ] Background messages have provenance tags ([bg] prefix or embed footer)
- [ ] Scheduled outreach uses conversation context, not generic templates
- [ ] Budget exhaustion is silent to the user (error returned to agent, not shown)
- [ ] Internal machinery (rate limits, token refresh, retries) is invisible to the user

## Interactive Flows

- [ ] Successful state changes confirmed minimally (ephemeral or embed, not a paragraph)
- [ ] Slash commands that reconfigure the bot clean up their own invocation messages
- [ ] Context crosses boundaries correctly (fork→main via updates, reply→fork via session resume)
- [ ] Degradation messages (timeout, expiry, blocked) are plain language, not errors
- [ ] Permission/approval UX matches the user's chosen trust tier (no prompts in dontAsk mode)
