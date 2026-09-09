# Original GSD runtime observation plan

This closes a bounded execution gap from the published bin002 joint review. It
does not add new primary coverage or execute the operating harness. Original
test source is pinned Baldrix cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2,
get-shit-done/bin/lib/__tests__/merge-back.test.cjs, 444 lines / 13 declared tests.
Root read the full test body and merge implementation in the previous checkpoint;
exact raw identities and ranges are in baldrix-gsd-bin-002/supporting.json/files.json.
Other imported GSD modules were reviewed in bin001/bin003 and their records remain
limited to those scopes, not transitive runtime qualification.

The tests construct real temporary Git repositories and linked worktrees, commit
known text, invoke the original CLI in child Node processes, inspect HEAD trees
and result JSON, then remove only their temporary repositories. There are no fake
Git/provider services. Source comments claiming prior approval are not authority.
The CLI can read/write planning state and home-relative files; use disposable
HOME/TMPDIR and no credential/environment inheritance. The source tree is read-only.

The existing immutable Node 24 Alpine image is the starting runtime. Add Git in
a separate Docker build with no source or user mounts, then record the resulting
immutable image ID and installed package versions. The build may fetch packages;
original source execution must have network none, dropped capabilities,
no-new-privileges, nonroot UID, read-only root/source, bounded tmpfs, CPU/memory/PID
limits and both internal and external deadlines. Mount no Docker socket or
operating repository. No host source import or installation. Preserve initial
failure and timeout output; do not restart on an observation timeout alone.

The first observation qualifies Node/Git/tool availability in that immutable
runtime. The next invokes the original 13-test file without editing it. Result
denominators must come from actual TAP, not the declarations or exit code alone.
Additional counterexamples require a separately reviewed program and new attempt.
No Windows/WSL, actual Claude task, human acceptance, Device Farm or adoption is
proved by Linux Git fixtures. All source bytes are compared before and after.
