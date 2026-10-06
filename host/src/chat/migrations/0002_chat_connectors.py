# SPDX-License-Identifier: AGPL-3.0-or-later
"""The connectors a chat may use (blank: every one). Django would add the column on SQLite by rebuilding the
table (CREATE new, copy, DROP chat_chat, rename); D1 enforces foreign keys and every event points at
chat_chat, so the column is added with the one change D1 applies to a table with rows: ALTER TABLE ADD COLUMN."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("chat", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE chat_chat ADD COLUMN connectors varchar(200) NOT NULL DEFAULT ''",
                    reverse_sql=migrations.RunSQL.noop,
                )
            ],
            state_operations=[
                migrations.AddField(
                    model_name="chat",
                    name="connectors",
                    field=models.CharField(blank=True, default="", max_length=200),
                )
            ],
        )
    ]
