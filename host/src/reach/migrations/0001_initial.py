# SPDX-License-Identifier: AGPL-3.0-or-later

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Receipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("owner", models.CharField(db_index=True, max_length=32)),
                ("brand", models.CharField(max_length=64)),
                ("claims", models.JSONField()),
                ("jws", models.TextField()),
                ("created_at", models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name="SignIn",
            fields=[
                (
                    "id",
                    models.CharField(max_length=40, primary_key=True, serialize=False),
                ),
                ("owner", models.CharField(max_length=32)),
                ("brand", models.CharField(max_length=64)),
                ("device_code", models.TextField()),
                ("link", models.CharField(max_length=2000)),
                ("scopes", models.CharField(max_length=500)),
                ("interval", models.IntegerField()),
                ("expires_at", models.BigIntegerField()),
                ("polled_at", models.BigIntegerField(default=0)),
                ("state", models.CharField(default="pending", max_length=10)),
                ("created_at", models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name="Conversation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("brand", models.CharField(max_length=64)),
                ("context_id", models.CharField(max_length=200)),
                ("updated_at", models.BigIntegerField()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner", "brand"), name="one_conversation_per_brand"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Delegation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("owner", models.CharField(max_length=32)),
                ("brand", models.CharField(max_length=64)),
                ("brand_name", models.CharField(max_length=100)),
                ("access_token", models.TextField()),
                ("refresh_token", models.TextField(blank=True, default="")),
                ("scopes", models.CharField(max_length=500)),
                ("expires_at", models.BigIntegerField()),
                ("updated_at", models.BigIntegerField()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner", "brand"), name="one_delegation_per_brand"
                    )
                ],
            },
        ),
    ]
