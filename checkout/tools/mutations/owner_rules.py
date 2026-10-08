# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each visitor's own daily limit: what scopes the ledger by owner, and that only the host names the owner."""

from tools.mutations.model import SRC, Mutation

BOOKS = ["tests/test_ledger_owners.py", "tests/test_ledger_races.py"]
CALLS = ["tests/test_owner_tools.py"]
CHECKOUT = ["tests/test_owner_checkout.py"]
LEDGER_FILE = f"{SRC}/ledger.py"

MUTATIONS: list[Mutation] = [
    Mutation(
        "the daily sum counts only the owner's approved spend (quote time and cards)",
        LEDGER_FILE,
        'f"WHERE owner = ? AND approved_at >= ? AND state IN ({_SPENDING_SQL})",',
        'f"WHERE ? IS NOT NULL AND approved_at >= ? AND state IN ({_SPENDING_SQL})",',
        BOOKS + CALLS,
    ),
    Mutation(
        "the daily sum inside the approval statement counts only the owner's approved spend",
        LEDGER_FILE,
        'f"FROM quotes WHERE owner = ? AND approved_at >= ? AND state IN ({_SPENDING_SQL})) <= ? "',
        'f"FROM quotes WHERE ? IS NOT NULL AND approved_at >= ? AND state IN ({_SPENDING_SQL})) <= ? "',
        BOOKS + CALLS,
    ),
    Mutation(
        "a quote is looked up only for its owner",
        LEDGER_FILE,
        '"SELECT * FROM quotes WHERE id = ? AND owner = ?", quote_id, owner',
        '"SELECT * FROM quotes WHERE id = ? AND ? IS NOT NULL", quote_id, owner',
        BOOKS + CALLS,
    ),
    Mutation(
        "an approval takes only the owner's own quote (inside the approval statement)",
        LEDGER_FILE,
        '"WHERE id = ? AND owner = ? AND connector = ?',
        '"WHERE id = ? AND ? IS NOT NULL AND connector = ?',
        BOOKS,
    ),
    Mutation(
        "a state change takes only the owner's own quote",
        LEDGER_FILE,
        'f"progress = json_patch(progress, ?) WHERE id = ? AND owner = ? AND state IN ({marks})",',
        'f"progress = json_patch(progress, ?) WHERE id = ? AND ? IS NOT NULL AND state IN ({marks})",',
        BOOKS,
    ),
    Mutation(
        "an idempotency key is stored with its owner (creating a quote)",
        LEDGER_FILE,
        "self._scoped_key(new.idempotency_key),",
        "new.idempotency_key,",
        BOOKS + CALLS,
    ),
    Mutation(
        "an idempotency key is looked up with its owner (replaying a quote)",
        LEDGER_FILE,
        "self._scoped_key(key),",
        "key,",
        BOOKS + CALLS,
    ),
    Mutation(
        "a call that names no owner is refused when no default owner is set",
        LEDGER_FILE,
        'if owner is None:\n            raise DomainError("OWNER_REQUIRED"',
        'if False:\n            raise DomainError("OWNER_REQUIRED"',
        BOOKS,
    ),
    Mutation(
        "the owner never changes after a quote is made (database trigger)",
        "migrations/0007_payer_group.sql",
        "created_at, expires_at, owner, payer_group ON quotes",
        "created_at, expires_at, payer_group ON quotes",
        BOOKS,
    ),
    Mutation(
        "the owner is taken from the host's header and from nowhere else",
        f"{SRC}/http.py",
        "given = headers.get(OWNER_HEADER)",
        'given = ((message.get("params") or {}).get("_meta") or {}).get("owner") or '
        "headers.get(OWNER_HEADER)",
        CALLS,
    ),
    Mutation(
        "a tool call without an owner is refused when the configuration requires one",
        f"{SRC}/http.py",
        "if given is None and calls_a_tool and app.settings.require_owner:",
        "if False:",
        CALLS,
    ),
    Mutation(
        "a malformed owner is refused",
        f"{SRC}/http.py",
        "if given is not None and not is_owner_key(given):",
        "if False:",
        CALLS,
    ),
    Mutation(
        "an owner is 32 lowercase hex characters",
        f"{SRC}/owner.py",
        '_SHAPE = re.compile(r"[0-9a-f]{32}")',
        '_SHAPE = re.compile(r".+")',
        BOOKS + CALLS,
    ),
    Mutation(
        "the public deployment requires an owner on every tool call",
        "wrangler.public.jsonc",
        '"REQUIRE_OWNER": "1",',
        '"REQUIRE_OWNER": "0",',
        ["tests/test_public_config.py"],
    ),
    Mutation(
        "a checkout reference is random",
        f"{SRC}/ids.py",
        'return f"qt-{secrets.token_hex(10)}"',
        'return f"qt-{secrets.randbits(10):020x}"',
        CHECKOUT,
    ),
]
