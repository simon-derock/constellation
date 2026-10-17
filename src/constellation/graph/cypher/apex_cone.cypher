// apex_cone — artifacts in an actor's visibility cone on simulation day $day (ADR-0005)
// params: $actor (Person.name), $day (int, simulation day)
MATCH (p:Person {name: $actor})-[:HAS_ROLE]->(:Role)-[:CAN_OPEN]->(s:Subsystem)
WITH p, collect(s.name) AS access
MATCH (e:Event)-[pr:PRODUCED]->(a:Artifact)
WHERE 1 <= e.day AND e.day <= $day AND pr.subsystem IN access
  AND ((p)-[:INVOLVED_IN]->(e) OR any(c IN e.broadcast WHERE c IN access))
// sorted before collect: a proof hash must not depend on traversal order
WITH DISTINCT a.doc_id AS doc_id ORDER BY doc_id
RETURN collect(doc_id) AS visible
