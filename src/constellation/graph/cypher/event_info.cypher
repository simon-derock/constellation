// event_info — an event's type, day and whether a design page it spawned exists in the corpus
// params: $event (Event.eid)
MATCH (e:Event {eid: $event})
OPTIONAL MATCH (e)-[:PRODUCED {key: 'confluence'}]->(page:Artifact)
RETURN e.type AS type, e.day AS day, coalesce(e.spawned_doc, false) AS spawned_doc,
       count(page.kind) > 0 AS page_in_corpus
