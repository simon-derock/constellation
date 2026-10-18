// graph_apex_roles — which role each person holds, as edges for the graph view
// params: none
MATCH (p:Person)-[:HAS_ROLE]->(r:Role)
RETURN p.name AS sid, 'Person' AS stype, p.name AS slabel, r.name AS tid, 'Role' AS ttype, r.name AS tlabel,
       'HAS_ROLE' AS rel
ORDER BY sid, tid
