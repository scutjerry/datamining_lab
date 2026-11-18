// 实验6 知识图谱导入脚本（Neo4j 5.x）
// 用法：把 nodes.csv、edges.csv 复制到 <NEO4J_HOME>/import/，
//       在 Neo4j Browser 执行  :source import_neo4j.cypher

CREATE CONSTRAINT scenicarea_id IF NOT EXISTS FOR (n:ScenicArea) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT poi_id IF NOT EXISTS FOR (n:POI) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT route_id IF NOT EXISTS FOR (n:Route) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT advice_id IF NOT EXISTS FOR (n:Advice) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT timeslot_id IF NOT EXISTS FOR (n:TimeSlot) REQUIRE n.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
WITH row WHERE row.label = 'ScenicArea'
MERGE (n:ScenicArea {id: row.id})
SET n.name = row.name, n.scenic = row.scenic, n.extra = row.extra;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
WITH row WHERE row.label = 'POI'
MERGE (n:POI {id: row.id})
SET n.name = row.name, n.scenic = row.scenic, n.extra = row.extra;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
WITH row WHERE row.label = 'Route'
MERGE (n:Route {id: row.id})
SET n.name = row.name, n.scenic = row.scenic, n.extra = row.extra;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
WITH row WHERE row.label = 'Advice'
MERGE (n:Advice {id: row.id})
SET n.name = row.name, n.scenic = row.scenic, n.extra = row.extra;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
WITH row WHERE row.label = 'TimeSlot'
MERGE (n:TimeSlot {id: row.id})
SET n.name = row.name, n.scenic = row.scenic, n.extra = row.extra;

LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
WITH row WHERE row.type = 'HAS_ROUTE'
MATCH (a {id: row.source}), (b {id: row.target})
MERGE (a)-[r:HAS_ROUTE]->(b);

LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
WITH row WHERE row.type = 'HAS_ADVICE'
MATCH (a {id: row.source}), (b {id: row.target})
MERGE (a)-[r:HAS_ADVICE]->(b);

LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
WITH row WHERE row.type = 'PART_OF'
MATCH (a {id: row.source}), (b {id: row.target})
MERGE (a)-[r:PART_OF]->(b);

LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
WITH row WHERE row.type = 'RELATES_TO'
MATCH (a {id: row.source}), (b {id: row.target})
MERGE (a)-[r:RELATES_TO]->(b);

LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
WITH row WHERE row.type = 'LOCATED_IN'
MATCH (a:POI {id: row.source}), (b:ScenicArea {id: row.target})
MERGE (a)-[r:LOCATED_IN]->(b)
SET r.scope = CASE WHEN row.extra = '' THEN 'in_scenic' ELSE row.extra END;

// STEP 边带属性，直接 SET 成关系属性（Schema 第9节）
LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
WITH row WHERE row.type = 'STEP'
MATCH (a:Route {id: row.source}), (b:POI {id: row.target})
MERGE (a)-[r:STEP {order: toInteger(row.order)}]->(b)
SET r.time_slot   = row.time_slot,
    r.activity    = row.activity,
    r.transport   = row.transport,
    r.duration_min = CASE WHEN row.duration_min = '' THEN null
                          ELSE toFloat(row.duration_min) END;