// live_search_vector — the items nearest to an embedding, from the engine's HNSW index; distance is cosine, lower is closer
// params: $vector (list of floats), $k (int)
CALL db.idx.vector.queryNodes('Item', 'embedding', $k, vecf32($vector)) YIELD node, score
RETURN node.id AS item, node.title AS title, node.repo AS repo, round(score * 1000000) / 1000000 AS distance
ORDER BY distance, item
