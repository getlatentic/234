# SPDX-License-Identifier: AGPL-3.0-or-later
"""A personal agent's conversations: which Brand and which User (PACT §4.2) each chat belongs to, and the
reply to each message, so a retried messageId gets the stored reply (§4.3)."""

from django.db import models

from chat.models import Chat


class Context(models.Model):
    chat = models.OneToOneField(Chat, primary_key=True, on_delete=models.CASCADE, related_name="pact")
    brand = models.CharField(max_length=64)
    owner = models.CharField(max_length=80, db_index=True)

    def __str__(self) -> str:
        return f"{self.brand}/{self.chat_id}"


class Reply(models.Model):
    """`message` is empty until the reply is known: a retry before then is refused."""

    context = models.ForeignKey(Context, on_delete=models.CASCADE, related_name="replies")
    message_id = models.CharField(max_length=200)
    message = models.JSONField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["context", "message_id"], name="one_reply_per_message")
        ]

    def __str__(self) -> str:
        return self.message_id
