# Seam extraction observations

Pinned Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`; original source remained byte-identical across all 1,648 files. Read-only source and root, network none, uid 65534, dropped capabilities, no host credentials, bounded scratch/memory/CPU/process count and deadline. Exact argv/image, timestamps, stream hashes and source tree identity are in each receipt.

## Original test execution

The first `seams-unit` attempt on immutable Python Alpine image failed: 22/26 passed, four `cli.seam_scan` import paths raised `ModuleNotFoundError: yaml`. This dependency failure and its runner/streams remain unchanged. It is not an upstream assertion failure or a passing suite.

`run_units_with_yaml.py` then used the already available immutable Zeus validation image `sha256:39d4f226fa8b1ae6087b283b16d0176e9181f8aaf31dcbf0c9145e513453725a`, overriding its service entrypoint with timeout and its existing Python environment. No package installation or network occurred. `seams-unit-with-yaml`: 26/26 passed, return code 0. These are the original synthetic unit fixtures, not actual fleet acceptance.

## Original functions on actual scratch files

`component_observations.py` completed with return code 0, without method/clock/process/provider replacement. Its stdout records the exact synthetic inputs and outputs; assertions only enforce unchanged input bytes. Completion means observations were captured, not that the observed behavior satisfies Zeus requirements.

- Partial `value_map` A→B with passthrough B returned `OK`, no transform error; affix stripping preX→X with passthrough X likewise returned `OK`. Explicitly mapping both A and B to X correctly returned `NEEDS_TRANSFORM`.
- `UNKNOWN` fidelity allowed blocking-eligible `DRIFT`; exact `LOW` correctly suppressed it. Empty HIGH contracts returned `OK` at the direct API. Reachability of those constructed fidelity/empty states from the extractors is not established by this input.
- Declared identity with disjoint A/B returned `NEEDS_TRANSFORM`. An unknown affix option (`added`) was ignored and the disjoint result became blocking-eligible `DRIFT`.
- Java retained LONG, omitted OK and the same-line OTHER, while retaining HIGH. A constructor with label then code and an accessor returning code extracted the first string label as HIGH. A multiline comment caused the recorded member line to be 3 although the original input member was on line 5.
- Dart nonliteral constructor expressions produced A/B/Foo/bar/baz as HIGH values. Mixed literal/nonliteral members retained only A as HIGH. An unrelated Text("foreign") call outside the enum entered its value set.
- Proto string→int64 with unchanged tag/name returned the same extracted value and `OK`. A map and a field with options were omitted; a nested child field entered both child and parent contracts; equal short names across two packages retained only the first. These are parser observations; no compiler, serialized bytes or actual wire compatibility was tested.
- A valid DRIFT ledger record produced a potential break. Appending a malformed final JSON line made that seam disappear from the audit results. This is actual isolated file parsing, not a live ledger change.

No fleet repository, Samsung device, compiler, real model task, human approval, deployment, native Windows/WSL upstream execution or adoption was validated. Zeus regression tests and GitHub CI are separate evidence.
