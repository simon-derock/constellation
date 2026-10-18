// graph_apex_ownership — who owns which domain, as edges for the graph view
// params: none
MATCH (p:Person)-[o:OWNS]->(d:Domain)
RETURN p.name AS sid, 'Person' AS stype, p.name AS slabel, d.name AS tid, 'Domain' AS ttype, d.name AS tlabel,
       'OWNS' AS rel
ORDER BY sid, tid, o.from
