// SPDX-License-Identifier: AGPL-3.0-or-later
import { must, should, skipped } from "../result.mjs";
import { approvesPayment, demandsApprovalProof, isAppOnly, isModelVisible, movesMoney, takesIdempotencyKey } from "../tools-model.mjs";

const names = (tools) => tools.map((t) => t.name).join(", ");

export function moneyRules({ tools }) {
  const moving = tools.filter(movesMoney);
  const approving = tools.filter(approvesPayment);
  if (!moving.length && !approving.length) return [skipped("money.rules", "no tool takes an amount or approves a payment")];
  const noKey = moving.filter((t) => !takesIdempotencyKey(t));
  const unsafeApproval = approving.filter((t) => isModelVisible(t) && !demandsApprovalProof(t));
  const notIdempotent = moving.filter((t) => t.annotations?.idempotentHint !== true);
  return [
    must("money.idempotency-key", noKey.length === 0, noKey.length ? `these take an amount and no idempotency_key: ${names(noKey)}` : "every tool that takes an amount takes an idempotency key"),
    should("money.idempotent-hint", notIdempotent.length === 0, notIdempotent.length ? `with a key they repeat safely; set idempotentHint: ${names(notIdempotent)}` : "money tools declare idempotentHint"),
    must("money.model-cannot-approve", unsafeApproval.length === 0,
      unsafeApproval.length ? `the model can approve a payment itself; make these app-only or require the person's approval token: ${names(unsafeApproval)}`
        : `approval is for the person: ${approving.map((t) => `${t.name}${isAppOnly(t) ? " (app-only)" : " (needs proof)"}`).join(", ") || "no approval tool"}`),
  ];
}
