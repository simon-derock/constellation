// live_components — weakly connected components of the collaboration graph: how many, and how large
// params: none
CALL algo.WCC({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES']}) YIELD node, componentId
WITH componentId, count(node) AS size
RETURN size, count(*) AS components
ORDER BY size DESC
