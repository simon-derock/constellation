// event_types — the vocabulary of event kinds in this tenant, for constraining plans to real types
MATCH (e:Event)
RETURN DISTINCT e.type AS type
ORDER BY type
