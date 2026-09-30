---
name: pogo-server-authority
description: "PoGo server state (quest progress, encounter tokens, currency, inventory) is authoritative — client-memory writes can't forge server-issued rewards."
metadata: 
  node_type: memory
  type: project
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

For PoGo, treat the **server as immovable** for quest progress, encounter tokens, currency, and inventory. Client-side memory writes change the UI but do NOT update server state; the server validates every claim against its own DB and silently rejects mismatches (the Promise resolves with a non-OK status, no exception thrown).

Hard-won specifics from the "Catching Some Z's" sleep-research saga:
- `QuestProto.Progress` (+0x48) is parent-only and reads 0 for `MULTI_PART` quests (QuestType=3). The real per-sub-quest progress is in `MultiPartQuestProto.SubQuests` (`RepeatedField<QuestProto>` at +0x10), reachable only via `il2cpp_runtime_invoke` on `QuestProto.get_MultiPart()`. Each sub-quest is itself a full `QuestProto`.
- The `CompleteQuestProto` RPC body is `(questId, subQuestId, choiceId, pokemonId)` — there is NO progress field. Encounter tokens for research-reward Pokémon are issued by the server in `CompleteQuestOutProto.Rewards`. So writing progress=target/status=2 in memory lets the user tap Claim, but the server rejects it and no tokens are granted — and even a forged encounter would fail the subsequent Encounter/CatchPokemon RPCs, which also validate against server-side records.
- Tried and all rejected: client memory writes, CompleteQuest RPC variants, UpdateQuestDetails resync, CompleteQueuedQuests, forging the response, and submitting forged sleep data (server requires signed records from paired Pokémon GO Plus+ hardware).

**Why:** PoGo is a closed-source live-service game with server-side anti-cheat; there is no client-side path to make the server issue rewards it didn't authorize.

**How to apply:** Never promise the user that client-side manipulation will yield server-issued rewards. For genuinely stuck server state (retired/expired pipelines), the only true fixes are a Niantic support ticket (the extracted per-sub-quest progress is solid evidence) or a `RemoveQuest` RPC (clears the slot, forfeits rewards). And first check the upstream input pipeline + community exploits (see [[feedback-verify-before-irreversible]]). Relates to [[pogo-source-of-truth-db-rules]], [[project-pogo-extract]].
