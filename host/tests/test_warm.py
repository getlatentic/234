# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from django.template import engines
from django.template.base import Template
from django.urls import get_resolver

from config.warm import warm_up

pytestmark = pytest.mark.django_db


def _forget_compiled_templates() -> None:
    for loader in engines["django"].engine.template_loaders:
        loader.reset()


@pytest.fixture
def compiled(monkeypatch):
    names: list[str] = []
    original = Template.compile_nodelist

    def counting(self):
        names.append(self.name)
        return original(self)

    monkeypatch.setattr(Template, "compile_nodelist", counting)
    _forget_compiled_templates()
    return names


def test_a_page_compiles_its_templates_when_nothing_was_warmed(visitor, compiled):
    assert visitor.client.get("/").status_code == 200
    assert "chat/chat.html" in compiled


def test_after_the_warm_up_no_page_compiles_a_template(visitor, compiled):
    warm_up()
    pages = {"chat/chat.html", "chat/_item.html", "chat/_sheet.html", "accounts/_account.html"}
    assert pages <= set(compiled)
    compiled.clear()
    assert visitor.client.get("/").status_code == 200
    assert compiled == []


def test_the_warm_up_leaves_the_url_tables_built():
    warm_up()
    assert get_resolver()._populated
