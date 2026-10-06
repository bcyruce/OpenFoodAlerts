from openfoodalerts.sources.rasff.lookups import Dictionary, LookupEntry, diff_dictionary


def test_identical_dictionaries_have_no_changes() -> None:
    entries = [LookupEntry(306, "alert notification"), LookupEntry(302, "news")]
    diff = diff_dictionary(Dictionary.NOTIFICATION_CLASSIFICATION, entries, list(reversed(entries)))
    assert not diff.has_changes


def test_reports_added_removed_and_renamed_by_id() -> None:
    seed = [
        LookupEntry(21782, "biocontaminants"),
        LookupEntry(21789, "TSEs"),
        LookupEntry(21798, "allergens"),
    ]
    live = [
        LookupEntry(21782, "biological contaminants"),
        LookupEntry(21798, "allergens"),
        LookupEntry(26845, "environmental pollutants"),
    ]
    diff = diff_dictionary(Dictionary.HAZARD_CATEGORY, seed, live)
    assert diff.has_changes
    assert diff.added == [LookupEntry(26845, "environmental pollutants")]
    assert diff.removed == [LookupEntry(21789, "TSEs")]
    assert diff.renamed == [
        (LookupEntry(21782, "biocontaminants"), LookupEntry(21782, "biological contaminants"))
    ]


def test_country_code_change_counts_as_renamed() -> None:
    seed = [LookupEntry(5014, "United Kingdom", code="UK")]
    live = [LookupEntry(5014, "United Kingdom", code="GB")]
    diff = diff_dictionary(Dictionary.COUNTRY, seed, live)
    assert diff.renamed == [(seed[0], live[0])]
