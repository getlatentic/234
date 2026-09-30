# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which number VTpass receives, and what the simulator does with a number."""

from tools.mutations.model import AIRTIME, SRC, Mutation

RECIPIENT = ["tests/test_vtpass_recipient.py"]

MUTATIONS: list[Mutation] = [
    Mutation(
        "the simulated VTpass delivers any valid Nigerian mobile number",
        f"{SRC}/vtpass/sim.py",
        '("success" if is_nigerian_mobile(phone) else "failed")',
        '("failed" if is_nigerian_mobile(phone) else "failed")',
        ["tests/test_vtpass_sim.py", "tests/test_flow_airtime.py"],
    ),
    Mutation(
        "the simulated VTpass fails a number that is not a valid Nigerian mobile",
        f"{SRC}/vtpass/sim.py",
        '("success" if is_nigerian_mobile(phone) else "failed")',
        '("success" if True else "failed")',
        ["tests/test_vtpass_sim.py"],
    ),
    Mutation(
        "the simulated VTpass keeps a number that means failure",
        f"{SRC}/vtpass/sim.py",
        'SIMULATED_FAILURE_NUMBER: "failed",',
        'SIMULATED_FAILURE_NUMBER: "success",',
        ["tests/test_vtpass_sim.py", "tests/test_flow_airtime.py"],
    ),
    Mutation(
        "the simulated VTpass keeps the documented pending number",
        f"{SRC}/vtpass/sim.py",
        '"201000000000": "pending",',
        '"201000000000": "success",',
        ["tests/test_vtpass_sim.py", "tests/test_flow_airtime.py"],
    ),
    Mutation(
        "a number quoted on another network is refused before anyone pays",
        f"{SRC}/flows/airtime.py",
        "if owner is not None and owner != network:",
        "if False:",
        AIRTIME,
    ),
    Mutation(
        "the network check applies to the simulator only, never to the real sandbox",
        f"{SRC}/flows/airtime.py",
        'if self.ctx.modes.vtpass != "simulated":',
        "if False:",
        AIRTIME,
    ),
    Mutation(
        "the sandbox is sent its success number for a real typed number",
        f"{SRC}/vtpass/recipient.py",
        "else DOCUMENTED_SUCCESS_NUMBER",
        "else typed",
        RECIPIENT,
    ),
    Mutation(
        "the sandbox is sent a typed trigger number unchanged",
        f"{SRC}/vtpass/recipient.py",
        "typed if typed in TRIGGER_NUMBERS else DOCUMENTED_SUCCESS_NUMBER",
        "DOCUMENTED_SUCCESS_NUMBER",
        RECIPIENT,
    ),
    Mutation(
        "live is sent the number as typed",
        f"{SRC}/vtpass/recipient.py",
        'case "simulated" | "live":\n            return typed',
        'case "simulated":\n            return typed\n        case "live":\n'
        "            return DOCUMENTED_SUCCESS_NUMBER",
        RECIPIENT,
    ),
    Mutation(
        "every VTpass purchase is sent the number the mode decides",
        f"{SRC}/flows/airtime.py",
        'AirtimeOrder(request_id, d["network"], self._recipient(quote), quote.amount_kobo)',
        'AirtimeOrder(request_id, d["network"], d["phone"], quote.amount_kobo)',
        [*RECIPIENT, *AIRTIME],
    ),
    Mutation(
        "a substituted number is recorded in the audit log",
        f"{SRC}/flows/airtime.py",
        "        if sent != typed:",
        "        if False:",
        RECIPIENT,
    ),
    Mutation(
        "the simulated mode never reaches VTpass",
        f"{SRC}/app.py",
        'return VtpassClient(SIMULATED_VTPASS, simulator, clock=clock), "simulated"',
        'return VtpassClient(SIMULATED_VTPASS, transport, clock=clock), "simulated"',
        RECIPIENT,
    ),
    Mutation(
        "the card names the sandbox and says no airtime is sent",
        f"{SRC}/modes.py",
        'if modes.vtpass == "sandbox" else ""',
        'if False else ""',
        ["tests/test_phase_and_mode.py", *RECIPIENT],
    ),
    Mutation(
        "live VTpass is refused at startup",
        f"{SRC}/config.py",
        'if mode == "live":',
        "if False:",
        ["tests/test_config.py", "tests/test_public_config.py"],
    ),
]
