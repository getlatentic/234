# SPDX-License-Identifier: AGPL-3.0-or-later
"""A research run: its chat's parent (ALTER TABLE ADD COLUMN, as 0002 and 0003 did) and the table that says how
the run stands."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("chat", "0003_chat_payer_group")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE chat_chat ADD COLUMN parent varchar(32) NOT NULL DEFAULT ''",
                    reverse_sql=migrations.RunSQL.noop,
                )
            ],
            state_operations=[
                migrations.AddField(
                    model_name="chat",
                    name="parent",
                    field=models.CharField(blank=True, default="", max_length=32),
                )
            ],
        ),
        migrations.CreateModel(
            name="Research",
            fields=[
                (
                    "chat",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="research",
                        serialize=False,
                        to="chat.chat",
                    ),
                ),
                ("parent", models.CharField(db_index=True, max_length=32)),
                ("owner", models.CharField(max_length=80)),
                ("question", models.CharField(max_length=500)),
                ("status", models.CharField(default="running", max_length=12)),
                ("created_at", models.BigIntegerField()),
                ("deadline_at", models.BigIntegerField()),
                ("finished_at", models.BigIntegerField(null=True)),
            ],
            options={"indexes": [models.Index(fields=["owner", "created_at"], name="chat_resear_owner_ffeddc_idx")]},
        ),
    ]
