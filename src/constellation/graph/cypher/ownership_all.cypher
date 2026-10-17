// ownership_all — every ownership interval, for drawing the timeline; half-open [from, to), to absent while open
MATCH (p:Person)-[o:OWNS]->(d:Domain)
RETURN d.name AS domain, p.name AS owner, o.from AS from, o.to AS to, o.origin AS origin,
       o.start_known AS start_known, o.evidence AS evidence
ORDER BY domain, from
