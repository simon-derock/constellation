// live_repos — tracked items per repository, largest first
// params: $limit (int)
MATCH (i:Item)
RETURN i.repo AS repo, count(i) AS items
ORDER BY items DESC, repo
LIMIT $limit
