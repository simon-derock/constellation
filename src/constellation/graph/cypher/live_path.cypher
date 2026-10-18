// live_path — the shortest chain of collaborators between two people, as aliases; empty when they are not connected
// params: $from (Person.alias), $to (Person.alias)
MATCH (a:Person {alias: $from}), (b:Person {alias: $to})
RETURN [n IN nodes(shortestPath((a)-[:COLLABORATES*..8]->(b))) | n.alias] AS path,
       length(shortestPath((a)-[:COLLABORATES*..8]->(b))) AS hops
