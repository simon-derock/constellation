// live_item_history — every claim ever held about one item, with the claim that replaced it
// params: $item (owner/name#number)
MATCH (i:Item {id: $item})-[:HAS_CLAIM]->(c:Claim)
OPTIONAL MATCH (c)-[:SUPERSEDES]->(o:Claim)
RETURN c.predicate AS predicate, c.value AS value, c.valid_from AS valid_from, c.valid_to AS valid_to,
       c.origin AS origin, o.value AS replaced
ORDER BY predicate, valid_from, value
