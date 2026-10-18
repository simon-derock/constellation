from constellation.live.search import text_query


def test_words_are_joined_with_or_so_a_natural_question_still_matches() -> None:
    assert text_query("Why does the vector index crash on restart?") == "vector|index|crash|restart"


def test_stopwords_short_words_and_repeats_are_dropped_in_first_seen_order() -> None:
    assert text_query("the of an on VECTOR vector Vector ab") == "vector"


def test_search_operators_cannot_be_smuggled_in() -> None:
    assert text_query('foo* "bar" (baz) @title:qux ~quux -corge') == "foo|bar|baz|title|qux|quux|corge"


def test_the_query_is_bounded() -> None:
    q = text_query(" ".join(f"word{i}" for i in range(50)))
    assert q.count("|") == 11


def test_nothing_searchable_gives_an_empty_query() -> None:
    assert text_query("   ?!  ") == ""
    assert text_query("") == ""
