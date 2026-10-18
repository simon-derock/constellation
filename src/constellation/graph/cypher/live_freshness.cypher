// live_freshness — the newest source timestamp the graph has absorbed, and how many repositories report
// params: none
MATCH (c:Cursor)
RETURN max(c.since) AS newest, count(c) AS repositories
