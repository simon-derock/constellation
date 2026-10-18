// live_state_as_of — how many items were in each state at epoch second $at; half-open [valid_from, valid_to)
// params: $at (int epoch seconds)
MATCH (i:Item)-[:HAS_CLAIM]->(c:Claim {predicate: 'state'})
WHERE c.valid_from <= $at AND (c.valid_to IS NULL OR $at < c.valid_to)
RETURN i.kind AS kind, c.value AS state, count(i) AS items
ORDER BY kind, state
