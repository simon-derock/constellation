// graph_live_network — the most connected people and the collaboration links among them, as edges for the graph view
// params: $people (int), $limit (int)
MATCH (p:Person)-[:COLLABORATES]->(q:Person)
WITH p, count(q) AS degree
ORDER BY degree DESC, p.alias
LIMIT $people
WITH collect(p.alias) AS tops
MATCH (a:Person)-[c:COLLABORATES]->(b:Person)
WHERE a.alias < b.alias AND a.alias IN tops AND b.alias IN tops AND c.repos >= 1
RETURN a.alias AS sid, 'Person' AS stype, a.alias AS slabel, b.alias AS tid, 'Person' AS ttype, b.alias AS tlabel,
       'COLLABORATES' AS rel
ORDER BY c.repos DESC, sid, tid
LIMIT $limit
