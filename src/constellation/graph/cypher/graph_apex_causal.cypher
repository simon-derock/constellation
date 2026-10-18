// graph_apex_causal — events and the causal links between them inside a day window, as edges for the graph view
// params: $from (int day), $to (int day), $limit (int)
MATCH (a:Event)-[c:CAUSES]->(b:Event)
WHERE a.day >= $from AND b.day <= $to
RETURN a.eid AS sid, 'Event' AS stype, a.type + ' · day ' + toString(a.day) AS slabel,
       b.eid AS tid, 'Event' AS ttype, b.type + ' · day ' + toString(b.day) AS tlabel, c.link_type AS rel
ORDER BY c.day, sid, tid, rel
LIMIT $limit
