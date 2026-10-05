// SPDX-License-Identifier: AGPL-3.0-or-later
// Reads a tool the way a host does: what the model may call, what moves money, what only a card may call.
const MONEY_ARGUMENT = /amount|kobo|naira|price|total/i;
const APPROVAL_TOOL = /approve|authori[sz]e|capture|charge|confirm_pay|payout/i;
const APPROVAL_ARGUMENT = /approval|token|otp|pin/i;

export const propertyNames = (tool) => Object.keys(tool.inputSchema?.properties ?? {});
export const isReadOnly = (tool) => tool.annotations?.readOnlyHint === true;
export const isAppOnly = (tool) => {
  const visibility = tool._meta?.ui?.visibility;
  return Array.isArray(visibility) && visibility.length > 0 && visibility.every((v) => v === "app");
};
export const isModelVisible = (tool) => !isAppOnly(tool);
export const movesMoney = (tool) => !isReadOnly(tool) && isModelVisible(tool) && propertyNames(tool).some((p) => MONEY_ARGUMENT.test(p));
export const approvesPayment = (tool) => !isReadOnly(tool) && APPROVAL_TOOL.test(tool.name);
export const demandsApprovalProof = (tool) => propertyNames(tool).some((p) => APPROVAL_ARGUMENT.test(p));
export const takesIdempotencyKey = (tool) => propertyNames(tool).some((p) => /idempot/i.test(p));
