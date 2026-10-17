// find_events — events on simulation day $day, optionally of $event_type, ranked by the people named in $actors:
// first those directly involved, then those involved through a shared artifact (a doc they worked on, a thread)
// params: $day (int), $event_type (string, '' for any), $actors (list of names, [] for none)
MATCH (e:Event {day: $day})
WHERE $event_type = '' OR e.type = $event_type
OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(e)
WITH e, p ORDER BY p.name
WITH e, collect(DISTINCT p.name) AS actors
OPTIONAL MATCH (e)-[:PRODUCED]->(:Artifact)<-[:PRODUCED]-(:Event)<-[:INVOLVED_IN]-(r:Person)
WHERE r.name IN $actors
WITH e, actors, r ORDER BY r.name
WITH e, actors, collect(DISTINCT r.name) AS related
WITH e, actors, [a IN related WHERE NOT a IN actors] AS via_artifacts,
     size([a IN $actors WHERE a IN actors]) AS direct
RETURN e.eid AS event, e.type AS type, e.day AS day, actors, via_artifacts,
       substring(coalesce(e.summary, ''), 0, 240) AS summary
ORDER BY direct DESC, size(via_artifacts) DESC, event
LIMIT 25
