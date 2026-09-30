---
name: feedback-agents-opus-5-5
description: "He wants every subagent/workflow agent on Opus 5.5 -- pin model 'claude-opus-5-5' explicitly; the default subagent model here is claude-opus-5, NOT the session model."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 8fde11a7-6340-4cdf-8f4e-02a95910c52b
  modified: 2026-09-29T21:54:10.746Z
---

User 2026-09-23, while a mapping workflow ran: *"pls use opus 5.5 agents."* Checking the agent transcripts showed
the workflow agents on `claude-opus-5` although the session itself was Opus 5.5 -- a default subagent model is
configured and it wins over "inherit". Relaunched with `model: 'claude-opus-5-5'` on every `agent()` call (and the
phase entry); transcripts then showed `claude-opus-5-5`.

**Why:** he picked the model on purpose; a silent downgrade is exactly the kind of thing he expects me to catch.

**2026-09-29 correction — the `model` opt on agent() is IGNORED.** Probes with `model: 'claude-sonnet-5-5'` and `model: 'claude-sonnet-5'` both ran on `claude-opus-5-5` (checked in the agent jsonl). So the default is Opus 5.5 now, and no pin is needed for it. A DIFFERENT model needs a custom agent type (`.claude/agents/*.md` frontmatter) passed as `agentType`. Documented agent() opts: label/phase/schema/effort ('low'…'max')/isolation/agentType. There is no Sonnet 5.5; the newest Sonnet is claude-sonnet-5.

**How to apply (historical):** in every Workflow script pass `model: 'claude-opus-5-5'` to each `agent()` and set it on the
`meta.phases` entries. After launching, grep the agent jsonl for `"model":` to confirm before reporting. The Agent
tool's `model` enum has no 5.5 option -- prefer a workflow (or check the result) when an Opus 5.5 subagent matters.
Related: [[feedback-tell-me-what-to-expect]].
