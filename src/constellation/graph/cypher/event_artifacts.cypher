// event_artifacts — the artifacts an event produced, with the key that names their kind
// params: $event (Event.eid)
MATCH (:Event {eid: $event})-[pr:PRODUCED]->(a:Artifact)
RETURN a.doc_id AS artifact, pr.key AS key, pr.subsystem AS subsystem, a.born AS born
ORDER BY artifact, key
