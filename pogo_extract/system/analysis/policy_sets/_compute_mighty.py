"""Compute the protected uid_hex set for keep-rule "mighty" (KEEP_POLICY.md §5).

RULE: Keep ALL fresh_is_strong=1 (the 'Mighty'/'is_strong' keep-reason; uncapped).
Scope: pokemon table, in_bag=1.
READ-ONLY. Writes one uid_hex per line to mighty.txt (sorted, deterministic).
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "..", "..", "..", "pokemon.db")
OUT = os.path.join(os.path.dirname(__file__), "mighty.txt")


def main():
    db = sqlite3.connect(os.path.abspath(DB))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    rows = cur.execute(
        "SELECT uid_hex FROM pokemon "
        "WHERE in_bag = 1 AND fresh_is_strong = 1 "
        "AND uid_hex IS NOT NULL"
    ).fetchall()
    uids = sorted({r["uid_hex"] for r in rows})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for u in uids:
            f.write(u + "\n")
    print(f"mighty: {len(uids)} uid(s) -> {os.path.abspath(OUT)}")
    db.close()


if __name__ == "__main__":
    main()
