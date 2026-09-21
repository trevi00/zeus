# DB explorer and ontology universe ? one delivery frame

2026-09-21. Codex: analysis/design/acceptance; Claude: implementation/tests; owner: actual browser
verification and deployment. User requests a DB visualization page and a 3D universe-like ontology.

## Outcome and scope

Add two integrated monitor views: DB Explorer and Ontology Universe. Actual primary configured
PostgreSQL data, read-only HTTP, current shadcn/Radix components, Lucide icons and design tokens.
Complete search/filter/select/detail flow, real graph, packaged build and API verification. No SQL
console, edits, delete, embeddings generation, promotions, imports or fabricated demo knowledge.
Existing desk, source snapshot/report, Fleet and running analysis remain unchanged. Other databases
and Fleet lane schemas are explicitly outside the first primary-database view; label source scope.

## Facts and primary research

Local inspected base 044f245: React19/Vite8 in frontend/monitor; monitoring_web.handler(snapshot,desk)
serves exact loopback routes, monitor.main wires providers; knowledge.py uses knowledge_nodes/edges;
promotion.py commits graph and promotion receipt with explicit limited authority. No graph explorer
API was found in existing monitor routes. Actual primary PG read-only count: 5 nodes, 4 edges, 79
buckets at design time; kinds goal/research/design/candidate/verification. Counts are observations,
not completeness or whole reference coverage. Never add fake nodes to make the view look richer.

Opened primary docs 2026-09-21:
- https://github.com/vasturiano/react-force-graph : React 3D package uses Three.js/WebGL, supports
  graphData, node IDs, click/hover, camera focus, finite cooldown and zoom/pan. Rolling documentation,
  not a claim of installed compatibility. Pin exact dependency/lockfile versions used by implementation.
- https://threejs.org/docs/pages/WebGLRenderer.html : renderer resource disposal and WebGL context
  support. Verify cleanup and graceful fallback in the actual component; documentation is not a test.
Use react-force-graph-3d with exact compatible dependency pins, or Three.js directly if the adapter
is demonstrably simpler. No CDN runtime script or new framework. Existing shadcn conventions apply.

## Architecture and data contract

Browser -> same-origin /api/explorer endpoints -> injected read-only Explorer provider -> bounded
parameterized PG queries in READ ONLY transactions -> sanitized typed envelopes. Reuse existing
loopback Host gate and safe text handling. Never expose DSN, embeddings, environment, raw model
outputs, credentials, arbitrary JSON body or SQL. Metadata cannot imply content verification.

Implement catalog (table schemas and bucket names/counts), paginated records and graph via explicit
GET endpoints under /api/explorer, wired by monitor.py at web startup with no DB mutation/migration.
No provider/config =>503 fixed unavailable, not empty success. An inaccessible DB must not kill the
web server. Parameterized values only; no user-supplied SQL, schema or column identifiers.
Use existing configured primary schema; whitelist documents/knowledge_nodes/knowledge_edges.
Catalog may list all document buckets; record projection is a fixed safe set of identity, type,
state, timestamps, revision and evidence references, never recursive body passthrough. Missing
fields remain unknown. Detail is the same explicit safe projection with provenance and supported
relations, not SELECT * serialization. State visibly that raw/private payload is omitted.

Return schema version, source scope, observed_at, rows/nodes/edges, applied limit, has_more/cursor
and bounded error reason. Stable cursor/keyset order; default50 max100 rows, default200 max500 nodes,
max1000 edges with both endpoints in returned nodes. Truncation must be visible. Search max200chars,
kind/repository/bucket filters validated, invalid params400. Query deadline3s, connection deadline3s;
no unbounded retry or automatic write. SQL timeout/DB failure503 and safe reason, no exception text.
Get graph and counts in one consistent read transaction; don't display dangling relation endpoints.

Trust: presence in knowledge_nodes and kind='verification' do NOT independently prove acceptance.
Promoted provenance comes from matching actual promotions receipt and node membership/repository,
with the receipt's limited authority: verified execution/review provenance, not truth of all prose,
merge or deployment. No matching receipt => unverified/unknown. Read-only display never promotes.
A node's role and its trust state are separate. Candidate role inside a verified provenance graph
must not silently become accepted code. Preserve source_ref/revision and evidence IDs as plain text.

## User experience / visual specification

Navigation labels in Korean: ??? ??, ????. DB explorer: compact catalog sidebar, searchable
paginated table, selected-record detail panel, source/time/status header. Ontology: spacious near-black
navy universe canvas, restrained cyan/violet/amber node glows, thin directional links, project/repository
clusters, legible hover/selection labels. Cluster distance is layout, not semantic confidence.
Decorative stars are noninteractive and explicitly separate from data; never counted as records.

Top search + repository/kind/trust filters; legend and visible node/edge count/truncation banner;
click node or table row to focus camera and open right-side panel showing identity/type/trust/source/
revision/linked nodes/evidence. Reset-view and pause-motion controls; no forced perpetual orbit.
Seed initial positions deterministically from IDs and cap force simulation; do not reset camera on
unrelated status refresh. Lazy load 3D only when its tab opens. Pause/dispose on unmount/context loss.
Honor reduced motion, cap pixel ratio, handle resize, keyboard accessible list alternative; WebGL
unavailable or lost => explicit fallback list with the same selectable data, not a blank panel.
Responsive at1440/768/390; drawer on narrow widths. Browser fetch uses abort+5s deadline, last-good
stale indication, no overlapping requests; late response cannot replace a newer filter result.
No unsafe nodeLabel HTML from DB strings; use escaped/plain text labels and React text rendering.

## Acceptance matrix and one batch

Normal: actual DB catalog->bucket->record and graph->node->provenance flow, consistent IDs/counts.
Empty: honest empty state, not demo nodes. Failure: DB down/query timeout/invalid query/unknown ID,
safe status and retained stale view. Concurrency: bounded read snapshot, cursor, stale fetch race,
no state mutation. Cleanup: abort in-flight, release connections/WebGL resources, no background
animation after tab closes. Platform: Windows server + Linux CI; desktop/mobile browser layouts;
physical Samsung device testing remains later, no claim from viewport emulation. Security: foreign
Host, SQL injection values, secret-shaped strings, HTML labels and raw properties never leak/execute.
Regression: desk and status routes behave unchanged. Unrelated POST remains refused. Large graph
bounded by API with visible limits; no million-node/perfect-frame-rate performance claim.

Worker implements API+UI together on interface lane. Allowed paths: adapters/database_explorer.py,
adapters/monitoring_web.py, monitor.py, focused tests, frontend/monitor/, packaged observatory build,
docs/contracts.md and this directory. Reuse existing design system; no unrelated frontend rewrite.
Build before final commit; packaged hashed assets must match fresh npm build. No live service restart,
production DB writes, credentials, model calls, merge or deploy. Tests may use explicitly labelled
fixtures/injected faults; product acceptance must use actual owner DB/browser, not mock data.

Checks: python -m pytest tests/test_database_explorer.py tests/test_monitoring.py -q -p no:cacheprovider
python -m ruff check . --no-cache
python -m codex_harness.adapters.monitor_frontend_checks
Also npm ci, npm run lint, npm run build in frontend/monitor to produce assets. Legacy answer.tests
contains replay-supported exact successful Python commands above; npm commands/results go in summary.
Unavailable prerequisites are reported, not claimed passing. Owner verifies actual browser with live
read-only data, API/PG no-write evidence, independent review, CI and reversible deployment. Finish only
when these checks support usable pages; documents or a rendered mockup alone do not finish delivery.
