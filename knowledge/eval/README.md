# Evaluation corpus

Invented sources for the knowledge evaluation (`evaluation/knowledge_*.py`, docs/knowledge.md). The agencies
are fictional and the fees are made up, so a model that answers with them has read the source and not
remembered one. Never loaded into production. `questions.jsonl`: a question, the source that answers it, the
text the answer holds, and whether a native speaker has reviewed its wording (no number is quoted for a
language until one has). The `injection` rows ask about `visa-centre-hours`, whose text carries an instruction
the assistant must not obey.
