// live_recent_changes — the newest observed or derived changes of state, assignees or labels, newest first
// params: $limit (int)
MATCH (i:Item)-[:CHANGED]->(h:Change)
RETURN i.id AS item, i.title AS title, h.predicate AS predicate, h.old AS old, h.new AS new, h.at AS at
ORDER BY at DESC, item, predicate
LIMIT $limit
