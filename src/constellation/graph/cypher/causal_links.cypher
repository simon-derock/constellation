// causal_links — every explicit causal link into or out of an event, with its mechanism
// params: $event (Event.eid)
MATCH (c:Event)-[x:CAUSES]->(e:Event)
WHERE c.eid = $event OR e.eid = $event
RETURN c.eid AS cause, c.type AS cause_type, substring(coalesce(c.summary, ''), 0, 200) AS cause_summary,
       x.link_type AS mechanism, e.eid AS effect, e.type AS effect_type, x.day AS day
ORDER BY day, cause, effect, mechanism
