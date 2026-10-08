# The bot check before a first message

A visitor who is not signed in passes Cloudflare Turnstile once, when they send the first message of a chat. It is
what stops a script from making a new visitor, and so a new daily allowance, with every request. Code:
`host/src/chat/bot_check.py`, `chat/views/send.py` (`start`), `chat/static/chat/bot-check.js`.

## What happens

1. The page learns the widget's public site key from `/api/me` (`botCheck`). A signed-in person is given none: Google
   has identified them already.
2. The home page makes no request to Cloudflare. When the first message is sent, `bot-check.js` fetches Turnstile's
   script, renders the widget (`appearance: interaction-only`, so it shows itself only if Cloudflare cannot decide
   alone) and sends the token with the message as `botToken`.
3. `POST /c/<id>/start` checks the token with Cloudflare's `siteverify`, with the secret, before it makes the chat.
   Cloudflare must say it is a good token, made for the action `start`, on one of this host's own addresses
   (`ALLOWED_HOSTS`, or `TURNSTILE_HOSTNAMES`). Each token is used once; Cloudflare refuses it the second time.
4. A refused message makes no chat and answers 403 `bot_check`: "We could not check that you are a person. Allow
   challenges.cloudflare.com and try again, or sign in."

A deploy's smoke test sends its first message with the deploy's own ops token (`Authorization: Bearer`, a secret
made at each deploy) and is let past; the smoke test also checks that a first message with no token is refused,
and that `/api/me` offers the widget, so a deploy that turns the check off by mistake fails.

Only the message that would make the chat is checked. A second message to the same id joins the chat, and the other
ways in (a message in a chat that exists, a card's note) are not asked for a token. A token longer than 2,048
characters is refused without asking Cloudflare.

## When Cloudflare cannot be asked

If `siteverify` does not answer, answers with a server fault, or answers with something that is not JSON, the
message is let through. A check that fails shut would stop every first message whenever Cloudflare has a bad minute,
and the limits that were always there still hold: 12 messages a minute per visitor, the day's calls and tokens of
the model (see [deploy.md](deploy.md)), and the daily allowance of money. The failure is logged as a warning.

A browser that cannot load Cloudflare's script (a blocker, a network that refuses it) cannot get a token, and is told
so. That is the one way the check keeps a real person out; signing in gets round it.

## The policy

Where Turnstile is on, the page's policy gains `https://challenges.cloudflare.com` in `script-src`, `connect-src` and
`frame-src`, and nowhere else. Where it is off, the policy is what it was. The static home's `_headers` file is built
with the site key in the environment (as sign-in's values are), so the build and the Worker agree.

## Turning it on

Two widgets exist on the Latentic account, one for production (`234.getlatentic.com` and the workers.dev address) and
one for staging; their keys are in `.env.turnstile.local` (git ignores it; mode 600):

```
TURNSTILE_PRODUCTION_SITE_KEY=…    TURNSTILE_PRODUCTION_SECRET=…
TURNSTILE_STAGING_SITE_KEY=…       TURNSTILE_STAGING_SECRET=…
```

`tools/deploy.sh` reads the two lines of its stage: the site key becomes the Worker variable `TURNSTILE_SITE_KEY` (and
reaches the build of the home page), the secret becomes the Worker secret `TURNSTILE_SECRET`, sent on stdin and never
printed. Without the file, or without a stage's lines, the check is off and the deploy says so. A malformed value
stops the deploy.

## Tests

- `host/tests/test_bot_check.py`: the verdicts for good, missing, over-long and refused tokens; another action or
  another host; every way Cloudflare can fail to answer; a chat that exists; a signed-in person; the policy.
- `conformance/bot-check.mjs` (a stack with `TURNSTILE=1`, which uses Cloudflare's published test keys and needs the
  network): the real script in a real browser and the real `siteverify`. The home page makes no request to Cloudflare;
  the first message carries a token and makes the chat; the next carries none; a first message with no token, or an
  over-long one, is refused and makes no chat.
- `checkout/tools/mutations/cost_rules.py`: each guard undone.

## Not done

- The check guards the page. The A2A and MCP doors (an agent's message, a person's OAuth client) have no Turnstile:
  those callers are identified by a registered key or a signed-in account, and are held by their own limits (the
  gateway's rate limit, the daily cap of an agent's people).
- A refused token is not told apart from a missing one in the page's message.
- No alert fires on a run of refusals. [metrics.md](metrics.md) has no data point for the check.
