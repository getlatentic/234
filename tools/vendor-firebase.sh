#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Vendors the Firebase JS SDK's Auth as the one file the chats drawer loads when a person presses "Continue with
# Google": the modular firebase/app and firebase/auth, only what sign-in by popup or redirect needs, bundled with
# this repository's esbuild into host/src/chat/static/chat/vendor/firebase-auth.esm.min.js. The npm install
# happens in a temporary directory; nothing is added to package.json.
# usage: tools/vendor-firebase.sh [version]        (the pinned version is the default: change it here and in docs/auth.md)
set -euo pipefail
version=${1:-12.19.0}
root=$(cd "$(dirname "$0")/.." && pwd)
out="$root/host/src/chat/static/chat/vendor"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
npm init -y > /dev/null
npm install --no-audit --no-fund --silent "firebase@$version" > /dev/null
cat > entry.mjs <<'ENTRY'
export { FirebaseError } from "@firebase/util";
export { initializeApp } from "firebase/app";
export {
  GoogleAuthProvider,
  browserPopupRedirectResolver,
  connectAuthEmulator,
  getRedirectResult,
  inMemoryPersistence,
  initializeAuth,
  signInWithPopup,
  signInWithRedirect,
  signOut,
} from "firebase/auth";
ENTRY
"$root/node_modules/.bin/esbuild" entry.mjs --bundle --minify --format=esm --target=es2022 --platform=browser \
  --legal-comments=none --define:process.env.NODE_ENV=\"production\" --outfile="$out/firebase-auth.esm.min.js"
{
  echo "Firebase JS SDK $version: firebase/app and firebase/auth, bundled by tools/vendor-firebase.sh."
  echo "Copyright Google LLC. Licensed under the Apache License, Version 2.0 (the packages ship no licence file;"
  echo "the text below is from https://www.apache.org/licenses/LICENSE-2.0.txt). Bundled with it:"
  for pkg in idb tslib; do
    echo "  $pkg $(node -p "require('./node_modules/$pkg/package.json').version"), $(node -p "require('./node_modules/$pkg/package.json').license"): $(node -p "require('./node_modules/$pkg/package.json').repository.url || require('./node_modules/$pkg/package.json').repository")"
  done
  echo
  curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt
  for pkg in idb tslib; do
    echo; echo "== $pkg =="; cat "node_modules/$pkg/LICENSE"*
  done
} > "$out/firebase-auth.LICENSE.txt"
echo "wrote $out/firebase-auth.esm.min.js ($(wc -c < "$out/firebase-auth.esm.min.js") bytes, sha256 $(shasum -a 256 "$out/firebase-auth.esm.min.js" | cut -d' ' -f1))"
