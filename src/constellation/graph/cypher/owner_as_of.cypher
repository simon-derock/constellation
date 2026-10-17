// owner_as_of — who owned a domain on simulation day $day; half-open [from, to), to absent while open
// params: $domain (Domain.name), $day (int simulation day)
MATCH (p:Person)-[o:OWNS]->(d:Domain {name: $domain})
WHERE o.from <= $day AND (o.to IS NULL OR $day < o.to)
RETURN p.name AS owner, o.from AS since, o.origin AS origin, o.evidence AS evidence, o.start_known AS start_known
