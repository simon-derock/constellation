// live_bridge_people — betweenness centrality: people who sit on the most shortest paths between others.
// The source sample is seeded so the ranking replays. Engine memory grows with the sample size, so it is kept just
// above the people count (exact today): a sample of 100000 exhausted a 3 GB engine on 347 people.
// params: $limit (int)
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES'], samplingSize: 512, samplingSeed: 7}) YIELD node, score
RETURN node.alias AS person, round(score * 1000) / 1000 AS score
ORDER BY score DESC, person
LIMIT $limit
