# Independent Codex seam-registry review

Root read all seven primary bodies, 24,216 bytes, at Baldrix
`cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2` before any Claude response for this
partition. Scope: `bdb8b8af3b18af7b8b51c423b22f613a6bc56670e522a28bda0aaec9731d2020`.
Original imports, executions and tests are zero. Direct CLI/config/test bodies and
extractors.base helper bodies remain unread in this initial checkpoint. Prior agents'
reports identify further work but do not count as root source reads.

## Deterministic parity and transform authority

Wire-value rather than symbol comparison, explicit LOW_FIDELITY/NEEDS_TRANSFORM,
and separation from blocking eligibility are useful guards. No LLM/embedding is used
in these bodies. However fidelity is an unchecked string: only exact LOW limits status;
other unknown labels can reach DRIFT/OK. values() deduplicates and drops None before
parity. Empty resolved sets can yield OK when the supplied fidelity is not LOW. These
are direct API contract candidates, not proof actual CLI supplies such objects.

The value_map injectivity check only considers explicitly mapped values, ignoring
collisions against unchanged values. Producer {A,B}, map A->B can collapse to {B} without
an error. Affix stripping can likewise collapse prefixed and already-unprefixed values;
that branch has no collision check. Config types/targets, non-string values and transform
shape are unvalidated here and may raise. _is_identity treats an explicitly declared
identity like no transform, so disjoint nonempty namespaces remain NEEDS_TRANSFORM even
though the doc refers to NO declared transform. These policies need a precise versioned
contract and all-value injectivity, not an inferred approval from a map's presence.

## Extractor coverage and fidelity

Java uses the first enum and accessor from a file but scans ALL member-looking lines
in that file. It cannot establish enum ownership for every member. The accessor's
returned field name is discarded: any simple return-variable becomes ctor-string and
the first string literal in each argument list is chosen, without resolving constructor
parameter/field assignment or actual serialization. Escaped source literals remain
escaped text. One/two-character constants, nested arguments, multiple members per line,
unterminated shapes and omitted symbols can be missing while the parsed subset is HIGH.
Existing fallback to COMPUTED/LOW for unparseable/no accessor is valuable but does not
prove all omissions or mixed-enum cases are downgraded. Historical fleet shapes are
source assertions, not current measured universal syntax.

Dart similarly chooses one enum but its string-member regex scans the entire file.
It ignores constructor/accessor semantics and can match outside the selected enum.
Bare-member fallback bounds a region, which is useful, but tokenizes every identifier
there rather than parsing enum constants; computed constructor arguments can become
invented wire values if the string path finds none. A mixture with some string members
can omit unresolved members and still be HIGH. EnumContract.rule stays dart-string-arg
even when WireValue.rule is dart-bare-member. Escapes, quotes, multiple same-line members
and file-order caps need explicit coverage, not the claim that every enum is extracted.

Proto records tag:name only, omitting field type, modifiers, options, reserved ranges,
service and other contract properties. Its simple line regex misses map/option syntax
and cannot account for all same-line fields. A message's substring includes nested
messages, so nested field matches can be attributed to its parent. Global seen uses only
the short message name, suppressing same names in distinct files/packages/scopes, even
if an earlier same-named message produced no fields. Brace matching does not understand
strings and accepts end-of-file for an unmatched block. Every nonempty parsed subset is
HIGH regardless of unsupported/missed constructs. Actual wire-compatibility judgments
require the authoritative language contract and fuller extraction, not these names alone.

Java/Dart/Proto share comment-removal/read helpers not yet read here. Their line numbers
are calculated after transformed text and need comparison with original byte spans.
Proto/Dart traversal caps are applied before sorting; omitted paths and read failures
do not get explicit per-input outcomes. Source identity/hash, immutable snapshot, error
denominators, supported dialect/version and symlink/capability bounds are not in these
returned records. Their actual caller may add guards; that closure remains open.

## Registry and Zeus adaptation

The registry's stale SocketAction-only scope conflicts with its Proto message extension
and broader Dart Action families. Extension requires editing the registry despite the
phrase zero edits to existing files. Protocol conformance is not runtime checked beyond
a non-None export; constructor and stack.lower errors propagate. Clarify actual scope,
not a hidden self-certification through HIGH or registry membership.

Zeus can preserve explicit stack-specific extraction and transform-aware set comparisons
as typed observations. Bind exact source/schema/parser versions, supported and omitted
constructs, original byte spans, approved producer/consumer identity and transform policy.
Only complete eligible comparisons can inform a blocking gate; actual product behavior,
human SDD acceptance and model qualification remain separate receipts. PG owns runtime
observations/approvals and Git owns definitions. Whole caller/config/test closure,
original executions, licenses, Windows/Linux/WSL behavior and independent discussion are
still required. No adoption, implementation or deployment is claimed here.
