# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps memory the person's: every query names its owner, nothing is saved but by the card's Save, what
is never kept is refused, a saved recipient's name and digits come from the bank and the server, and what the
model reads of a note is marked and quoted."""

from tools.mutations.model import SRC, Mutation

MEMORY = f"{SRC}/memory"
OWNERS = ["tests/test_memory_owners.py", "tests/test_memory_store_owners.py"]
PROPOSALS = ["tests/test_memory_proposals.py", "tests/test_memory_store_owners.py"]
NEVER = ["tests/test_memory_never_store.py"]
RECIPIENTS = ["tests/test_memory_recipients.py"]
TRANSFERS = ["tests/test_transfer_saved_recipient.py"]
TOOLS = ["tests/test_memory_tools.py"]
STORE = ["tests/test_memory_store.py", "tests/test_memory_index.py"]


def owner_query(guardrail: str, file: str, find: str, was: str = "owner = ?") -> Mutation:
    """A statement that names its owner, and the same statement with the owner left out of its WHERE."""
    return Mutation(
        f"{guardrail} names its owner",
        f"{MEMORY}/{file}",
        find,
        find.replace(was, "? IS NOT NULL", 1),
        OWNERS + STORE,
    )


MUTATIONS: list[Mutation] = [
    owner_query(
        "the memory index query",
        "store.py",
        '"SELECT id, kind, title, hook FROM memory_entry WHERE owner = ? AND deleted_at IS NULL "',
    ),
    owner_query(
        "the list of an owner's notes",
        "store.py",
        '"SELECT * FROM memory_entry WHERE owner = ? AND deleted_at IS NULL "',
    ),
    owner_query(
        "the count of an owner's notes",
        "store.py",
        '"SELECT COUNT(*) AS n FROM memory_entry WHERE owner = ? AND deleted_at IS NULL", owner',
    ),
    owner_query(
        "the lookup of one note",
        "store.py",
        '"SELECT * FROM memory_entry WHERE id = ? AND owner = ? AND deleted_at IS NULL", entry_id, owner',
        "AND owner = ?",
    ),
    owner_query(
        "the check for a title already taken",
        "store.py",
        '"SELECT id FROM memory_entry WHERE owner = ? AND kind = ? AND deleted_at IS NULL "',
    ),
    owner_query(
        "marking a note as used",
        "store.py",
        '"UPDATE memory_entry SET last_used = ? WHERE id = ? AND owner = ? AND deleted_at IS NULL",',
        "AND owner = ?",
    ),
    owner_query(
        "the search",
        "store.py",
        '"WHERE memory_fts MATCH ? AND e.owner = ? AND e.deleted_at IS NULL ORDER BY f.rank LIMIT ?",',
        "e.owner = ?",
    ),
    owner_query(
        "forgetting a note",
        "store.py",
        '"UPDATE memory_entry SET deleted_at = ?, updated_at = ? WHERE id = ? AND owner = ? "',
        "AND owner = ?",
    ),
    owner_query(
        "editing a note in place",
        "store.py",
        '"UPDATE memory_entry SET title = ?, hook = ?, updated_at = ? WHERE id = ? AND owner = ? "',
        "AND owner = ?",
    ),
    owner_query(
        "deleting all of an owner's notes",
        "store.py",
        '("DELETE FROM memory_entry WHERE owner = ?", (owner,)),',
    ),
    owner_query(
        "deleting all of an owner's proposals",
        "store.py",
        '("DELETE FROM memory_proposal WHERE owner = ?", (owner,)),',
    ),
    owner_query(
        "the lookup of a proposal",
        "proposals.py",
        '"SELECT * FROM memory_proposal WHERE id = ? AND owner = ?", proposal_id, owner',
        "AND owner = ?",
    ),
    owner_query(
        "the discarding of the oldest unanswered proposals",
        "proposals.py",
        "\"SELECT id FROM memory_proposal WHERE owner = ? AND state = 'pending' \"",
    ),
    owner_query(
        "writing a confirmed note",
        "proposals.py",
        "\"FROM memory_proposal p WHERE p.id = ? AND p.owner = ? AND p.op = 'remember' "
        "AND p.state = 'pending' \"",
        "p.owner = ?",
    ),
    owner_query(
        "changing a confirmed note",
        "proposals.py",
        '"WHERE id = (SELECT target_id FROM memory_proposal WHERE id = ?) AND owner = ? '
        'AND deleted_at IS NULL "',
        "AND owner = ?",
    ),
    owner_query(
        "reading the proposal behind a change",
        "proposals.py",
        "\"AND EXISTS (SELECT 1 FROM memory_proposal WHERE id = ? AND owner = ? AND op = 'update' \"",
        "AND owner = ?",
    ),
    owner_query(
        "marking a proposal as decided",
        "proposals.py",
        '"UPDATE memory_proposal SET state = ?, decided_at = ? WHERE id = ? AND owner = ? AND state = ? "',
        "AND owner = ?",
    ),
    owner_query(
        "discarding a proposal",
        "proposals.py",
        "\"UPDATE memory_proposal SET state = 'discarded', decided_at = ? WHERE id = ? AND owner = ? \"",
        "AND owner = ?",
    ),
    owner_query(
        "restoring a forgotten note",
        "proposals.py",
        '"UPDATE memory_entry SET deleted_at = NULL, updated_at = ? WHERE id = ? AND owner = ? "',
        "AND owner = ?",
    ),
    owner_query(
        "marking a forget as undone",
        "proposals.py",
        "\"UPDATE memory_proposal SET state = 'undone', decided_at = ? WHERE id = ? AND owner = ? \"",
        "AND owner = ?",
    ),
    Mutation(
        "a call to the memory connector without a memory owner is refused",
        f"{SRC}/http.py",
        "if given is None and calls_a_tool and connector == MEMORY_CONNECTOR:",
        "if False:",
        ["tests/test_memory_owners.py"],
    ),
    Mutation(
        "the memory owner is taken from its own header and from nowhere else",
        f"{SRC}/http.py",
        'given = _checked_key(headers.get(MEMORY_OWNER_HEADER), "memory owner")',
        'given = _checked_key(headers.get(MEMORY_OWNER_HEADER) or headers.get("x-ledger-owner"), '
        '"memory owner")',
        ["tests/test_memory_owners.py"],
    ),
    Mutation(
        "remember writes no note: it only makes a proposal",
        f"{MEMORY}/proposing.py",
        "proposal = await self._ctx.proposals.create(owner, REMEMBER, None, payload)",
        "proposal = await self._ctx.proposals.create(owner, REMEMBER, None, payload)\n"
        "        await self._ctx.proposals.apply(owner, proposal)",
        PROPOSALS,
    ),
    Mutation(
        "update changes no note: it only makes a proposal",
        f"{MEMORY}/proposing.py",
        "proposal = await self._ctx.proposals.create(owner, UPDATE, entry.id, payload)",
        "proposal = await self._ctx.proposals.create(owner, UPDATE, entry.id, payload)\n"
        "        await self._ctx.proposals.apply(owner, proposal)",
        PROPOSALS,
    ),
    Mutation(
        "a save needs the card's token",
        f"{MEMORY}/deciding.py",
        "if not self._ctx.proposals.token_is_valid(owner, proposal_id, token):",
        "if False:",
        PROPOSALS,
    ),
    Mutation(
        "a note is written only from a proposal that is still pending",
        f"{MEMORY}/proposals.py",
        "AND p.op = 'remember' AND p.state = 'pending' \"",
        "AND p.op = 'remember' AND p.state IS NOT NULL \"",
        PROPOSALS,
    ),
    Mutation(
        "a note is written only from a proposal that has not expired",
        f"{MEMORY}/proposals.py",
        '"AND p.expires_at > ? "',
        '"AND ? IS NOT NULL "',
        PROPOSALS,
    ),
    Mutation(
        "a note is written only while the owner has room",
        f"{MEMORY}/proposals.py",
        '"AND (SELECT COUNT(*) FROM memory_entry WHERE owner = p.owner AND deleted_at IS NULL) < ?"',
        '"AND (SELECT COUNT(*) FROM memory_entry WHERE owner = p.owner AND deleted_at IS NULL) '
        '< ? + 1000000"',
        STORE,
    ),
    Mutation(
        "a forgotten note is brought back only while the owner has room",
        f"{MEMORY}/proposals.py",
        '"AND (SELECT COUNT(*) FROM memory_entry WHERE owner = ? AND deleted_at IS NULL) < ?"',
        '"AND (SELECT COUNT(*) FROM memory_entry WHERE owner = ? AND deleted_at IS NULL) < ? + 1000000"',
        STORE,
    ),
    Mutation(
        "a proposal that has expired is not saved",
        f"{MEMORY}/deciding.py",
        "if proposal.expired(self._ctx.clock.now()):",
        "if False:",
        PROPOSALS,
    ),
    Mutation(
        "a proposal is refused when the owner has no room, before the card is shown",
        f"{MEMORY}/proposing.py",
        "if await store.count_live(owner) >= store.settings.max_entries:",
        "if False:",
        STORE,
    ),
    Mutation(
        "the body of a note has a size cap",
        f"{MEMORY}/fields.py",
        "if len(cleaned.encode()) > max_bytes:",
        "if False:",
        STORE,
    ),
    Mutation(
        "a forgotten note is purged only after the retention period",
        f"{MEMORY}/store.py",
        "(now - self.settings.retention_ms, PURGE_BATCH),",
        "(now + 10**12, PURGE_BATCH),",
        STORE,
    ),
    Mutation(
        "the memory index stays within its token budget",
        f"{MEMORY}/index.py",
        "if used + cost + reserve > budget_tokens:",
        "if False:",
        STORE,
    ),
    Mutation(
        "a card number is never kept",
        f"{MEMORY}/never_store.py",
        "if _is_card(digits):",
        "if False:",
        NEVER,
    ),
    Mutation(
        "a long number that is not a phone number in a phone-titled note is never kept",
        f"{MEMORY}/never_store.py",
        "if len(digits) > _LONGEST_NAME_RUN and not _is_phone(digits, kind, title):",
        "if False:",
        NEVER,
    ),
    Mutation(
        "a PIN, a code, a password or a key word is never kept",
        f"{MEMORY}/never_store.py",
        "if _SECRET_WORDS.search(text):",
        "if False:",
        NEVER,
    ),
    Mutation(
        "a BVN or a NIN is never kept",
        f"{MEMORY}/never_store.py",
        "if _BVN_OR_NIN.search(text):",
        "if False:",
        NEVER,
    ),
    Mutation(
        "an API key shape is never kept",
        f"{MEMORY}/never_store.py",
        "if _KEY_SHAPES.search(text):",
        "if False:",
        NEVER,
    ),
    Mutation(
        "a new preference or fact is checked against what is never kept",
        f"{MEMORY}/proposing.py",
        "assert_storable(kind, title, clean_line, text)",
        "None",
        NEVER,
    ),
    Mutation(
        "a new recipient is checked against what is never kept",
        f"{MEMORY}/proposing.py",
        "assert_storable(kind, title, holder.hook, text)",
        "None",
        NEVER,
    ),
    Mutation(
        "a change to a preference or a fact is checked against what is never kept",
        f"{MEMORY}/proposing.py",
        "assert_storable(entry.kind, title, line, text)",
        "None",
        NEVER,
    ),
    Mutation(
        "a change to a recipient is checked against what is never kept",
        f"{MEMORY}/proposing.py",
        "assert_storable(entry.kind, title, holder.hook, text)",
        "None",
        NEVER,
    ),
    Mutation(
        "a proposal is checked against what is never kept again when it is saved",
        f"{MEMORY}/deciding.py",
        'assert_storable(payload["kind"], payload["title"], payload["hook"], payload["body"])',
        "None",
        NEVER,
    ),
    Mutation(
        "an edit in the page's list is checked against what is never kept",
        f"{MEMORY}/account.py",
        "assert_storable(entry.kind, new_title, new_hook, entry.body)",
        "None",
        STORE,
    ),
    Mutation(
        "a recipient's saved name is the bank's answer, not the model's",
        f"{MEMORY}/recipient.py",
        "name = clean_name(await account_holder(paystack, account, chosen.code))",
        'name = "MUM"',
        RECIPIENTS,
    ),
    Mutation(
        "a recipient's bank is exactly one bank on Paystack's list",
        f"{MEMORY}/recipient.py",
        "chosen = choose_bank(bank, None)",
        'chosen = type("Chosen", (), {"code": "058", "name": bank})()',
        RECIPIENTS,
    ),
    Mutation(
        "a recipient is saved only while the bank still gives the name the card showed",
        f"{MEMORY}/deciding.py",
        'return None if same_name(name, payload["account_name"]) else NAME_CHANGED',
        "return None",
        RECIPIENTS,
    ),
    Mutation(
        "a transfer to a saved recipient takes no digits from the model",
        f"{SRC}/flows/saved_recipient.py",
        "if any(value is not None for value in (account_number, bank, bank_code)):",
        "if False:",
        TRANSFERS,
    ),
    Mutation(
        "a saved recipient is loaded for its owner and for nobody else",
        f"{SRC}/flows/saved_recipient.py",
        "ctx.memory.get(ctx.ledger.owner(), memory_id)",
        'ctx.memory.get("0" * 32, memory_id)',
        TRANSFERS,
    ),
    Mutation(
        "a transfer to a saved recipient is refused when the bank gives another name",
        f"{SRC}/flows/saved_recipient.py",
        'if not same_name(name, saved.account_name or ""):',
        "if False:",
        TRANSFERS,
    ),
    Mutation(
        "what the model recalls is marked as notes and not instructions",
        f"{MEMORY}/reading.py",
        'return "\\n".join([UNTRUSTED, *blocks])',
        'return "\\n".join(blocks)',
        TOOLS,
    ),
    Mutation(
        "every field of a recalled note is quoted as data",
        f"{MEMORY}/reading.py",
        'f"{name}: {json.dumps(value, ensure_ascii=False)}" for name, value in _shown(entry)',
        'f"{name}: {value}" for name, value in _shown(entry)',
        TOOLS,
    ),
    Mutation(
        "a title cannot close the link of its index line",
        f"{MEMORY}/fields.py",
        '_BRACKETS = str.maketrans({"[": "(", "]": ")", "`": "\'"})',
        "_BRACKETS = str.maketrans({})",
        TOOLS,
    ),
    Mutation(
        "the model is never given a recipient's whole account number",
        f"{MEMORY}/entry.py",
        '"account_masked": mask_account(self.account_number),',
        '"account_masked": self.account_number,',
        RECIPIENTS,
    ),
]
