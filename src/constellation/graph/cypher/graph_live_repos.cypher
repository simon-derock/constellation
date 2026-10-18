// graph_live_repos — the busiest repositories and the people active in them, as edges for the graph view
// params: $repos (int)
MATCH (r:Repo)<-[:IN_REPO]-(i:Item)
WITH r, count(i) AS items
ORDER BY items DESC, r.name
LIMIT $repos
WITH collect(r.name) AS names
MATCH (p:Person)-[:ACTIVE_IN]->(r:Repo)
WHERE r.name IN names
RETURN p.alias AS sid, 'Person' AS stype, p.alias AS slabel, r.name AS tid, 'Repo' AS ttype, r.name AS tlabel,
       'ACTIVE_IN' AS rel
ORDER BY tid, sid
