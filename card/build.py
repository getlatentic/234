# SPDX-License-Identifier: AGPL-3.0-or-later
"""Renders a card: Django templates for the markup, the Tailwind CLI's CSS and two small scripts
inlined, so the card is one self-contained HTML document with no network.

usage: uv run --project ../checkout python card/build.py [out] [--client hand|official] [--card menu]
       (needs `npm install` at the repo root). The default card is the approval card; `--card menu` is
       the menu card. The hand client is mcp-app.js; the official one is the ext-apps App class,
       bundled with esbuild into the same McpApp surface.
"""

import subprocess
import sys
from pathlib import Path

import django
from django.conf import settings
from django.template import engines

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CARD_DIR = ROOT / "checkout" / "src" / "checkout" / "card"
DEFAULT_OUT = CARD_DIR / "card.html"
MENU = HERE / "menu"


def design_tokens() -> None:
    """The stylesheets import the generated design tokens, so they are made first."""
    subprocess.run(["node", str(ROOT / "design" / "build.mjs")], check=True)


def tailwind_css(source: Path) -> str:
    design_tokens()
    binary = ROOT / "node_modules" / ".bin" / "tailwindcss"
    result = subprocess.run(
        [str(binary), "-i", str(source), "--minify"],
        cwd=source.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def official_client() -> str:
    binary = ROOT / "node_modules" / ".bin" / "esbuild"
    result = subprocess.run(
        [str(binary), str(HERE / "static" / "mcp-app-official.src.js"), "--bundle", "--minify",
         "--format=iife", "--target=es2022"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return result.stdout.replace("</script", "<\\/script")


def _engine():
    if not settings.configured:
        dirs = [str(HERE / "templates"), str(MENU / "templates")]
        settings.configure(
            TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": dirs}],
        )
        django.setup()
    return engines["django"]


def menu_bundle() -> str:
    binary = ROOT / "node_modules" / ".bin" / "esbuild"
    result = subprocess.run(
        [str(binary), str(MENU / "src" / "main.js"), "--bundle", "--minify", "--format=iife", "--target=es2022"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return result.stdout.replace("</script", "<\\/script")


def render(client: str = "hand") -> str:
    template = _engine().get_template("card.html")
    return template.render(
        {
            "css": tailwind_css(HERE / "card.css"),
            "mcp_app_js": official_client() if client == "official" else (HERE / "static" / "mcp-app.js").read_text(),
            "inline_js": (HERE / "static" / "inline-checkout.js").read_text(),
            "card_js": (HERE / "static" / "card.js").read_text(),
        }
    )


def render_menu() -> str:
    return _engine().get_template("menu.html").render(
        {
            "css": tailwind_css(MENU / "menu.css"),
            "mcp_app_js": (HERE / "static" / "mcp-app.js").read_text(),
            "menu_js": menu_bundle(),
        }
    )


def option(name: str, default: str) -> str:
    flag = f"--{name}"
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


if __name__ == "__main__":
    client, kind = option("client", "hand"), option("card", "approval")
    values = {option("client", ""), option("card", "")}
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a not in values]
    default = CARD_DIR / "menu.html" if kind == "menu" else DEFAULT_OUT
    out = Path(args[0]) if args else default
    html = render_menu() if kind == "menu" else render(client)
    out.write_text(html)
    print(f"{out}: {len(html.encode()):,} bytes")
