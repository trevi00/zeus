# Selected validation receipts

Raw evidence stays on D; this is a sanitized summary.

```json
{
  "revision": "e52ed08617a0ad540caf17155112b2f02eb884db",
  "ci": {
    "id": 35109780079,
    "attempt": 1,
    "conclusion": "success",
    "jobs": [
      {
        "name": "changes",
        "conclusion": "success"
      },
      {
        "name": "integration",
        "conclusion": "success"
      },
      {
        "name": "test (windows-latest, 3.14)",
        "conclusion": "success"
      },
      {
        "name": "test (windows-latest, 3.12)",
        "conclusion": "success"
      },
      {
        "name": "test (ubuntu-latest, 3.12)",
        "conclusion": "success"
      },
      {
        "name": "test (ubuntu-latest, 3.14)",
        "conclusion": "success"
      },
      {
        "name": "docs",
        "conclusion": "skipped"
      },
      {
        "name": "CI gate",
        "conclusion": "success"
      }
    ]
  },
  "owner": {
    "counts": {
      "focused": {
        "tests": 143,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "passed": 143
      },
      "junit": {
        "tests": 2166,
        "failures": 0,
        "errors": 0,
        "skipped": 442,
        "passed": 1724
      }
    },
    "checks": [
      {
        "name": "ruff",
        "exit_code": 0,
        "log_sha256": "82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18"
      },
      {
        "name": "focused-pg",
        "exit_code": 0,
        "log_sha256": "f88bf646c0f4d728a56b91056861b83f24ad230a306042bc5acbbc26b8f959ff"
      },
      {
        "name": "pytest",
        "exit_code": 0,
        "log_sha256": "de4cf83ed55791f2cceb56af42c3910ee8ce25f807db9b562fd5349bf04d1ffb"
      }
    ]
  },
  "operation": {
    "id": "research-bound-dge-002",
    "status": "accepted",
    "task_id": "6cb0cde4-d6aa-5a61-8a29-9278f1895318",
    "decision_id": "67b5b295-1d25-4ec9-9931-f6570c835127",
    "inspection_id": "de82dd63ec33baed552670923500cfb9a6b3a1058358f643574c2c5edbf3d459",
    "calls": {
      "reserved": 2,
      "settled": 2
    },
    "collection": {
      "files": 1,
      "records": 114,
      "inserted": 114,
      "sink_failures": 0,
      "corrupt": 0,
      "refused": 0
    }
  },
  "hashes": {
    "receipt.json": "d3bc0f27a5c2d92a178ca44e970ec590de00581cf4244f25e23af7fa6129a5d2",
    "run.stdout": "5db6bbd02cda96d5a030b314c9b2fdf3f23bbf6832174409cb28573ac856b0f6",
    "records.json": "9cf77bc0aed5938827b964afbf897aa3e33a558a47dfe6026d10e6e460711f5c",
    "correction/receipt.json": "707203cbffdd92e842fd5c71d725466c4b26af31ef44ddeb15513d93ababad09",
    "correction/run.stdout": "2f3f0d21a21cfd75b60fb83997201790dac06dd9b849a05b865067e404d5e89a",
    "correction/records.json": "a742f1b75dc6f1e11b3874ad8a4d02d10fec02c9c5186769f9fdfcbae9dc22d9",
    "correction/owner-checks/result.json": "f7c26b57323f26bed085ecf41f54ea18b7dda44f4ed37c955c206f3644a45571",
    "correction/owner-checks/focused.xml": "ac1f221079381170f406c32c4b0df5398b377cc8312e3ef7212efd01528ce429",
    "correction/owner-checks/junit.xml": "367d4523ff859ff69dee0976c17054b9aede70dd888819357eea1879738eefdb",
    "ci-run.json": "fdf370da0e9eb24b4c3b380ca75b2c40423f7d41b5a87ae19c744ca1ac050e54",
    "ci-jobs.json": "c8a02a67986ab54a9664bf5c29ec170720c3de06be1e330628f698e2751e8155",
    "check-carry.py": "a5fa9ab2fabe064ac65ae5dad40ba0843344ef2f46b8f968ce397ecb6241c18e",
    "carry-proof.json": "1706a8aaca19c8008b09a832bf2049b03f01f8a3aecc135e8b62e8aee7316733"
  }
}
```
