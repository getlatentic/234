// SPDX-License-Identifier: AGPL-3.0-or-later
import { must, should } from "../result.mjs";

export function handshake({ client }) {
  const info = client.getServerVersion();
  return [
    must("handshake.server-info", Boolean(info?.name && info?.version), `server is ${info?.name ?? "unnamed"} ${info?.version ?? ""}`.trim()),
    should("handshake.instructions", (client.getInstructions() ?? "").length >= 40, "the server tells the model how to use it (instructions)"),
  ];
}
