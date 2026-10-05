// SPDX-License-Identifier: AGPL-3.0-or-later
// A check reports one result per rule. "must" rules decide the exit code; "should" rules are warnings.
export const must = (id, ok, detail) => ({ id, level: "must", ok, detail });
export const should = (id, ok, detail) => ({ id, level: "should", ok, detail });
export const skipped = (id, detail) => ({ id, level: "skip", ok: true, detail });
