// event_types_on_day — which kinds of events happened on a day, so a failed lookup can be corrected
// params: $day (int)
MATCH (e:Event {day: $day})
RETURN e.type AS type, count(e) AS events
ORDER BY type
