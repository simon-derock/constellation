from constellation.retrieval.passages import best_windows, windows


def test_windows_cover_the_whole_text_with_overlap_and_no_gaps() -> None:
    text = "".join(str(i % 10) for i in range(2_500))
    got = windows(text, size=1_000, stride=800)
    assert got[0] == text[:1_000]
    assert got[-1].endswith(text[-1])
    covered: set[int] = set()
    for n, w in enumerate(got):
        covered.update(range(n * 800, n * 800 + len(w)))
    assert covered == set(range(len(text)))


def test_a_short_text_is_one_window_and_an_empty_one_is_none() -> None:
    assert windows("short", size=1_000, stride=800) == ["short"]
    assert windows("", size=1_000, stride=800) == []


def test_the_head_is_always_kept_because_titles_and_headers_live_there() -> None:
    docs = {"d": "HEAD " + "filler " * 400 + "needle penicillin dosage " + "filler " * 400}
    got = best_windows("penicillin dosage", docs, per_doc=2, size=300, stride=250)
    assert got["d"][0].startswith("HEAD")
    assert any("penicillin" in w for w in got["d"])


def test_the_most_query_specific_windows_are_chosen_in_document_order() -> None:
    body = ["alpha " * 60, "beta gamma delta " * 20, "alpha " * 60, "gamma rare-term zeta " * 20, "alpha " * 60]
    docs = {"d": "".join(body)}
    got = best_windows("rare-term zeta", docs, per_doc=2, size=len(body[3]), stride=len(body[3]))
    assert len(got["d"]) == 2
    assert any("rare-term" in w for w in got["d"])


def test_common_words_do_not_pick_windows_because_rare_words_weigh_more() -> None:
    docs = {
        "a": "the the the the " * 80 + "uniqueword appears here " + "the " * 80,
        "b": "the the the the " * 200,
    }
    got = best_windows("the uniqueword", docs, per_doc=2, size=300, stride=250)
    assert any("uniqueword" in w for w in got["a"])


def test_every_document_gets_at_most_per_doc_windows() -> None:
    docs = {f"d{i}": "word " * 2_000 for i in range(3)}
    got = best_windows("word", docs, per_doc=3, size=400, stride=300)
    assert all(len(v) <= 3 for v in got.values())
    assert set(got) == set(docs)
