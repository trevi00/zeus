# Spec Bundle / Zeus SDD boundary comparison

Scope: pinned Baldrix cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2; current Zeus working-source hashes in supporting-evidence.json. This is source review, no execution or incorporation approval.

Baldrix doc-writer.md maps to cli/spec_bundle_emit.py, validators/spec_bundle.py, lib/spec_bundle.py, lib/spec_facets.py and tests/test_spec_bundle_emit.py (all read in full). Structural extraction transitively imports extractors/base, logical, er; those bodies and lib.testgen have NOT been read in this partition. PyYAML and validator registry graduation are unresolved execution dependencies. Six emitter tests read, NOT RUN; testing requires pinned dependencies, isolated source and temporary output. The existing 17 tech-stack passes do not cover this feature.

Confirmed source defects/limitations:
- emit(root,out) does not prevent root==out (forward tests explicitly require it), contradicting read-only-root documentation. Domain strings from --domains are used as paths without traversal/absolute/drive/symlink rejection. Output is not atomically confined.
- Existing authored .feature files are preserved, but manifest personas are reset to TODO each emit. Missing source signal leaves stale old facets. Duplicate normalized endpoint IDs silently discard later endpoints.
- Invalid/missing manifest or unreadable feature fails soft to empty data. Empty declared domains skip manifest comparison. TODO scaffolds satisfy validator; no required GWT, oracle, active requirements, stable semantic identity history, persona/schema-version validation.
- Facet validation checks known facet kind and nonempty unique IDs only. Malformed elements can be dropped. No cross-facet semantic integrity.
- Validator no-bundle result is PASS; main only discovers CLAUDE_HOME/spec, CLI exit0 even problems. These are advisory shape checks, never full specification correctness.

Zeus domain/sdd.py, adapters/sdd.py and tests/test_sdd.py read in full:
- validate_spec requires exact fields/schema, bounded nonempty requirements/scenarios/devices, unique stable IDs, active-scenario coverage of all active requirements, valid requirement/device links and explicit Given/When/Then lists. Unknown authority fields and empty scope fail.
- Previous requirement statement/risk changes require new ID; deleted requirement/scenario IDs must be retired; retired IDs cannot resurrect. Source does NOT compare prior active scenario given/when/then/title/bindings for semantic-ID reuse. Existing tests specifically cover requirement meaning and scenario retirement, not all scenario semantic changes. This is a narrower proven contract, not a claim every identity risk is solved.
- parse_json rejects duplicate keys; local input is bounded1MiB. write_export permits review.html or replay.py.review, uses exclusive creation and only accepts byte-identical existing files. It does not overwrite authored content; it is not a sandbox confinement API.
- propose_scenarios preserves observations and reports structural coverage, missing/orphan/gap state. It never converts observed behavior to an expected oracle; requires human oracle review.
- gate_report all8stages blocked; acceptance_passed=false,release_authorized=false,human_authority_configured=false. Imported flags/report claims cannot authenticate human or actual device run.
- replay_source requires concrete Android build/app, rejects financial and multi-scenario until reset integration, requires every oracle mapped to assertion, environment-only input parameters. Generated code is unexecuted and .py.review avoids automatic collection. Device_probe is discovery only, not an acceptance run.
- Tests include duplicate JSON/export/nooverwrite/HTML escaping/empty scope/retired IDs/observation gaps and real PostgreSQL integration definitions. NONE were executed by this review. Appium/ADB/template/application.sdd/transitive imports are not fully reviewed here, so no complete SDD subsystem claim.

Decision: retain Zeus stricter contracts and permanently blocked current acceptance/release authority. A future stack-neutral spec adapter must translate source claims into draft observations/requirements with explicit provenance; never import Baldrix empty/TODO PASS or automatic approval. All licenses/private proof links remain unverified.
