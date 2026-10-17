// event_info — an event's type, day, people, and whether a design page it spawned exists in the corpus
// params: $event (Event.eid)
MATCH (e:Event {eid: $event})
OPTIONAL MATCH (e)-[:PRODUCED {key: 'confluence'}]->(page:Artifact)
WITH e, count(page.kind) > 0 AS page_in_corpus
OPTIONAL MATCH (p:Person)-[:INVOLVED_IN]->(e)
WITH e, page_in_corpus, p ORDER BY p.name
RETURN e.type AS type, e.day AS day, coalesce(e.spawned_doc, false) AS spawned_doc, page_in_corpus,
       collect(p.name) AS actors
