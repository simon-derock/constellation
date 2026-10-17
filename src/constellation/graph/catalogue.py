from functools import cache
from importlib.resources import files


@cache
def cypher(name: str) -> str:
    # reviewed query text lives in .cypher files; code refers to queries by name only
    return files("constellation.graph").joinpath("cypher", f"{name}.cypher").read_text()
