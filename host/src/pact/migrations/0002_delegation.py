# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT Delegated: device authorizations, grants and refresh tokens, the account a context runs as and the
chat it runs in, and a reply's stored body renamed to what it now is. The columns change with ALTER TABLE, not Django's rebuild of the table, which D1 refuses for a table
other rows point at (chat/migrations/0002_chat_connectors.py)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pact", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceAuthorization",
            fields=[
                (
                    "digest",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("user_code", models.CharField(max_length=9, unique=True)),
                ("brand", models.CharField(max_length=64)),
                ("pa_issuer", models.CharField(max_length=512)),
                ("pa_owner", models.CharField(max_length=80)),
                ("scopes", models.CharField(max_length=200)),
                ("status", models.CharField(default="pending", max_length=8)),
                ("granted", models.CharField(blank=True, default="", max_length=200)),
                ("account", models.CharField(blank=True, default="", max_length=80)),
                ("expires_at", models.BigIntegerField(db_index=True)),
                ("polled_at", models.BigIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="Grant",
            fields=[
                (
                    "id",
                    models.CharField(max_length=40, primary_key=True, serialize=False),
                ),
                ("brand", models.CharField(max_length=64)),
                ("pa_issuer", models.CharField(max_length=512)),
                ("pa_owner", models.CharField(db_index=True, max_length=80)),
                ("account", models.CharField(db_index=True, max_length=80)),
                ("scopes", models.CharField(max_length=200)),
                ("created_at", models.BigIntegerField()),
                ("expires_at", models.BigIntegerField()),
                ("revoked", models.BooleanField(default=False)),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE pact_context ADD COLUMN account varchar(80) NOT NULL DEFAULT ''",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "ALTER TABLE pact_context ADD COLUMN delegated_chat_id varchar(32) NULL",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "ALTER TABLE pact_reply RENAME COLUMN message TO answer",
                    reverse_sql="ALTER TABLE pact_reply RENAME COLUMN answer TO message",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="context",
                    name="account",
                    field=models.CharField(blank=True, default="", max_length=80),
                ),
                migrations.AddField(
                    model_name="context",
                    name="delegated_chat",
                    field=models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="chat.chat",
                    ),
                ),
                migrations.RenameField(model_name="reply", old_name="message", new_name="answer"),
            ],
        ),
        migrations.CreateModel(
            name="RefreshToken",
            fields=[
                (
                    "digest",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("used", models.BooleanField(default=False)),
                ("expires_at", models.BigIntegerField()),
                (
                    "grant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refresh_tokens",
                        to="pact.grant",
                    ),
                ),
            ],
        ),
    ]
