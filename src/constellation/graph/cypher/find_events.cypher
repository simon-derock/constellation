// find_events — events on simulation day $day, optionally of $event_type, involving every name in $actors
// params: $day (int), $event_type (string, '' for any), $actors (list of names, [] for any)
MATCH (e:Event {day: $day})
WHERE $event_type = '' OR e.type = $event_type
OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(e)
WITH e, p ORDER BY p.name
WITH e, collect(p.name) AS actors
WHERE all(a IN $actors WHERE a IN actors)
RETURN e.eid AS event, e.type AS type, e.day AS day, actors, substring(coalesce(e.summary, ''), 0, 240) AS summary
ORDER BY event
LIMIT 25
