# S3b labelled fixture image (target/tests/test_s3_docker_fixture.py): NOT a worker image and NOT Codex.
# `/usr/local/bin/codex` is a provider-free fixture peer that speaks the App Server JSON-RPC subset the
# S3 transport uses and runs TRUSTED hooks the way the pinned CLI does (session cwd, JSON on stdin, the
# configured timeout); `/opt/zeus/bin/python` is the image interpreter path the S3b hook command names.
# Built with `docker build --network none` under the owned-fixture label; no credential, no model.
FROM python:3.12-slim
RUN mkdir -p /opt/zeus/bin && ln -s /usr/local/bin/python3 /opt/zeus/bin/python
COPY codex_peer.py /usr/local/bin/codex
RUN chmod 0555 /usr/local/bin/codex
