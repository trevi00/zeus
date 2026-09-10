# Current single-PC recovery review

The user rejected treating unmeasured host conditions as approval-only closure.
Scope is this Windows/WSL/Docker PC. Multiple hosts are excluded. Actual host
sleep/reboot and isolated real clock-step observations remain required; suspending
a worker or PostgreSQL container does not substitute for them.

Root and the actual Claude CLI reviewed independently and discussed the proposed
tests before implementation. Claude's relevant concerns are preserved in raw
review files. Root implements. Corrections to assumptions in the reviews:

- The child is a Python worker, not .NET/JVM. Only its main thread calls Workflow;
  no heartbeat thread is started. It reaches a closed-file barrier after the
  PostgreSQL transaction's fresh connection context has returned. PostgresStore
  has no pool. Windows thread ownership and suspend counts are checked; the test
  always resumes its own worker before bounded cleanup.
- The 2/12-second PG pauses intentionally keep the deadline alive to detect false
  clock events from IO stalls. A separate worker pause crosses a real deadline.
- QEMU is another possible genuine VM isolation mechanism; Hyper-V is not the
  only one. Neither a usable QEMU nor Hyper-V management command was found here.
  No Docker SYS_TIME or shared host-clock mutation is authorized by this test.
- WSL boot identity alone does not prove a Windows restart. A Windows boot marker
  must change. Shutdown/power-on and process restart are not labelled Restart.
- The current ledger is a separately created container with no Compose labels.
  Its empty HostPort binding and restart policy `no` differ from the project's
  fixed-port Compose default. Editing the unrelated Compose default would not fix
  this existing ledger. Pin its existing address and enable restart only after a
  verified backup, retaining the original container as a stopped rollback object.

Ledger migration must retain full original inspect metadata privately, including
PGDATA, image ID, commands, health check and stop signal. Snapshot and dump use
the control-plane advisory lock to exclude concurrent application writers. Restore
the custom-format database dump into a separate named volume and compare canonical
table data; retain a globals dump separately. Do not run two postmasters on the
original volume. Verify the original container is stopped before starting its
replacement. No original Claude/harness deployment is changed or removed.

Sources consulted for measurement mechanics:

- [Microsoft SuspendThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-suspendthread)
- [Microsoft GetProcessIdOfThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocessidofthread)
- [Microsoft ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)
- [Docker container pause](https://docs.docker.com/reference/cli/docker/container/pause/)
