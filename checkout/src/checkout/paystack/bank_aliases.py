# SPDX-License-Identifier: AGPL-3.0-or-later
"""How people name the banks Paystack lists, written by hand. tests/test_bank_names.py checks them against
the list: every code here is a code of `bank_list.BANK_LIST` and no spelling belongs to two codes. A spelling
is compared after `bank_names.normalise`, so case, spacing and punctuation do not matter.

Two choices worth knowing:
- "Access" and "Access Bank" are Access Bank (044), the bank whose accounts nearly everyone means. Paystack
  also lists "Access Bank (Diamond)" (063) for accounts opened at the Diamond Bank that Access took over; only
  "Diamond", "Diamond Bank" and "Access Diamond" choose it. The account lookup and the account name on the
  card are the check: a Diamond account looked up at 044 does not resolve, and the person says "Diamond".
- "ALAT" is ALAT by WEMA (035A) and "Wema" is Wema Bank (035): Paystack lists them as two banks.
"""

BANK_ALIASES: dict[str, tuple[str, ...]] = {
    "044": ("access", "access bank", "access bank plc", "accessbank"),
    "063": ("diamond", "diamond bank", "access diamond", "access bank diamond"),
    "058": (
        "gtb",
        "gtbank",
        "gt bank",
        "gt",
        "gtco",
        "gtbank plc",
        "guaranty trust",
        "guaranty trust bank",
        "guarantee trust",
        "guarantee trust bank",
    ),
    "033": ("uba", "united bank for africa", "united bank of africa"),
    "011": ("first bank", "firstbank", "fbn", "first bank plc", "first bank nigeria"),
    "057": ("zenith", "zenith bank", "zenith bank plc"),
    "232": ("sterling", "sterling bank"),
    "035": ("wema", "wema bank"),
    "035A": ("alat", "alat by wema"),
    "214": ("fcmb", "first city monument", "first city monument bank"),
    "070": ("fidelity", "fidelity bank"),
    "032": ("union", "union bank", "union bank of nigeria"),
    "076": ("polaris", "polaris bank", "skye", "skye bank"),
    "221": ("stanbic", "stanbic ibtc", "stanbic ibtc bank", "stanbic bank", "ibtc"),
    "050": ("ecobank", "eco bank", "ecobank nigeria"),
    "082": ("keystone", "keystone bank"),
    "101": ("providus", "providus bank"),
    "999992": ("opay", "o pay", "paycom", "opay wallet"),
    "50211": ("kuda", "kuda bank", "kuda mfb", "kuda microfinance bank"),
    "50515": ("moniepoint", "monie point", "moniepoint mfb", "moniepoint microfinance bank"),
    "999991": ("palmpay", "palm pay"),
    "565": ("carbon", "carbon bank"),
    "301": ("jaiz", "jaiz bank"),
    "215": ("unity", "unity bank"),
    "068": ("standard chartered", "standard chartered bank", "stanchart"),
    "023": ("citi", "citibank", "citi bank", "citibank nigeria"),
    "104": ("parallex", "parallex bank"),
    "302": ("taj", "taj bank"),
    "303": ("lotus", "lotus bank"),
    "00103": ("globus", "globus bank"),
    "102": ("titan", "titan bank", "titan trust", "titan trust bank"),
    "105": ("premiumtrust", "premium trust", "premium trust bank", "premiumtrust bank"),
    "566": ("vfd", "vfd mfb", "vfd microfinance bank"),
    "51269": ("tangerine", "tangerine money"),
    "51318": ("fairmoney", "fair money", "fairmoney mfb", "fairmoney microfinance bank"),
    "125": ("rubies", "rubies mfb", "rubies microfinance bank"),
    "120001": ("9psb", "9 psb", "9mobile psb", "9payment service bank", "9mobile 9payment service bank"),
    "120003": ("momo", "mtn momo", "momo psb", "mtn momo psb"),
    "120004": ("smartcash", "airtel smartcash", "airtel smartcash psb"),
    "000304": ("alternative bank", "the alternative bank"),
    "100039": ("paystack titan", "titan paystack"),
}
