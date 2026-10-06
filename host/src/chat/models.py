# SPDX-License-Identifier: AGPL-3.0-or-later
import secrets

from django.db import models

from turns.eventlog import Event as LoggedEvent


def new_chat_id() -> str:
    return secrets.token_hex(16)


class Chat(models.Model):
    """One conversation. Its content is the event log; the Chat row says who may see it."""

    id = models.CharField(primary_key=True, max_length=32, default=new_chat_id, editable=False)
    owner = models.CharField(max_length=80, db_index=True)
    title = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # The connectors this chat's model may use, comma-separated; blank is every one (pact/brands.py).
    connectors = models.CharField(max_length=200, blank=True, default="")

    def __str__(self) -> str:
        return self.id


class Access(models.Model):
    """A visitor who was let into a chat they do not own, by its share link."""

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="guests")
    visitor = models.CharField(max_length=80)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["chat", "visitor"], name="one_access_per_visitor")]

    def __str__(self) -> str:
        return f"{self.visitor} in {self.chat_id}"


class Event(models.Model):
    """One entry of a chat's append-only log. Appended by the chat's runner in turns/eventlog.py with
    plain SQL, read here; (chat, seq) is unique and gapless."""

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="events")
    seq = models.PositiveIntegerField()
    type = models.CharField(max_length=24)
    task = models.CharField(max_length=32, blank=True, default="")
    ref = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField()
    created_at = models.BigIntegerField()

    class Meta:
        ordering = ["seq"]
        constraints = [models.UniqueConstraint(fields=["chat", "seq"], name="one_event_per_seq")]
        indexes = [models.Index(fields=["task"]), models.Index(fields=["ref"])]

    def __str__(self) -> str:
        return f"{self.chat_id}#{self.seq} {self.type}"

    def as_logged(self) -> LoggedEvent:
        return LoggedEvent(
            self.seq, self.type, self.task or None, self.ref or None, self.payload, self.created_at
        )


class Budget(models.Model):
    """Model calls made in one scope on one UTC day: the daily cap of a visitor, or of everyone."""

    scope = models.CharField(max_length=80)
    day = models.DateField()
    used = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["scope", "day"], name="one_budget_per_day")]

    def __str__(self) -> str:
        return f"{self.scope} {self.day}: {self.used}"
