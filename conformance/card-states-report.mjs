// SPDX-License-Identifier: AGPL-3.0-or-later
// The tally of the checks a run has made.
let failed = 0;
export const check = (ok, what) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed += 1;
};

export const failures = () => failed;
export const addFailures = (n) => {
  failed += n;
};
