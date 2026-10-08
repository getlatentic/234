# SPDX-License-Identifier: AGPL-3.0-or-later
"""The payer group of a chat, added as 0002 added its connectors: ALTER TABLE ADD COLUMN, the one change D1
applies to a table with rows that other tables point at."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("chat", "0002_chat_connectors")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE chat_chat ADD COLUMN payer_group varchar(32) NOT NULL DEFAULT ''",
                    reverse_sql=migrations.RunSQL.noop,
                )
            ],
            state_operations=[
                migrations.AddField(
                    model_name="chat",
                    name="payer_group",
                    field=models.CharField(blank=True, default="", max_length=32),
                )
            ],
        )
    ]
