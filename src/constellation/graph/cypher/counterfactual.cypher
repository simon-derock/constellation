// counterfactual — would removing $cause have changed $effect under mechanism $link_type?
// same-mechanism redundancy: the effect survives if another cause of the same type remains
// params: $cause, $effect (Event.eid), $link_type (string)
MATCH (c:Event)-[:CAUSES {link_type: $link_type}]->(:Event {eid: $effect})
WITH DISTINCT c.eid AS eid ORDER BY eid
WITH collect(eid) AS causes
RETURN $cause IN causes AS linked, [x IN causes WHERE x <> $cause] AS alternatives
