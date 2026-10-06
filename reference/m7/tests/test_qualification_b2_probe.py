"""aibox-migration-001 qualification probe: the model endpoint name resolves from this environment."""
import socket

ENDPOINT = "api.anthropic.com"


def test_model_endpoint_name_resolves():
    assert socket.getaddrinfo(ENDPOINT, 443, proto=socket.IPPROTO_TCP)
