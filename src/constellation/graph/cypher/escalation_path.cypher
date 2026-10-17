// escalation_path — the latest observed escalation chain starting at $person on or before simulation day $day
// params: $person (Person.name), $day (int)
MATCH (:Person {name: $person})-[first:ESCALATED_TO {ord: 0}]->(:Person)
WHERE first.day <= $day
WITH first ORDER BY first.day DESC, first.eid DESC LIMIT 1
MATCH (a:Person)-[hop:ESCALATED_TO {eid: first.eid}]->(b:Person)
WITH first, a, b, hop ORDER BY hop.ord
WITH first, collect(a.name) AS sources, collect(b.name) AS targets
RETURN sources[0..1] + targets AS path, first.day AS since, first.eid AS evidence
