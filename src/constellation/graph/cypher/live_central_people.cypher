// live_central_people — PageRank over the collaboration graph: people who open items in the same repositories
// params: $limit (int)
CALL algo.pageRank('Person', 'COLLABORATES') YIELD node, score
RETURN node.alias AS person, round(score * 1000000) / 1000000 AS score
ORDER BY score DESC, person
LIMIT $limit
