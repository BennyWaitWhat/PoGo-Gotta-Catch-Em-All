---
name: reference-pogo-tag-order
description: "How PoGo stores and saves the in-game tag ORDER (SortIndex + EditTag promise), the approved order, and the cull hook that keeps it"
metadata:
  node_type: memory
  type: reference
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-24T21:05:15.225Z
---

Tag order is settable and was set 2026-09-24 (user: "reorder all the tags, but the most active ones i use on top" -> "Ok"; "If not, explore the game and figure it out").

- `Holoholo.Rpc.PokemonTagProto`: Id @0x38 (UInt64), Name @0x40, Color @0x48, **SortIndex @0x4c** (Int32, **0-based**, 0 = top). Read offsets by field NAME live; never hardcode.
- Save = `TaggingRpcService.EditTag(editedTag, updateCacheSubscribers)` -> `IPromise<EditPokemonTagOutProto>` (concrete `RpcPromise`1`). Its base-class fields `completeCalled` / `completedValue` hold the server reply: `EditResult` list, 1 = Success, 5 = InvalidTagSortIndex. **Walk parent classes** to see them.
- The server accepted a temporary duplicate index (swap test), so it assigns indices outright; the script still re-sends EVERY tag in target order, which is correct under either reading.
- Frida gotcha: `il2cpp_gchandle_new` returns a **pointer** (Il2CppGCHandle, Unity 2021.2+). Declaring it `uint32` truncates it and `gchandle_get_target` faults.
- EditTag once threw right after an aborted run. One retry after 2 s is built in.
- Tool: `system/scripts/order_tags.py` (`--read`, `--dry-run`, `--test`, apply, `--selfcheck`). ORDER lives there: act-on tags, then PvP, then collection. Safety Hold is last.
- Cull hook: `sync_post_tags.py` runs `order_tags.keep_order` last, in its gated session. It only reads when the order is in place; when it drifted it re-sends and full_audit prints `tag order: ...`. **When you add a managed tag, add it to ORDER**; any unlisted tag is logged as "not in ORDER".
- Still unproven: that the order survives a server refetch (app restart). The hook re-checks after every cull, so the first idle cull with a proof restart will show it.

Related: [[pogo-tag-vocabulary-2026-09-09]], [[pogo-granular-tags-2026-09]], [[pogo-tag-system-2026]].
