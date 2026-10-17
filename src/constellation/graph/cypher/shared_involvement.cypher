// shared_involvement — artifacts of $event the actor met through an earlier event they took part in
// params: $actor (Person.name), $event (Event.eid), $day (int)
MATCH (t:Event {eid: $event})-[:PRODUCED]->(a:Artifact)<-[:PRODUCED]-(e:Event)<-[:INVOLVED_IN]-(:Person {name: $actor})
WHERE e.day <= t.day AND a.born <= $day
RETURN DISTINCT a.doc_id AS artifact
ORDER BY artifact
