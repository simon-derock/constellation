// graph_apex_escalation — who escalates to whom, as edges for the graph view
// params: none
MATCH (a:Person)-[e:ESCALATED_TO]->(b:Person)
RETURN a.name AS sid, 'Person' AS stype, a.name AS slabel, b.name AS tid, 'Person' AS ttype, b.name AS tlabel,
       'ESCALATED_TO' AS rel
ORDER BY e.day, e.eid, e.ord, sid, tid
