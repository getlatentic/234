# SPDX-License-Identifier: AGPL-3.0-or-later
"""What signing in does with the anonymous visitor's chats: they become the account's.

Only the owner column changes (and the visitor's guest passes move with them), never a row of a chat's log,
so nothing is copied, merged or lost, and an account that already has chats simply has more. Every statement
is idempotent: a sign-in that failed half-way is repeated by the next one.

A quote made under the anonymous key stays bound to it (the connectors scope every quote by owner). An
approval card still open in an adopted chat therefore asks the connector under the account's key, the
connector does not know the quote, and the card shows its "No longer available" state. Nothing has been paid
or approved by that.
"""

from django.db.models import Q

from chat.models import Access, Chat


def adopt(visitor_owner: str, account_owner: str) -> int:
    """Moves the visitor's chats and guest passes to the account; returns how many chats moved."""
    moved = Chat.objects.filter(owner=visitor_owner).update(owner=account_owner)
    already = Access.objects.filter(visitor=account_owner).values("chat_id")
    Access.objects.filter(visitor=visitor_owner).filter(
        Q(chat__owner=account_owner) | Q(chat_id__in=already)
    ).delete()
    Access.objects.filter(visitor=visitor_owner).update(visitor=account_owner)
    return moved
