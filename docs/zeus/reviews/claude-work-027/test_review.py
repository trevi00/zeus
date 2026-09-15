import os
import time
import traceback
from urllib.parse import urlparse

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices
from codex_harness.domain.model import ContractError


def test_answer_after_deadline_is_not_ready(tmp_path, monkeypatch):
    from psycopg.conninfo import conninfo_to_dict
    endpoint = conninfo_to_dict(os.environ['HARNESS_DATABASE_URL'])
    service = VerificationServices(tmp_path / 'services', FileArtifacts(tmp_path / 'artifacts'))
    service.password = endpoint['password']
    port = int(endpoint['port'])
    original = service._answer
    identity = original('postgres', port, 3)
    seen = []

    def delayed_answer(kind, port, seconds, register=None):
        answer = original(kind, port, seconds, register)
        seen.append(answer)
        time.sleep(0.3)
        return answer

    monkeypatch.setattr(service, '_answer', delayed_answer)
    monkeypatch.setattr(service, '_container_identity', lambda kind, seconds: identity)
    with pytest.raises(ContractError):
        service._await_service('postgres', port, deadline_seconds=0.05)
    assert seen


def test_refusal_traceback_does_not_include_raw_error(tmp_path, monkeypatch):
    port = urlparse(os.environ['HARNESS_REDIS_URL']).port
    service = VerificationServices(tmp_path / 'services', FileArtifacts(tmp_path / 'artifacts'))
    marker = 'REVIEW_RAW_CREDENTIAL_SENTINEL'

    def rejected(*args):
        raise RuntimeError(marker)

    monkeypatch.setattr(service, '_answer', rejected)
    with pytest.raises(ContractError) as caught:
        service._await_service('redis', port, deadline_seconds=0.02)
    rendered = ''.join(traceback.format_exception(caught.type, caught.value, caught.tb))
    # Do not print the marker or the traceback. Record only the violated safe assertion.
    assert marker not in rendered, 'raw provider error is retained in the public exception chain'
