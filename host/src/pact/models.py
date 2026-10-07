# SPDX-License-Identifier: AGPL-3.0-or-later
"""A personal agent's conversations: which Brand and which User (PACT §4.2) each chat belongs to, and the
reply to each message, so a retried messageId gets the stored reply (§4.3). For PACT Delegated (§5): the
device authorizations a person approves, the grants they lead to, and the refresh tokens of a grant. Device
codes and refresh tokens are stored as SHA-256 digests, so the database never holds a value that works."""

from django.db import models

from chat.models import Chat


class Context(models.Model):
    chat = models.OneToOneField(Chat, primary_key=True, on_delete=models.CASCADE, related_name="pact")
    brand = models.CharField(max_length=64)
    owner = models.CharField(max_length=80, db_index=True)
    account = models.CharField(max_length=80, blank=True, default="")
    """The 234 account the context runs as, once a delegation token has been sent in it; empty before."""
    delegated_chat = models.ForeignKey(
        Chat,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    """For a context begun without delegation: the account's own chat its turns run in from then on. The
    first chat keeps its owner, so a link to it never opens the account's chat."""

    def __str__(self) -> str:
        return f"{self.brand}/{self.chat_id}"

    @property
    def running_chat_id(self) -> str:
        return self.delegated_chat_id or self.chat_id


class Reply(models.Model):
    """`answer` (the reply body: a message or a step-up task) is empty until it is known: a retry before then
    is refused."""

    context = models.ForeignKey(Context, on_delete=models.CASCADE, related_name="replies")
    message_id = models.CharField(max_length=200)
    answer = models.JSONField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["context", "message_id"], name="one_reply_per_message")
        ]

    def __str__(self) -> str:
        return self.message_id


class Grant(models.Model):
    """What a person allowed one personal agent's User to do as their account at one Brand (§5.3, §5.4)."""

    id = models.CharField(primary_key=True, max_length=40)
    brand = models.CharField(max_length=64)
    pa_issuer = models.CharField(max_length=512)
    pa_owner = models.CharField(max_length=80, db_index=True)
    account = models.CharField(max_length=80, db_index=True)
    scopes = models.CharField(max_length=200)
    created_at = models.BigIntegerField()
    expires_at = models.BigIntegerField()
    revoked = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.id


class DeviceAuthorization(models.Model):
    """One RFC 8628 request: pending until the person signs in and decides, then taken once by its agent."""

    PENDING, APPROVED, DENIED, TAKEN = "pending", "approved", "denied", "taken"

    digest = models.CharField(primary_key=True, max_length=64)
    user_code = models.CharField(max_length=9, unique=True)
    brand = models.CharField(max_length=64)
    pa_issuer = models.CharField(max_length=512)
    pa_owner = models.CharField(max_length=80)
    scopes = models.CharField(max_length=200)
    status = models.CharField(max_length=8, default=PENDING)
    granted = models.CharField(max_length=200, blank=True, default="")
    account = models.CharField(max_length=80, blank=True, default="")
    expires_at = models.BigIntegerField(db_index=True)
    polled_at = models.BigIntegerField(default=0)

    def __str__(self) -> str:
        return self.user_code


class RefreshToken(models.Model):
    """Used once: a refresh token used twice ends its grant."""

    digest = models.CharField(primary_key=True, max_length=64)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="refresh_tokens")
    used = models.BooleanField(default=False)
    expires_at = models.BigIntegerField()

    def __str__(self) -> str:
        return self.digest[:8]
