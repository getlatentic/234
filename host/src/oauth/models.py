# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the authorization server keeps: clients, codes and tokens. Codes and tokens are stored as SHA-256
digests, so the database never holds a value that works."""

from django.db import models


class Client(models.Model):
    """A client registered by RFC 7591, or a client metadata document kept after it was fetched."""

    client_id = models.CharField(primary_key=True, max_length=512)
    name = models.CharField(max_length=100)
    redirect_uris = models.JSONField()
    fetched_at = models.BigIntegerField(default=0)
    created_at = models.BigIntegerField()

    def __str__(self) -> str:
        return self.name


class Code(models.Model):
    """An authorization code: used once, within a minute, by the client it was issued to."""

    digest = models.CharField(primary_key=True, max_length=64)
    client_id = models.CharField(max_length=512)
    owner = models.CharField(max_length=80)
    redirect_uri = models.CharField(max_length=2000)
    challenge = models.CharField(max_length=128)
    resource = models.CharField(max_length=300)
    scope = models.CharField(max_length=100)
    expires_at = models.BigIntegerField(db_index=True)

    def __str__(self) -> str:
        return self.digest[:8]


class Token(models.Model):
    """An access or refresh token. A refresh token is used once; the tokens one grant led to share a family,
    so a refresh token used twice ends them all."""

    ACCESS = "access"
    REFRESH = "refresh"

    digest = models.CharField(primary_key=True, max_length=64)
    kind = models.CharField(max_length=8)
    family = models.CharField(max_length=32, db_index=True)
    client_id = models.CharField(max_length=512)
    owner = models.CharField(max_length=80, db_index=True)
    resource = models.CharField(max_length=300)
    scope = models.CharField(max_length=100)
    expires_at = models.BigIntegerField(db_index=True)
    used = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.kind} {self.digest[:8]}"
