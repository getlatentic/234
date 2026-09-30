# The brand: 234

## The decision

The product is named **234** (Nigeria's calling code). The brand is "234", the call to action is "Ask 234", and the tagline is "Talk and do anything with 234." The brand is green (`docs/chat-ui.md`, "The look"). The name, the wordmark, the plus symbol and the icons are not covered by the software licence: see [TRADEMARKS.md](../TRADEMARKS.md).

- The name is one setting, `PRODUCT_NAME` in `host/src/config/settings.py`. It is the page title, the composer's placeholder and accessible name ("Ask 234"), the manifest's `name` and `short_name`, the meta description and Open Graph tags, and the name a screen reader gives the drawn wordmark.
- The tagline is built from the setting (`chat/context.py`, `tagline()`): the manifest's `description`, the meta description and `og:description`. It is a slogan that says "anything", and the product has four connectors, so it is **not** the home's main copy. The home keeps its specific line under the wordmark ("I buy airtime, send money and order food, and you approve every payment."), which is true and says what the product does. The tagline lives in meta, the manifest and the docs.

## Known risks of the name

- **A number-only name is weak as a trademark and hard to search.** Digits with no word are hard to protect, and a search for "234" returns the country code, phone numbers and dates before this product.
- **Other Nigerian ventures use 234.** Known ones: 234Finance, 234Radio, and The 234 Project, which runs a "234 AI Hackathon".
- **It ties the name to Nigeria.** That fits the product today (naira, Nigerian banks, MTN and the food menu) and is a limit if the product ever serves another country.
- **Clearance is still to do.** Nothing has been checked yet: the Nigerian trademark registry, domain names, and social handles.

## The brand assets

The brand comes from eleven concept images (AI-generated raster art, several with transparent grounds). The images themselves are not distributed with this repository; the vector assets below were traced and rebuilt from them and are what the repository contains. The rule is to stick to the images. What they define:

| Image | Defines |
|---|---|
| Sheet "Logo & Icon System" | the seven parts below on one board, their names and uses, the type of the board itself (a heavy tight grotesque for titles, spaced capitals for the eyebrow and section labels, grey body, green section numbers), cards with soft corners on a warm white page |
| Lockup board | the secondary lockup: the logo over "Ask 234." (black "Ask", deep green "234" and stop, the heavy grotesque set with overlapping letters) |
| Symbol board | the four-pill pinwheel symbol alone |
| App icon (depth), flat icon, outlined icon | three tiles: a deep green face with a bright rim, a shadow and white numerals; the same flat; a pale tile with a deep green edge and the colour logo |
| Reverse board | white numerals on the deep green field; the plus in vivid green and mint |
| Four glow boards | the mark as light on black: two with the plus, two without, one in green and one in grey. They are a mood, not an asset (see "Not adopted") |

- **Primary logo.** Heavy geometric "234" with tight overlaps (the 2 meets the 3, the 3 meets the 4) and a small plus at the 4's upper right, in deep green. The plus is three pills: a green one standing on the 4, a mint one that replaces the top of the 4's stem and ends in a round foot, a green one pointing right. The 4 stands in for the fourth arm.
- **Secondary lockup.** The logo with "Ask 234." beneath it, as wide as the logo with its plus.
- **Symbol mark.** A pinwheel "plus" of four pills: bright green on top, mint on the left, vivid green on the right, deep green at the bottom. Each arm has its outer end round and its inner end flat, except the two vertical arms, which have one inner corner rounded too.
- **Wordmark.** The numerals alone.
- **Monochrome, reverse, single colour.** Charcoal, white on deep green, and deep green on mint.
- **App icons and favicon.** Filled with depth, flat, outlined; the favicon and avatar is a deep green tile with the plus alone.

**Not adopted:** the glow boards (light on black is a render, not a mark), the sheet's decorative mint pills in its header, and the concept boards' UI ideas (`Starters and the connectors`).

### Colours, as sampled

Medians of the flat regions of the images. The boards disagree with each other by a few steps (they are generated pictures), so the table gives the spread and the value the product uses. The values are in `design/tokens.json` (`brand`), once, in OKLCH, and round-trip to these hex values.

| Name | Used | Samples (image: hex) | Product value |
|---|---|---|---|
| deep | numerals, the primary action, the tile | lockup `#024933`, reverse field `#01492D`, sheet logo `#04482C`, single colour `#04472C`, flat tile `#02452A`, wordmark `#084B2F`, lockup "234" `#054C2F`, symbol foot `#014637`, favicon tile `#034028` | `#03492F` (median of the nine flat logo and tile samples) |
| green | the plus on a light ground | lockup top `#00AD53`, right `#01AD54`; sheet `#01A458` | `#00AD53` |
| bright | symbol, top pill | symbol board `#01BA65`; sheet `#019D54` | `#01BA65` |
| vivid | symbol, right pill; the plus on deep green | symbol board `#01D879`; reverse board `#01D985`, `#01D683` | `#01D879` |
| mint | symbol, left pill; the plus on deep green | symbol board `#CBFAE3`; reverse board `#C4F8DA`; sheet `#C9EED7` | `#CBFAE3` |
| mint soft | the mint pill on a light ground | lockup `#DDF3E6`; sheet `#D1F1DC` | `#DDF3E6` |
| white | reverse numerals | reverse board `#FEFDFE` | `#FEFDFE` |
| charcoal | monochrome, "Ask" | sheet `#212020`; lockup `#1F1F1E` | `#212020` |
| rim, lift, shade | the icon with depth: rim, face top, face bottom | depth icon `#36F895`, `#02543A`, `#023624` | the same |

**Contrast (WCAG 2.x, measured by `conformance/palette.test.mjs`).**

- Deep `#03492F`: the label on it (warm white `#FDFCF7`) is 10.23:1 (pure white 10.4:1; hover `#023924` 12.67:1, pressed `#022B1A` 15.0:1); the deep green on the warm ground `#FAF8F2` is 9.90:1, on the raised surface 10.33:1, on the sunken surface 8.98:1, on mint 9.34:1. It passes AA as text and as a fill with a light label, so it is the primary action, the focus ring, a selected edge and the numerals of the wordmark. (The earlier primary `#0B5D3B` was 7.7:1.)
- The brand greens fail as text, and this is why they are graphics only. On white and on the warm ground: green `#00AD53` 2.96 and 2.78, bright `#01BA65` 2.56 and 2.41, vivid `#01D879` 1.89 and 1.78, mint `#CBFAE3` 1.15 and 1.08, mint soft `#DDF3E6` 1.16 and 1.10. None reaches even 3:1, so none is used for text, a border that carries meaning, or a control. They are for the plus, the symbol, illustrations and selection tints. The palette test fails if one of them reaches 3:1 (then the rule needs another look) and measures that a vivid green primary fails its label.
- In the dark theme the plus is vivid `#01D879` on `#08120C`, well above 3:1 (the same pill is a graphic there too).
- Success is still not brand green: a separate teal, always with an icon and a word (`docs/chat-ui.md`). One primary-colour action per screen.

## The mark, as built

All of it is vector, from the concept images, and there is no font in any of it.

- **The numerals and "Ask" are traced.** `design/trace/trace.py` (a dev tool, run once, offline, and only with the source PNGs, which are not in the repository: `uv run design/trace/trace.py <folder of the PNGs>`; it needs `potrace` and runs `pillow` and `numpy` through `uv` for that one run, so nothing is added to the repository) thresholds the reverse board (white numerals on the deep field: the crispest source) and the lockup board (for "Ask"), closes the hairline gaps the drawing leaves where letters overlap, traces with potrace and then `design/trace/fit.py` refits the outline corner to corner: straight runs become lines, the rest cubic Beziers (Schneider), nearly axis-aligned edges share one coordinate, and small counters become polygons. Result: `design/mark/numerals.svg` (52 nodes, 903 x 376 units) and `design/mark/ask.svg` (40 nodes), at 0.986 and 0.972 intersection over union with the source masks. Only those two SVGs and the scripts are committed, and the build does not need the images.
- **The plus is geometry** (`design/mark.mjs`), measured on the reverse board: three pills on a 90-unit column. Top: a leaf 90 x 90 (round top, round lower left, square lower right, its foot under the mint pill). Right: 93 x 96, round end. Mint: 90 wide, square top flush with the 4's top, round foot 147 tall. Every arm is "a rectangle whose outer corners are fully round, with one inner corner round for the rest of its length": the same rule draws the four-pill symbol in a 100-unit box (arms 40 wide, band 36 thick, end arms 32 long with a 12-unit inner radius), which matches the symbol board to 0.958.
- **Assembly** (`design/brand.mjs`, run by `node design/build.mjs`, checked current by the palette test) writes `design/brand/*.svg`: `logo`, `logo-reverse`, `logo-mono`, `logo-single`, `lockup`, `lockup-reverse`, `symbol`, `wordmark`, `wordmark-reverse`, `app-icon-flat`, `app-icon-outline`, `app-icon-depth`, `favicon`. The one-colour versions cut each pill back from what is painted after it (a mask, so no ground colour is baked in): the concept's monochrome shows the same hairline.
- **In the page.** The home draws the colour logo inline (`chat/_wordmark.html`, generated): the numerals take the `mark` token (deep green in light, white in dark: the reverse version), the green pills the `accent` token (green, vivid in dark), the mint pill `mark-mint`. One sentence under it; no tagline in the page (the tagline lives in meta and the manifest).
- **Icons**, all in `host/src/chat/static/chat/brand/`: `favicon.svg` and `favicon.ico` (16, 32, 48): the plus alone on the deep tile; `apple-touch-icon.png` (180) and `icon-maskable-512.png`: the reverse logo on a deep square to the edge, inside the 80% circle of the maskable safe zone (the logo's corners are at 91% of that radius); `icon-192.png` and `icon-512.png`: the flat rounded tile. The SVG sources are written by `node design/build.mjs`, the PNGs and the `.ico` by `node design/raster.mjs` (Chromium) and are committed. Contact sheet: `docs/screens/brand-icons.png`.
- **The depth icon is not in the PWA set.** It survives at 192 pixels (`brand-icons.png` shows it), but its shadow and its margin make the tile about a fifth smaller than its neighbours in a launcher, and a tile with a shadow cannot be full bleed for the maskable and touch icons, so one family of icons (flat) is shipped. The depth version stays in `design/brand/app-icon-depth.svg` for store listings.
- **Manifest.** `theme_color` is the deep green (`PRIMARY` in the generated `palette.py`); `background_color` stays the warm ground, so a launch shows the icon on the page's own colour. The page's `theme-color` metas still follow the light and dark grounds.
- **The simulated checkout page** carries the favicon (the plus, inline as a data URI) and takes every colour from the tokens, so its primary button is the deep green.

### Typeface

**Manrope** (SIL Open Font License 1.1), a Latin subset with the weight axis cut to 500 to 800, 19.4 KB, `host/src/chat/static/chat/fonts/manrope.woff2`, licence text beside it (`OFL.txt`, copyright "The Manrope Project Authors"). It sets headings in replies only and is fetched only by a page that has one. The body and UI stack stays the system stack: Manrope has no naira sign (U+20A6) and no combining tone marks, both of which this product's text needs (amounts, Yoruba), so the system font must carry them anyway.

### Clear space and smallest sizes

The images carry no written rules; these come from measuring them and from rendering the assets small (`docs/screens/brand-icons.png`).

- **Clear space: one plus pill, 90 units, about a quarter of the numerals' height,** on every side of the logo, the lockup and the wordmark. The concept cards pad the logo by 0.25 to 0.35 of the numerals' height.
- **Smallest logo with its plus: 24 px tall in all** (numerals about 20 px). At 20 px the pills still show; at 16 px the mint pill merges with the 4. Below 24 px use the wordmark (no plus), down to 12 px tall.
- **Smallest lockup: 40 px tall**, where "Ask" is still clear. **Smallest symbol: 16 px**, where the four pills are still four.
- **Favicon: the plus on the deep tile, from 16 px.** At 16 px the green pill, the mint pill and the right pill read as three blocks on green; from 32 px they are pills.

### Do and do not

- Do use the deep green as the only solid green of an action; keep one per screen. Do set the mark on warm white, on the deep green or on the dark ground, in the version made for it (`logo` on light, `logo-reverse` on dark).
- Do keep the lockup line as wide as the logo. Do keep the wordmark for spaces under 24 px.
- Do not set text in any brand green or mint, and do not use them for a control, a border that carries meaning or a status. Do not recolour a pill, reorder the colours, rotate the plus, or draw it with a stroke.
- Do not put the plus on a photograph or a busy ground; do not add a glow, a gradient or a shadow to the logo itself (the depth icon is the one exception and is for store listings).
- Do not retype "234" in a font: the numerals are the drawing. A screen reader gets the name from `PRODUCT_NAME`.

A green plus can read as a health or pharmacy symbol, the cross of a first-aid kit. This was a deliberate choice.

### What differs from the concept images

`design/trace/compare.py` puts the brand SVGs beside the source PNGs and prints the overlap (it needs the PNGs, which are not in the repository). The measurements:

- **Numerals.** Ours are traced from the reverse board (0.979 against it). The boards do not agree on the proportions: the width over height of the numerals is 2.27 to 2.56 across them, and ours is 2.40. Against the lockup board, which is wider, the overlap is 0.868, most of it the numerals' width. The hairline the boards leave between the 3 and the 4 (the 3's edge drawn as a thin dark line) is closed, so the silhouette is one shape.
- **Symbol.** Flat fills where the board has a slight gradient; the arms are regularised to one pinwheel (the board's top arm is 266 pixels long and the bottom 243, the vertical arms 310 wide and the band 276). 0.958 against the board.
- **The mint pill** is opaque; the reverse board shows it slightly translucent over the white 4, which loses the pill's edge in the dark theme as it does in the board.
- **Lockup.** The second line is set to the logo's width, and its "234" is the logo's numerals (the board's are wider). "Ask" and the stop are traced from the board.
- **Icons.** The flat tile matches the flat board's proportions; the depth tile approximates the board's gradient and rim with three sampled colours; the outlined tile is a little tinted where the board is almost white. The favicon's plus is vivid green on the tile (the sheet draws it a duller green).
- **Type.** The sheet's headings suggest a heavy tight grotesque. The product's headings in replies stay Manrope ExtraBold (below), a geometric face; the lettering of the mark is a drawing, not a font.

## Starters and the connectors

A starter is shown only if it works end to end today on a connector that exists: airtime, data, send money, order food, pay a merchant, and "What can you do?". The concept board also shows starters for electricity, a ride, places nearby, splitting a bill, NEPA bill help and school-fee reminders. There are no connectors for those, so there are no starters for them (a starter that fails or invents is worse than none).

**Next connectors, in order:** electricity and other bills through VTpass (the natural next one: the airtime and data connector already talks to VTpass, and electricity is the same API with a meter number in place of a phone number); then a bill-splitting helper (a message to the people involved, no money moved by the product); then a ride and places-nearby lookups, which need their own providers. A starter is added with its connector, not before.

The board's web layout (a sidebar with Home, Explore, Library, Tasks, Payments and so on, a bell, an avatar, an insights strip) is not adopted: the page keeps no header, footer or navigation, and the chats drawer is the only panel.

## Comparison with the concept board's transfer card

The board's transfer card is: recipient name from the bank lookup, amount, an editable reference, one primary "Confirm and send", then a distinct "Payment sent" state with a receipt link. Ours: the recipient name from the bank lookup (`recipientName`), the bank and masked account, the amount, one primary "Approve", then a distinct success state (a check icon, "Transfer sent" and the receipt lines). Two things on the board are not in ours, and both need a connector that does not have them: an editable reference (the connector fixes the reference) and a receipt link (a receipt has a title and lines and no address). Nothing was added for either; no backend behaviour changed.

## Colour

The palette, its contrast numbers and the rule that separates success from the brand green are in `docs/chat-ui.md`; the brand greens, sampled, and what they measure are above. The concept boards' earlier vivid greens (`#1FAF5A`, then `#16A34A`) are superseded by the sampled `#00AD53`, `#01BA65` and `#01D879`, which are graphic colours and fail as text by design.
