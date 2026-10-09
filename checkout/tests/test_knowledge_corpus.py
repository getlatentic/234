# SPDX-License-Identifier: AGPL-3.0-or-later
"""The corpus rules (tools/knowledge_corpus.py) and the SQL it becomes (tools/knowledge_load.py): what a
source must have to be published, and that the real corpus in knowledge/sources is sound."""

from datetime import date

from tests.knowledge_support import DRAFT, LICENCE, write_corpus
from tools import knowledge_load
from tools.knowledge_corpus import is_stale, load_all, parse


def problems_of(tmp_path, text, name="frsc-licence-renewal"):
    folder = write_corpus(tmp_path, **{name: text})
    return parse(next(folder.glob("*.md"))).problems


def test_a_sound_source_has_no_problems(tmp_path):
    assert problems_of(tmp_path, LICENCE) == []
    assert problems_of(tmp_path, DRAFT, "nimc-draft") == []


def test_a_published_source_needs_a_reviewer_and_a_date(tmp_path):
    bare = LICENCE.replace("reviewed_by: Reviewer One\n", "").replace("reviewed_at: 2026-10-02\n", "")
    assert problems_of(tmp_path, bare) == ["a published source has reviewed_by and reviewed_at"]


def test_a_fee_is_verified_by_someone_other_than_the_reviewer_and_is_in_the_text(tmp_path):
    same = LICENCE.replace("verified_by: Reviewer Two", "verified_by: Reviewer One")
    assert problems_of(tmp_path, same) == ["fee 'Renewal' is verified by someone other than the reviewer"]
    absent = LICENCE.replace("naira: 15000", "naira: 16000")
    assert problems_of(tmp_path, absent) == ["fee 'Renewal' (16,000) is not in the text"]


def test_the_link_must_be_on_the_list_and_tier_one_must_be_an_official_page(tmp_path):
    other = LICENCE.replace("https://frsc.gov.ng/licence-renewal", "https://gov.ng.evil.com/x")
    assert problems_of(tmp_path, other) == ["url is an https link on the allow-list"]
    outlet = LICENCE.replace("https://frsc.gov.ng/licence-renewal", "https://inecnigeria.org/x")
    assert problems_of(tmp_path, outlet) == ["tier 1 is an official .gov.ng page"]


def test_a_page_is_not_kept_whole_only_an_excerpt_or_a_paraphrase(tmp_path):
    long = LICENCE + "word " * 1300
    assert "keep an excerpt or a paraphrase" in problems_of(tmp_path, long)[0]


def test_the_id_is_the_files_name_and_a_date_is_not_in_the_future(tmp_path):
    assert problems_of(tmp_path, LICENCE, "other-name") == [
        "id is lowercase words joined by hyphens and is the file's name"
    ]
    future = LICENCE.replace("retrieved_at: 2026-10-01", "retrieved_at: 2999-01-01")
    assert problems_of(tmp_path, future) == ["retrieved_at is a date that is not in the future"]


def test_a_file_without_front_matter_or_with_missing_fields_says_so(tmp_path):
    assert problems_of(tmp_path, "just text") == ["no front matter between --- lines"]
    missing = LICENCE.replace("agency: FRSC\n", "")
    assert problems_of(tmp_path, missing) == ["agency is missing"]


def test_two_sources_cannot_share_an_id(tmp_path):
    folder = write_corpus(tmp_path, frsc_licence_renewal=LICENCE)
    (folder / "sub").mkdir()
    (folder / "sub" / "frsc-licence-renewal.md").write_text(LICENCE)
    assert any("is also used by" in p for s in load_all(folder) for p in s.problems)


def test_a_source_is_stale_after_half_a_year(tmp_path):
    source = parse(next(write_corpus(tmp_path, frsc_licence_renewal=LICENCE).glob("*.md")))
    assert not is_stale(source, date(2026, 12, 1)) and is_stale(source, date(2027, 6, 1))


def test_the_sql_replaces_what_the_database_holds_and_quotes_text(tmp_path):
    folder = write_corpus(tmp_path, frsc_licence_renewal=LICENCE)
    sql = knowledge_load.statements(load_all(folder))
    assert sql[0].startswith("DELETE FROM knowledge_source WHERE id NOT IN ('frsc-licence-renewal')")
    assert (
        any("driver''s licence" in line for line in sql)
        and sum("INSERT INTO knowledge_passage" in s for s in sql) >= 1
    )


def test_the_report_lists_drafts_and_stale_sources(tmp_path):
    old = LICENCE.replace("retrieved_at: 2026-10-01", "retrieved_at: 2025-01-01")
    folder = write_corpus(tmp_path, frsc_licence_renewal=old, nimc_draft=DRAFT)
    lines = knowledge_load.report(load_all(folder))
    assert "unreviewed  nimc-draft" in lines and any(line.startswith("stale       frsc-") for line in lines)


def test_the_real_corpus_is_sound():
    assert knowledge_load.check(load_all()) == []
