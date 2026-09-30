# SPDX-License-Identifier: AGPL-3.0-or-later
"""The menu as the card is given it: categories, the drawing for each item, and images only from origins
the view declares."""

from dataclasses import replace

from checkout.food.menu import ART, CATEGORIES, MENU
from checkout.food.view import menu_line, menu_view, view_meta

ORIGIN = "https://images.example-merchant.ng"
PHOTO = replace(MENU[0], image_url=f"{ORIGIN}/jollof.jpg")


class TestMenuItems:
    def test_every_item_has_a_category_and_a_drawing_the_card_knows(self):
        assert {m.category for m in MENU} == set(CATEGORIES)
        assert all(m.art in ART for m in MENU)

    def test_the_simulated_merchant_has_no_photos(self):
        assert all(m.image_url is None for m in MENU)


class TestMenuView:
    def test_leaves_out_an_image_the_view_does_not_declare(self):
        assert "image_url" not in menu_view([PHOTO], "a" * 32, ())["items"][0]
        assert "image_url" not in menu_view([PHOTO], "a" * 32, ("https://other.example",))["items"][0]

    def test_offers_an_image_from_a_declared_origin(self):
        assert menu_view([PHOTO], "a" * 32, (ORIGIN,))["items"][0]["image_url"] == f"{ORIGIN}/jollof.jpg"

    def test_does_not_treat_a_longer_host_as_the_declared_origin(self):
        lookalike = replace(MENU[0], image_url=f"{ORIGIN}.evil.example/x.jpg")
        assert "image_url" not in menu_view([lookalike], "a" * 32, (ORIGIN,))["items"][0]

    def test_gives_the_simulated_menu_no_image_field_at_all(self):
        assert all("image_url" not in item for item in menu_view(list(MENU), "a" * 32)["items"])


class TestViewMeta:
    def test_declares_no_origins_when_there_are_no_photos(self):
        assert view_meta() == {"prefersBorder": False}

    def test_declares_the_origins_images_load_from(self):
        assert view_meta((ORIGIN,)) == {"prefersBorder": False, "csp": {"resourceDomains": [ORIGIN]}}


class TestMenuLine:
    def test_is_one_line_that_names_no_item(self):
        line = menu_line(list(MENU))
        assert "\n" not in line and "11 items match" in line
        assert not any(m.name.split(",")[0] in line for m in MENU)
