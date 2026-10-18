// live_expertise — who has opened the most items in a repository; people are aliases, never logins
// params: $repo (owner/name), $limit (int)
MATCH (i:Item {repo: $repo})-[:AUTHORED_BY]->(p:Person)
RETURN p.alias AS person, count(i) AS items
ORDER BY items DESC, person
LIMIT $limit
