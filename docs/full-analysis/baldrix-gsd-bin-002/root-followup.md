# Direct trace and comparison after the independent pass

All findings remain static. No upstream import, command, collection or test ran.

1. `core.cjs` 209–404 shows that safeReadFile returns null for any read error,
   while loadConfig can write migrations and sub-repository synchronization.
   Therefore an initializer/model resolution is not necessarily read-only.
   A present planning directory with malformed config returns defaults, not global
   defaults. Top-level values precede nested values. This can make a nested policy
   edit ineffective. The normalized shape omits intel; intel's separate config
   read is a divergent authority, not automatically a security defect.
2. `core.cjs` 531–628 passes Git as an argv array (real shell-injection defense)
   but gives spawnSync no timeout. The planning lock creates with wx, then deletes
   by pathname in finally without an owner token. After ten seconds it unlinks
   the lock and calls fn without reacquiring. Thirty-second mtime recovery also
   lacks a live-owner check. A callback EEXIST can be caught as acquisition EEXIST.
   These weaken the phase helpers' locking claims; no race was executed.
3. `core.cjs` 648–680 explicitly rejects separators and '..' in project/workstream
   names. That defense must be preserved, while symlink containment, OS names and
   all callers are separate obligations. `security.cjs` 1–130 validates existing
   real paths and one parent fallback. init validates the skill directory, then
   separately checks SKILL.md existence: it does not validate a symlinked SKILL.md
   leaf, nor establish protection from a later path swap. No symlink probe ran.
4. `core.cjs` 1230–1362 confirms installation-file existence rather than role
   capability, override-before-omit model precedence, and unknown-role sonnet
   fallback. `config.cjs` 400–454 accepts quality/balanced/budget/adaptive through
   the table; `verify.cjs` 625–644 accepts quality/balanced/budget/inherit. This is
   a concrete setter/health/resolver disagreement, not model qualification.
5. `gsd-tools.cjs` 160–265, 435–494, 565–704 and 900–1049 directly routes primary
   helpers. expectedBase is passed unchanged; no check in merge-back consumes it.
   Intel paths are unscoped root .planning; its relative entry checks still use
   process cwd despite --cwd support. Profile answers are passed as a string,
   without reading an answers file. generate-claude-md forwards force but the full
   primary never reads that option. Other intervening router paths remain unread.
6. The actual `merge-back.test.cjs` 1–444 was freshly read in full: 13 node:test
   definitions, not '12 non-trivial scenarios' plus a separate extra inferred
   denominator. Scenarios construct real temp Git repositories and subprocesses;
   none ran here. Main advances in both test 2 and test 7. An assertion that
   expectedBase must equal current HEAD would contradict the supported non-FF
   case. Inert expectedBase is established; its correct contract should separate
   planned base ancestry, selected worktree ownership and current revision fencing.
   The file does not test mismatched claimed base, mixed success/conflict across
   two worktrees, cleanup/reconcile failure, or unrelated worktree ownership.
7. Claude's milestone claim needs narrowing: milestones_updated:true follows an
   unconditional successful write on normal return; failed writes throw before the
   result. The problem is lack of semantic/idempotent acceptance and multi-file
   transaction evidence, not proof that this flag is returned after a thrown write.
   fs.existsSync archive flags likewise cannot prove this invocation created them.
8. Claude's initial primary line ends include an extra EOF display line. Raw
   source has 1522/660/378/267/282/70/931/1048 lines, respectively. Metadata uses
   raw lines; the original report remains unchanged as historical model output.

Useful material to adapt after closure: actual Git scenario assertions, explicit
missing/conflict fields, deterministic ordering, CRLF-aware blob comparison,
typed answer options, visible warning/partial states and bounded config flags.
Reject automatic promotion from these declarations to human acceptance, approved
knowledge, process liveness or model qualification. No runtime feature is absorbed
by writing this report.
