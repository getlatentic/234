# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 keeps as a person's own agent at other Brands over PACT (turns/reach/): the conversation with each
Brand, the delegation the person gave there, the sign-ins waiting for them, and the receipts the Brands sent.
Every row belongs to a ledger owner key (turns/ledger_owner.py). The turn runner reads and writes these tables
with its own SQL; Django holds their schema and the person's Connected apps reads them."""

from django.db import models


class Conversation(models.Model):
    owner = models.CharField(max_length=32)
    brand = models.CharField(max_length=64)
    context_id = models.CharField(max_length=200)
    updated_at = models.BigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "brand"], name="one_conversation_per_brand")]

    def __str__(self) -> str:
        return f"{self.brand}/{self.context_id}"


class Delegation(models.Model):
    """The tokens a Brand issued for this person. They work only with 234's own personal-agent JWT."""

    owner = models.CharField(max_length=32)
    brand = models.CharField(max_length=64)
    brand_name = models.CharField(max_length=100)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, default="")
    scopes = models.CharField(max_length=500)
    expires_at = models.BigIntegerField()
    updated_at = models.BigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "brand"], name="one_delegation_per_brand")]

    def __str__(self) -> str:
        return f"{self.brand} {self.scopes}"


class SignIn(models.Model):
    """One device authorization a Brand started for this person, shown on a card until it ends."""

    PENDING, CONNECTED, DENIED, EXPIRED = "pending", "connected", "denied", "expired"

    id = models.CharField(primary_key=True, max_length=40)
    owner = models.CharField(max_length=32)
    brand = models.CharField(max_length=64)
    device_code = models.TextField()
    link = models.CharField(max_length=2000)
    scopes = models.CharField(max_length=500)
    interval = models.IntegerField()
    expires_at = models.BigIntegerField()
    polled_at = models.BigIntegerField(default=0)
    state = models.CharField(max_length=10, default=PENDING)
    created_at = models.BigIntegerField()

    def __str__(self) -> str:
        return self.id


class Receipt(models.Model):
    owner = models.CharField(max_length=32, db_index=True)
    brand = models.CharField(max_length=64)
    claims = models.JSONField()
    jws = models.TextField()
    created_at = models.BigIntegerField()

    def __str__(self) -> str:
        return f"{self.brand} {self.created_at}"
