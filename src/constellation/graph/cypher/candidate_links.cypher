// candidate_links — causal links whose cause is a $event_type event on $day, filtered by effect type and mechanism,
// ranked by how directly the named $people reach the cause: involved themselves, then through a shared artifact
// a named mechanism fixes its own cause and effect types in this graph, so the type filters apply only without one
// params: $day (int), $event_type, $target_type, $mechanism (strings, '' for any), $people (list of names)
MATCH (c:Event {day: $day})-[x:CAUSES]->(e:Event)
WHERE ($mechanism <> '' AND x.link_type = $mechanism)
   OR ($mechanism = '' AND ($event_type = '' OR c.type = $event_type) AND ($target_type = '' OR e.type = $target_type))
OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(c)
WITH c, x, e, collect(DISTINCT p.name) AS involved
OPTIONAL MATCH (c)-[:PRODUCED]->(:Artifact)<-[:PRODUCED]-(:Event)<-[:INVOLVED_IN]-(r:Person)
WHERE r.name IN $people
WITH c, x, e, involved, collect(DISTINCT r.name) AS related
WITH c, x, e,
     size([n IN $people WHERE n IN involved]) AS direct,
     size([n IN $people WHERE n IN related AND NOT n IN involved]) AS via
RETURN c.eid AS cause, x.link_type AS mechanism, e.eid AS effect, e.type AS effect_type,
       substring(coalesce(c.summary, ''), 0, 110) AS why
ORDER BY direct DESC, via DESC, cause, effect
LIMIT 16
