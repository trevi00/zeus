# tokobs observability runbook (DESIGN §7)

This runbook installs, checks, updates and removes the isolated compose project `zeus-tokobs` (collector, Prometheus,
Grafana). Run every command from the root of the accepted release checkout, as the operator user (uid 1000).

## Scope and authority

Nothing here runs without the user's decisions **U1** (run the three containers in project `zeus-tokobs`; the
collector reads worker stream files read-only) and **U3** (create the one new secret, the Grafana admin password),
both in DESIGN §10 and not restated here. Until U1 and U3 are granted, this file is documentation only. The A56
isolated connectivity test below uses its own project `zeus-tokobs-conntest`, test ports and a temporary secret; it
needs neither decision and touches no `/srv` path.

## Install

Create the ledger directory, owned by uid/gid 1000 and private:

```bash
install -d -o 1000 -g 1000 -m 0700 /srv/zeus/runtime/tokobs
```

U3: the operator creates the secret file `/srv/zeus/secrets/grafana-admin.pass` (mode 0600, owner 1000). The password
is typed at a hidden prompt and is never printed, echoed, put on a command line or kept in shell history:

```bash
install -m 0600 -o 1000 -g 1000 /dev/null /srv/zeus/secrets/grafana-admin.pass
IFS= read -rs -p 'Grafana admin password: ' pw && printf '%s' "$pw" > /srv/zeus/secrets/grafana-admin.pass; unset pw
```

Start the project:

```bash
docker compose -p zeus-tokobs -f deploy/observability/compose.yaml up -d
```

## Post-checks

All four must pass; any failure means roll back (see below).

1. On the host only `127.0.0.1:3300` is listening and there is **no** listener on 9469 or 9090 at any address (no
   `0.0.0.0` or `[::]` for any tokobs port). The command must list exactly one line, for `127.0.0.1:3300`:

   ```bash
   ss -ltn | grep -E ':(3300|9469|9090)[[:space:]]'
   ```

2. Prometheus sees the exporter; the query returns the value 1:

   ```bash
   docker compose -p zeus-tokobs -f deploy/observability/compose.yaml exec prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=up{job="tokobs"}'
   ```

3. Grafana is healthy, and the provisioned datasource `tokobs-prom` is healthy:

   ```bash
   curl -s 127.0.0.1:3300/api/health
   ```

   For the datasource, open the SSH tunnel below, sign in as `admin`, and use **Connections > Data sources >
   tokobs-prom > Save & test**. The password is never given to `curl` on a command line.

4. Hardening: `docker inspect` of every service shows no privileged mode, no host network/PID/IPC, `CapDrop` ALL,
   `ReadonlyRootfs` true, user 1000:1000, no Docker socket mount and no published port other than loopback. The
   linter exits 0 when all hold:

   ```bash
   docker inspect $(docker compose -p zeus-tokobs -f deploy/observability/compose.yaml ps -q) | PYTHONPATH=tools/token_observability:src python3 -B -m tokobs lint-deploy --inspect-json -
   ```

## Access

Grafana is published only on host loopback. From a workstation, tunnel to it (as for the S9 monitor web) and browse
to `http://127.0.0.1:3300`:

```bash
ssh -N -L 3300:127.0.0.1:3300 <operator>@<host>
```

Prometheus and the collector are not published; ad-hoc queries go through Grafana's Explore or the `exec` form of
post-check 2.

## Update (controlled restart, no patch avoidance)

Images are pinned by digest in `deploy/observability/compose.yaml`. An update is a deliberate restart:

1. Resolve the new digest for the wanted tag (`docker pull <image>:<tag>` prints `Digest: sha256:...`, as does
   `docker buildx imagetools inspect <image>:<tag>`).
2. Edit the pinned `image:` line of that one service (`image: <name>:<tag>@sha256:<new digest>`). Keep the previous
   line so a rollback is one edit.
3. Run the A56 isolated connectivity test against the edited file. It starts project `zeus-tokobs-conntest` on test
   ports with a temporary secret, and removes everything it created:

   ```bash
   TOKOBS_CONNTEST=1 uv run pytest -q -p no:cacheprovider tests/token_observability/test_tokobs_conntest.py
   ```

4. Only if it passes, recreate the changed services (Compose recreates only services whose definition changed):

   ```bash
   docker compose -p zeus-tokobs -f deploy/observability/compose.yaml up -d
   ```

5. Repeat the post-checks.

Rollback of an update: put the previous digest back in `compose.yaml` and run the `up -d` command of step 4 again.

## Rollback / isolated cleanup

This removes the whole deployment and nothing else (A30). `down -v` removes the three containers, the project's two
networks and its two named volumes; then the ledger directory and the U3 secret file are removed:

```bash
docker compose -p zeus-tokobs -f deploy/observability/compose.yaml down -v
rm -rf -- /srv/zeus/runtime/tokobs
rm -- /srv/zeus/secrets/grafana-admin.pass
```

## What is not touched

Install, update and cleanup never change or remove: any worker source file (the collector mounts them read-only),
any S9 file (`/srv/zeus/runtime/control` is a read-only bind), any harness volume, container or network outside the
`zeus-tokobs*` projects, any host systemd unit, and any firewall rule. No command here uses a global prune.
