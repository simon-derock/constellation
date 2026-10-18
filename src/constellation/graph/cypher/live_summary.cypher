// live_summary — how many tracked items are in each state right now, by kind
// params: none
MATCH (i:Item)-[:HAS_CLAIM]->(c:Claim {predicate: 'state'}) WHERE c.valid_to IS NULL
RETURN i.kind AS kind, c.value AS state, count(i) AS items
ORDER BY kind, state
