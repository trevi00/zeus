# Release CLI-canary image, built from the candidate tree's ROOT `Dockerfile` by the release controller
# (`docker build -t zeus:candidate-<rev> <tree>`), then run for `cli_start` (`codex --version`) and
# `cli_file_task` (the root file canary with its chown handoff).
# INV-RELEASE-FILE-CANARY-001, INV-HOST-DELIVERY-VERIFY-001: this is the release CLI-canary image only. It is
# never an agent image (the legacy Compose agent image was retired by U6(b)) and never a worker image
# (INV-ISOLATED-WORKER-001 stays `Dockerfile.worker`). It holds the pinned Codex CLI and nothing else: no
# Zeus package, no Claude CLI, no node in the final stage and no credential.
# The codex stage below is byte-identical to `Dockerfile.worker`'s, so the build cache is shared.
FROM node:22-bookworm-slim AS codex
RUN npm install -g @openai/codex@0.156.1

FROM python:3.13-slim-bookworm
# The base already carries ca-certificates and coreutils (observed in python:3.13-slim-bookworm@sha256:2325bb28…:
# ca-certificates 20250419~deb12u1, coreutils 9.1-1), so the build needs no package download: an apt layer made the
# owner build depend on the Debian mirror and exceed the 600 s bound (cutover G2-R2). The build fails if the bundle
# is missing instead of fetching it.
RUN test -s /etc/ssl/certs/ca-certificates.crt
# The digest check hook: the build fails unless the copied binary is exactly the pinned 0.156.1 linux-x64
# musl build (INV-ROLE-CONTAINER-001, CODEX_CLI_SHA256) and answers its version.
ARG CODEX_CLI_VERSION=0.156.1
ARG CODEX_CLI_SHA256=0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f
COPY --from=codex /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex /opt/codex/bin/codex
RUN echo "${CODEX_CLI_SHA256}  /opt/codex/bin/codex" | sha256sum -c - \
    && ln -s /opt/codex/bin/codex /usr/local/bin/codex \
    && codex --version | grep -Fx "codex-cli ${CODEX_CLI_VERSION}"
# No USER instruction: the default user is root, which the file canary needs for its chown handoff.
ENTRYPOINT ["codex"]
