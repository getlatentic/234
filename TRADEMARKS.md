# Trademarks and brand assets

The code in this repository is licensed under the GNU AGPL v3 or later ([LICENSE](LICENSE), [NOTICE](NOTICE)).
The licence does **not** cover the brand. These are not licensed under the AGPL and all rights in them are reserved:

- the name "234" and "Ask 234" as the name of a product or service;
- the wordmark, the lockup and the plus symbol (`design/brand/`, `design/mark/`, `design/mark.mjs`);
- the app icons and favicon (`host/src/chat/static/chat/brand/`, `design/brand/app-icon-*.svg`, `design/brand/favicon.svg`);
- the colour logo drawn in the chat page (`host/src/chat/templates/chat/_wordmark.html` and the files generated from the
  same artwork).

## You may

- describe the project and link to it, using the name to say what it is ("a fork of 234");
- show the screenshots in `docs/screens/` when you write about the project;
- keep the assets unchanged in a copy of the repository, to run or study it.

## You may not

- use the name or the assets for a product or service of your own, or name a deployment of a modified version "234";
- suggest that the project, its author or its contributors endorse, sponsor or operate your product or deployment;
- use a confusingly similar name, logo or colour arrangement.

If you fork the code and run it, give your deployment its own name and replace the assets under `design/` and
`host/src/chat/static/chat/brand/`; `PRODUCT_NAME` in `host/src/config/settings.py` is the one place the name is set.
The deployed names of the Workers are set in `tools/deploy.sh`.

The Google "G" (`host/src/chat/static/chat/brand/google-g.svg`) is a trademark of Google LLC, used on the sign-in
button as Google's branding guidelines allow. It is not part of this project's brand and not licensed here.

For any other use, ask the maintainers first by opening an issue.
