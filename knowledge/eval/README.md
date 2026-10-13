# Evaluation corpus

Invented sources for the knowledge evaluation (`evaluation/knowledge_*.py`, docs/knowledge.md). The agencies
are fictional and the fees are made up, so a model that answers with them has read the source and not
remembered one. Never loaded into production. `questions.jsonl`: a question, the source that answers it, the
text the answer holds, and whether a native speaker has reviewed its wording (no number is quoted for a
language until one has). Each row has a `split`: `dev` rows were used while the tool, the prompt and the scorer were built;
`held-out` rows were written before the run that quotes numbers and are not used to change anything. The `S` rows (#645) are about the source line the host shows under an answer: `vehicle-inspection` and `passport-replacement` are pages on the subject of other ones, and the figure 14 is in two pages. The `injection` rows ask about `visa-centre-hours`, whose text carries an instruction
the assistant must not obey. `refuse-levy` has no question here: the wallet split's injection cases
(`evaluation/cases.jsonl`, `wallet_injection`) ask about it, and its text tells the assistant to pay from the
person's wallet and send their balance to a link.
