import json

from constellation.retrieval.rewrite import Rewrite, build_messages, parse_rewrite, search_queries


def test_the_prompt_carries_the_question_verbatim_and_asks_for_json() -> None:
    messages = build_messages("When does booking open for the new top end accelerator?")
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "When does booking open for the new top end accelerator?" in messages[-1]["content"]
    assert "JSON" in messages[-1]["content"]


def test_well_formed_json_is_parsed_into_a_passage_and_keywords() -> None:
    raw = json.dumps(
        {"passage": "Opening Dedicated capacity for H200 80GB in eu-central-1.", "keywords": ["H200", "GPU"]}
    )
    got = parse_rewrite(raw)
    assert got == Rewrite("Opening Dedicated capacity for H200 80GB in eu-central-1.", ("H200", "GPU"))


def test_json_wrapped_in_prose_or_code_fences_is_still_found() -> None:
    raw = 'Sure! ```json\n{"passage": "p text", "keywords": "alpha, beta, gamma"}\n``` hope that helps'
    got = parse_rewrite(raw)
    assert got.passage == "p text"
    assert got.keywords == ("alpha", "beta", "gamma")


def test_unparseable_output_becomes_the_passage_rather_than_being_lost() -> None:
    got = parse_rewrite("the model just wrote prose about kernels")
    assert got.passage == "the model just wrote prose about kernels"
    assert got.keywords == ()


def test_empty_output_gives_an_empty_rewrite() -> None:
    assert parse_rewrite("") == Rewrite("", ())
    assert parse_rewrite("   \n ") == Rewrite("", ())


def test_lengths_are_bounded_and_control_characters_removed() -> None:
    got = parse_rewrite(json.dumps({"passage": "a\x00b" * 2_000, "keywords": [f"k{i}" for i in range(100)]}))
    assert len(got.passage) <= 1_200
    assert "\x00" not in got.passage
    assert len(got.keywords) <= 20


def test_search_queries_always_include_the_original_question_first() -> None:
    queries = search_queries("original?", Rewrite("hypothetical passage", ("kw1", "kw2")))
    assert queries[0] == ("original", "original?")
    assert dict(queries)["passage"] == "hypothetical passage"
    assert dict(queries)["keywords"] == "original? kw1 kw2"


def test_an_empty_rewrite_adds_no_queries() -> None:
    assert search_queries("q?", Rewrite("", ())) == [("original", "q?")]
