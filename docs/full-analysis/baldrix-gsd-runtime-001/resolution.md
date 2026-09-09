# Root / actual Claude execution-evidence resolution

The [root observations](root-initial.md) and [actual Claude review](claude-discussion.md)
agree on 13 original Git tests passing only after adding process reaping, four
demonstrated unsafe behaviors across six component observations, and the strict
boundary between successful observation and product acceptance. The actual Claude
CLI resumed its independent bin002 source review; its new work was read-only review
of retained execution evidence, not another source execution or new independent
full-body pass. Raw prompt/output/stderr/receipt are retained beside this report.

The first cancelled suite and diagnostic termination remain in the record.
`verify_evidence.py` checks source Git blobs and raw hashes, all five attempts,
program identities, recorded cleanup, the single `--init` wrapper difference,
actual test counts and component outputs. This verifies retained evidence; it
does not turn the counterexamples into passing regression or acceptance tests.

## Corrections and limits accepted after discussion

- The foreign-branch fixture does contain the task's PLAN/SUMMARY. It proves that
  the branch name does not constrain selection and that this branch is deleted.
  It does not reproduce deletion of a long-lived feature worktree without quick
  artifacts. The broader all-noncurrent selection remains a static finding.
- The PID observations show 38 Git zombies and exactly 64 total threads at four
  samples, followed by success under the single `--init` change. No fork EAGAIN
  return or original pre-adoption parent chain was captured; each original arm
  ran once. This is strong controlled evidence, not a measured recurrence rate.
- The source checks publish a before tree hash and comparison boolean, not an
  independently recorded after-map/hash. The wrapper actually recomputes the map;
  the verifier also checks current bytes. Historical receipts are not rewritten
  to pretend that an after-hash was captured. Future recorder revisions should
  publish both maps/hashes and timestamps explicitly.
- The diagnostic program digest is under `component_program_sha256`; the key is
  generic/misleading but resolves to the correct retained diagnostic program.
- The control merge's returned code commit is not final HEAD. Claude correctly
  points to SUMMARY-tip peeling as the explanation for this fixture, where
  `reconcile_commit_hash` is null. Root's general statement that a later cleanup
  commit *can* change HEAD must not be read as the observed cause in this control.
- The phase fixture contains only phases 5–7 while declaring total 7 beforehand.
  Duplicate surviving headings and their divergence from directories are directly
  demonstrated. The differing STATE body/frontmatter totals are observed too, but
  not a proof that the sparse starting fixture was globally consistent. Default
  metadata must not be described as fabricated user evidence without that context.
- The profile inputs use an inert labelled sentinel. No actual password, session
  content or transmission was exercised. LOW-confidence dimension rendering and
  summary/global directive policy remain distinct paths.

## Timeout process identity

Claude flagged Node at PID 1 and `timeout` as its child as unexpected. The runtime
package inventory identifies BusyBox 1.37.0-r31; the separate
[binary identity observation](runtime-tool-identity-v2.json) resolves `/usr/bin/timeout`
to `/bin/busybox`. BusyBox's versioned timeout source creates a detached timer
descendant, then replaces the original process with the requested command.
That design explains how Node can retain PID 1 while the timer is adopted beneath
it. This is an inference connecting the observed process tree with upstream source,
not a byte-for-byte audit of Alpine's patched binary. [BusyBox 1.37.0 source](https://raw.githubusercontent.com/vda-linux/busybox_mirror/1_37_0/coreutils/timeout.c)

The first identity command assumed `/bin/readlink`, which this image lacks and
returned 127. Its separate `runtime-tool-identity.json` remains unchanged. The
second used the qualified Node filesystem API to resolve the same path, with
no original source mounted or executed in either identity observation.

## Required Zeus changes after whole analysis

1. Give isolated runners a child reaper while retaining resource, network and
   filesystem boundaries; distinguish infrastructure cancellation from source failure.
2. Bind merge selection to task ownership, valid base ancestry and current revision.
   Exact base equality with current HEAD would reject intentional divergent cases.
3. Keep stable phase IDs separate from display numbering; validate the whole
   requirement/dependency mapping before publishing a definition change.
4. Normalize accepted profile fields and sanitize every output surface once,
   deriving redaction reporting from that same transformation.

These changes are not yet implemented or adopted. FA-014, FA-015, FA-026 and FA-032
remain unresolved; this report supplies advisory evidence for them. There was no
issue close/reopen, operating deployment replacement, Windows/WSL qualification,
human acceptance or device execution. This batch adds zero primary coverage.
