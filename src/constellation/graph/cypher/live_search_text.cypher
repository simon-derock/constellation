// live_search_text — items whose title matches a full-text query (terms joined with |), best match first
// params: $query (string), $limit (int)
CALL db.idx.fulltext.queryNodes('Item', $query) YIELD node, score
RETURN node.id AS item, node.title AS title, node.repo AS repo, round(score * 1000000) / 1000000 AS score
ORDER BY score DESC, item
LIMIT $limit
