// SPDX-License-Identifier: AGPL-3.0-or-later
export const naira = (kobo) => `₦${(kobo / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
