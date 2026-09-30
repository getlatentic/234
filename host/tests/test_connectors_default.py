# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Django side reaches every connector the turn loop offers the model: a card of any of them is read
through the same list."""

from django.conf import settings

from turns.settings import Settings


def test_the_page_can_read_the_card_of_every_connector_the_model_is_offered():
    assert tuple(settings.CONNECTORS) == Settings.connectors
    assert "food-order" in settings.CONNECTORS
