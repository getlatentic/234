# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from django.test import Client


@pytest.mark.django_db
def test_the_page_says_it_is_a_test_while_providers_are_simulated(settings):
    settings.SIMULATION = True
    html = Client().get("/").content.decode()
    assert 'data-slot="test-box"' in html
    assert "This is a simulation" in html


@pytest.mark.django_db
def test_the_page_is_silent_once_providers_are_real(settings):
    settings.SIMULATION = False
    html = Client().get("/").content.decode()
    assert "test-box" not in html
    assert "This is a simulation" not in html
