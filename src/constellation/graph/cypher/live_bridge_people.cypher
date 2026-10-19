// live_bridge_people — betweenness centrality: people who sit on the most shortest paths between others.
// The source sample is seeded so the ranking replays. Engine memory grows with the sample size, about half a megabyte
// per source because the working matrices span every node: 100000 exhausted a 3 GB engine, and 512 peaked near 390 MB
// and ran a 512 MB host out of memory. It is kept just above the people count (347, so exact today).
// params: $limit (int)
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES'], samplingSize: 360, samplingSeed: 7}) YIELD node, score
RETURN node.alias AS person, round(score * 1000) / 1000 AS score
ORDER BY score DESC, person
LIMIT $limit
