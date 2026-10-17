// absence — did a $response_type follow trigger $trigger? the searched space is returned either way
// params: $trigger (Event.eid), $response_type (string)
MATCH (:Event {eid: $trigger})-[:EXPECTS]->(x:Expectation {response_type: $response_type})
OPTIONAL MATCH (x)-[:MET_BY]->(r:Event)
RETURN x.responded AS responded, r.eid AS response_event, x.search_space AS searched
