# Ported from SOURCE M7 tests/test_qualification_b2_probe.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""aibox-migration-001 qualification probe: the model endpoint name resolves from this environment."""
import socket

ENDPOINT = "api.anthropic.com"


def test_model_endpoint_name_resolves():
    assert socket.getaddrinfo(ENDPOINT, 443, proto=socket.IPPROTO_TCP)
