"""Buzz A2: the NIP-42 relay client against an in-process fake relay (a websockets server on 127.0.0.1:0).

No external network. Every server runs in a thread and is shut down by a finalizer; every receive has a timeout.
"""

import json
import threading
import time

import pytest
from websockets.sync import server as ws_server
from websockets.sync.client import connect as real_connect

from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.buzz_relay import BuzzRelayClient, reconnect_delay
from codex_harness.observation.adapters.event_signer import NostrEventSigner
from codex_harness.observation.adapters.nostr_verify import verify_event
from codex_harness.observation.ports import RelayClient

T = 1700000000


class _Accept:
    def verify(self, event):
        return True


class _Relay:
    """A scripted fake relay: `handler(ws, relay)` runs per connection; `frames` records client frames."""

    def __init__(self, handler):
        self.frames = []
        self.connections = 0
        self._handler = handler
        self._server = ws_server.serve(self._run, "127.0.0.1", 0, compression=None)
        self.url = f"ws://127.0.0.1:{self._server.socket.getsockname()[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _run(self, ws):
        self.connections += 1
        try:
            self._handler(ws, self)
        except Exception:  # noqa: BLE001 - a client that went away ends the script
            pass

    def recv(self, ws, timeout=5):
        frame = json.loads(ws.recv(timeout=timeout))
        self.frames.append(frame)
        return frame

    def wait_frames(self, count, timeout=3.0):
        deadline = time.monotonic() + timeout
        while len(self.frames) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(self.frames) >= count

    def stop(self):
        self._server.shutdown()
        self._thread.join(timeout=10)


@pytest.fixture
def relay(request):
    made = []

    def make(handler):
        item = _Relay(handler)
        made.append(item)
        return item

    yield make
    for item in made:
        item.stop()


@pytest.fixture
def keys(tmp_path):
    store = TestRoleKeys(tmp_path / "keys")
    for role in ("bridge", "other"):
        store.create(role)
    return store


@pytest.fixture
def signer(keys):
    return NostrEventSigner(keys.pubkey, keys.sign_id)


def _client(url, signer, *, verifier=None, **kwargs):
    class _Verify:
        def verify(self, event):
            return verify_event(event)

    options = {"max_size": 1 << 20, "recv_timeout": 5, "open_timeout": 5}
    options.update(kwargs)
    return BuzzRelayClient(url, auth_signer=signer, auth_role="bridge", verifier=verifier or _Verify(), **options)


def _event(signer, content="hi", role="other", created_at=T, kind=1):
    return signer.sign(role, {"kind": kind, "created_at": created_at, "tags": [], "content": content})


def _fake(i, created_at=T):
    return {"id": f"{i:064x}", "pubkey": "11" * 32, "created_at": created_at, "kind": 1, "tags": [],
            "content": "", "sig": "22" * 64}


def test_client_satisfies_the_port_and_validates_arguments(signer):
    client = _client("ws://127.0.0.1:1", signer)
    assert [n for n in vars(RelayClient) if not n.startswith("_")] and hasattr(client, "query_all")
    for bad in (0, True, "x"):
        with pytest.raises(ContractError):
            _client("ws://x", signer, page=bad)
        with pytest.raises(ContractError):
            _client("ws://x", signer, max_size=bad)


# 1. AUTH ------------------------------------------------------------------------------------------------

def _auth_handler(ws, relay, *, final_auth_required=False):
    ws.send(json.dumps(["AUTH", "c1"]))
    authed = False
    while True:
        frame = relay.recv(ws)
        if frame[0] == "AUTH":
            authed = True
            ws.send(json.dumps(["OK", frame[1]["id"], True, ""]))
        elif frame[0] == "EVENT":
            if authed and not final_auth_required:
                ws.send(json.dumps(["OK", frame[1]["id"], True, ""]))
            else:
                ws.send(json.dumps(["AUTH", "c2"]))  # a newer challenge replaces c1
                ws.send(json.dumps(["OK", frame[1]["id"], False, "auth-required: members only"]))


def test_auth_required_authenticates_with_the_latest_challenge_and_retries_once(relay, signer, keys):
    fake = relay(_auth_handler)
    client = _client(fake.url, signer)
    event = _event(signer)
    result = client.publish(event)
    assert result == {"id": event["id"], "accepted": True, "prefix": "none", "message": ""}
    assert [frame[0] for frame in fake.frames] == ["EVENT", "AUTH", "EVENT"]
    auth = fake.frames[1][1]
    assert auth["kind"] == 22242 and auth["pubkey"] == keys.pubkey("bridge") and verify_event(auth) is True
    assert auth["tags"] == [["relay", fake.url], ["challenge", "c2"]] and auth["content"] == ""
    assert fake.frames[2][1] == event
    client.close()


def test_the_first_challenge_is_kept_when_no_newer_one_arrives(relay, signer):
    def handler(ws, fake):
        ws.send(json.dumps(["AUTH", "only"]))
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], False, "auth-required: x"]))
        auth = fake.recv(ws)
        ws.send(json.dumps(["OK", auth[1]["id"], True, ""]))
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], True, ""]))

    fake = relay(handler)
    client = _client(fake.url, signer)
    assert client.publish(_event(signer))["accepted"] is True
    assert fake.frames[1][1]["tags"][1] == ["challenge", "only"]
    client.close()


def test_a_second_auth_required_after_the_retry_is_final(relay, signer):
    fake = relay(lambda ws, r: _auth_handler(ws, r, final_auth_required=True))
    client = _client(fake.url, signer)
    result = client.publish(_event(signer))
    assert result["accepted"] is False and result["prefix"] == "auth-required"
    assert [frame[0] for frame in fake.frames] == ["EVENT", "AUTH", "EVENT"]
    client.close()


def test_auth_required_without_a_challenge_or_with_a_refused_auth_is_final(relay, signer):
    def no_challenge(ws, fake):
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], False, "auth-required: x"]))
        fake.recv(ws, timeout=1)

    fake = relay(no_challenge)
    client = _client(fake.url, signer)
    assert client.publish(_event(signer))["prefix"] == "auth-required"
    assert [frame[0] for frame in fake.frames] == ["EVENT"]
    client.close()

    def refuses(ws, fake):
        ws.send(json.dumps(["AUTH", "c"]))
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], False, "auth-required: x"]))
        auth = fake.recv(ws)
        ws.send(json.dumps(["OK", auth[1]["id"], False, "restricted: no"]))
        fake.recv(ws, timeout=1)

    fake = relay(refuses)
    client = _client(fake.url, signer)
    assert client.publish(_event(signer))["prefix"] == "auth-required"
    assert [frame[0] for frame in fake.frames] == ["EVENT", "AUTH"]
    client.close()


# 2/3. restricted and duplicate --------------------------------------------------------------------------

def test_restricted_is_final_with_exactly_one_send(relay, signer):
    def handler(ws, fake):
        ws.send(json.dumps(["AUTH", "c"]))
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], False, "restricted: not a member"]))
        fake.recv(ws, timeout=1)

    fake = relay(handler)
    client = _client(fake.url, signer)
    event = _event(signer)
    result = client.publish(event)
    assert result == {"id": event["id"], "accepted": False, "prefix": "restricted",
                      "message": "restricted: not a member"}
    assert [frame[0] for frame in fake.frames] == ["EVENT"]
    client.close()


@pytest.mark.parametrize("accepted", [True, False])
def test_duplicate_is_accepted_with_prefix_duplicate(relay, signer, accepted):
    def handler(ws, fake):
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", "ff" * 32, True, ""]))  # an unrelated OK is ignored
        ws.send(json.dumps(["OK", frame[1]["id"], accepted, "duplicate: already have this event"]))

    fake = relay(handler)
    client = _client(fake.url, signer)
    result = client.publish(_event(signer))
    assert result["accepted"] is True and result["prefix"] == "duplicate"
    client.close()


# 4. query -----------------------------------------------------------------------------------------------

def test_query_eose_dedups_and_drops_unverified(relay, signer):
    good, other = _event(signer, "a"), _event(signer, "b")
    forged = {**_event(signer, "c"), "content": "tampered"}

    def handler(ws, fake):
        req = fake.recv(ws)
        sub = req[1]
        for event in (good, good, forged, other):
            ws.send(json.dumps(["EVENT", sub, event]))
        ws.send(json.dumps(["EVENT", sub, {"id": "x"}]))  # malformed: counted unverified
        ws.send(json.dumps(["EVENT", "other-sub", _event(signer, "z")]))  # not ours
        ws.send(json.dumps(["NOTICE", "hello"]))
        ws.send(json.dumps(["EOSE", sub]))
        fake.recv(ws, timeout=2)  # the CLOSE

    fake = relay(handler)
    client = _client(fake.url, signer)
    result = client.query([{"kinds": [1]}])
    assert result["events"] == [good, other] and result["ended"] == "eose" and result["unverified"] == 2
    assert fake.frames[0][0] == "REQ" and fake.frames[0][2] == {"kinds": [1]}
    fake.wait_frames(2)
    assert fake.frames[1] == ["CLOSE", fake.frames[0][1]]
    client.close()


def test_query_closed_with_a_prefix_and_auth_retry(relay, signer):
    def handler(ws, fake):
        req = fake.recv(ws)
        ws.send(json.dumps(["CLOSED", req[1], "restricted: no"]))
        req = fake.recv(ws)
        ws.send(json.dumps(["CLOSED", req[1], "blocked: no"]))

    fake = relay(handler)
    client = _client(fake.url, signer)
    assert client.query([{}])["ended"] == "closed:restricted"
    assert client.query([{}])["ended"] == "closed:blocked"
    client.close()

    def auth_handler(ws, fake):
        ws.send(json.dumps(["AUTH", "ch"]))
        req = fake.recv(ws)
        ws.send(json.dumps(["CLOSED", req[1], "auth-required: sign in"]))
        auth = fake.recv(ws)
        ws.send(json.dumps(["OK", auth[1]["id"], True, ""]))
        req = fake.recv(ws)
        ws.send(json.dumps(["EVENT", req[1], event]))
        ws.send(json.dumps(["EOSE", req[1]]))
        fake.recv(ws, timeout=2)

    event = _event(signer)
    fake = relay(auth_handler)
    client = _client(fake.url, signer)
    result = client.query([{}])
    assert result["events"] == [event] and result["ended"] == "eose"
    assert [frame[0] for frame in fake.frames[:3]] == ["REQ", "AUTH", "REQ"]
    client.close()

    def always(ws, fake):
        ws.send(json.dumps(["AUTH", "ch"]))
        while True:
            frame = fake.recv(ws)
            if frame[0] == "REQ":
                ws.send(json.dumps(["CLOSED", frame[1], "auth-required: sign in"]))
            elif frame[0] == "AUTH":
                ws.send(json.dumps(["OK", frame[1]["id"], True, ""]))

    fake = relay(always)
    client = _client(fake.url, signer)
    assert client.query([{}])["ended"] == "closed:auth-required"
    assert [frame[0] for frame in fake.frames] == ["REQ", "AUTH", "REQ"]
    client.close()


def test_query_timeout_and_connection_closed(relay, signer):
    fake = relay(lambda ws, r: (r.recv(ws), r.recv(ws, timeout=3)))
    client = _client(fake.url, signer, recv_timeout=0.3)
    event = _fake(1)
    assert client.query([{}]) == {"events": [], "ended": "timeout", "unverified": 0, "received": 0}
    fake.wait_frames(2)
    assert fake.frames[-1][0] == "CLOSE"
    client.close()

    def drops(ws, fake):
        req = fake.recv(ws)
        ws.send(json.dumps(["EVENT", req[1], event]))
        ws.close()

    fake = relay(drops)
    client = _client(fake.url, signer, verifier=_Accept())
    result = client.query([{}])
    assert result["ended"] == "connection_closed" and result["events"] == [event]
    assert client.last_close_code == 1000  # the relay closed normally


def test_an_unreachable_relay_is_connection_closed_and_unknown(signer):
    client = _client("ws://127.0.0.1:9", signer)
    assert client.query([{}])["ended"] == "connection_closed" and client.last_close_code == 1006
    assert client.publish(_event(signer))["accepted"] is None


# 5. query_all -------------------------------------------------------------------------------------------

def _keyset_handler(events, requests, *, ignore_keyset=False):
    ordered = sorted(events, key=lambda e: (-e["created_at"], e["id"]))

    def handler(ws, fake):
        while True:
            req = fake.recv(ws)
            if req[0] != "REQ":
                continue
            flt = req[2]
            requests.append(flt)
            rows = ordered
            if "until" in flt and not ignore_keyset:
                rows = [e for e in ordered if e["created_at"] < flt["until"]
                        or (e["created_at"] == flt["until"] and e["id"] > flt.get("before_id", ""))]
            for event in rows[:flt["limit"]]:
                ws.send(json.dumps(["EVENT", req[1], event]))
            ws.send(json.dumps(["EOSE", req[1]]))

    return handler


def test_query_all_pages_through_1001_events_with_the_same_created_at(relay, signer):
    events = [_fake(i) for i in range(1001)]
    requests = []
    fake = relay(_keyset_handler(events, requests))
    client = _client(fake.url, signer, verifier=_Accept())
    result = client.query_all({"kinds": [1]})
    assert result["ended"] == "eose" and result["pages"] == 2 and result["unverified"] == 0
    assert sorted(e["id"] for e in result["events"]) == [e["id"] for e in events]
    assert len(result["events"]) == 1001
    assert requests == [{"kinds": [1], "limit": 1000},
                        {"kinds": [1], "limit": 1000, "until": T, "before_id": f"{999:064x}"}]
    client.close()


def test_query_all_with_until_and_a_short_page_stops_after_one_page(relay, signer):
    requests = []
    fake = relay(_keyset_handler([_fake(1), _fake(2, T - 5)], requests))
    client = _client(fake.url, signer, verifier=_Accept(), page=3)
    result = client.query_all({"kinds": [1]}, until=T)
    assert result["pages"] == 1 and len(result["events"]) == 2 and requests[0]["until"] == T
    client.close()


def test_query_all_mixed_created_at_pages_in_relay_order(relay, signer):
    events = [_fake(i, T - i // 3) for i in range(10)]
    requests = []
    fake = relay(_keyset_handler(events, requests))
    client = _client(fake.url, signer, verifier=_Accept(), page=3)
    result = client.query_all({})
    assert result["ended"] == "eose" and result["pages"] == 4
    assert sorted(e["id"] for e in result["events"]) == sorted(e["id"] for e in events)
    client.close()


def test_query_all_stalls_when_the_keyset_does_not_advance(relay, signer):
    events = [_fake(i) for i in range(3)]
    fake = relay(_keyset_handler(events, [], ignore_keyset=True))  # the same full page every time
    client = _client(fake.url, signer, verifier=_Accept(), page=3)
    result = client.query_all({})
    assert result["ended"] == "stalled" and result["pages"] == 2 and len(result["events"]) == 3
    client.close()

    pages = [[_fake(5), _fake(6), _fake(7)], [_fake(1), _fake(2), _fake(3)]]  # page 2 goes backwards in id

    def backwards(ws, fake):
        for page in pages:
            req = fake.recv(ws)
            while req[0] != "REQ":  # the CLOSE of the previous page
                req = fake.recv(ws)
            for event in page:
                ws.send(json.dumps(["EVENT", req[1], event]))
            ws.send(json.dumps(["EOSE", req[1]]))

    fake = relay(backwards)
    client = _client(fake.url, signer, verifier=_Accept(), page=3)
    result = client.query_all({})
    assert result["ended"] == "stalled" and result["pages"] == 2
    client.close()


def test_query_all_stops_on_a_non_eose_end(relay, signer):
    def handler(ws, fake):
        req = fake.recv(ws)
        for i in range(3):
            ws.send(json.dumps(["EVENT", req[1], _fake(i)]))
        ws.send(json.dumps(["CLOSED", req[1], "rate-limited: slow down"]))

    fake = relay(handler)
    client = _client(fake.url, signer, verifier=_Accept(), page=3)
    result = client.query_all({})
    assert result["ended"] == "closed:rate-limited" and result["pages"] == 1 and len(result["events"]) == 3
    client.close()


def test_query_all_a_full_page_of_unverified_events_stalls(relay, signer):
    class _Reject:
        def verify(self, event):
            return False

    fake = relay(_keyset_handler([_fake(i) for i in range(3)], []))
    client = _client(fake.url, signer, verifier=_Reject(), page=3)
    result = client.query_all({})
    assert result["ended"] == "stalled" and result["events"] == [] and result["unverified"] == 3
    client.close()


# subscribe ----------------------------------------------------------------------------------------------

def test_subscribe_yields_verified_events_and_returns_the_closed_reason(relay, signer):
    good = _event(signer)
    forged = {**_event(signer, "x"), "content": "tampered"}

    def handler(ws, fake):
        req = fake.recv(ws)
        ws.send(json.dumps(["EOSE", req[1]]))
        ws.send(json.dumps(["EVENT", req[1], forged]))
        ws.send(json.dumps(["EVENT", req[1], good]))
        ws.send(json.dumps(["CLOSED", req[1], "restricted: left the group"]))

    fake = relay(handler)
    client = _client(fake.url, signer)
    stream = client.subscribe("live", [{"kinds": [1]}])
    assert next(stream) == good
    with pytest.raises(StopIteration) as stop:
        next(stream)
    assert stop.value.value == "closed:restricted"
    client.close()


def test_subscribe_connection_closed_and_close_sends_close_frames(relay, signer):
    fake = relay(lambda ws, r: (r.recv(ws), ws.close()))
    client = _client(fake.url, signer)
    stream = client.subscribe("live", [{}])
    with pytest.raises(StopIteration) as stop:
        next(stream)
    assert stop.value.value == "connection_closed"

    good = _event(signer)

    def handler(ws, fake):
        req = fake.recv(ws)
        ws.send(json.dumps(["EVENT", req[1], good]))
        fake.recv(ws, timeout=3)  # CLOSE from close()

    fake = relay(handler)
    client = _client(fake.url, signer)
    stream = client.subscribe("live", [{}])
    assert next(stream) == good
    client.close()
    fake.wait_frames(2)
    assert fake.frames[-1] == ["CLOSE", "live"]
    stream.close()


def test_subscribe_survives_a_receive_timeout_and_auth_retry(relay, signer):
    good = _event(signer)

    def handler(ws, fake):
        ws.send(json.dumps(["AUTH", "ch"]))
        req = fake.recv(ws)
        ws.send(json.dumps(["CLOSED", req[1], "auth-required: sign in"]))
        auth = fake.recv(ws)
        ws.send(json.dumps(["OK", auth[1]["id"], True, ""]))
        req = fake.recv(ws)
        threading.Event().wait(0.5)  # longer than the client's recv timeout
        ws.send(json.dumps(["EVENT", req[1], good]))
        fake.recv(ws, timeout=3)

    fake = relay(handler)
    client = _client(fake.url, signer, recv_timeout=0.2)
    stream = client.subscribe("live", [{}])
    assert next(stream) == good
    stream.close()
    client.close()


# 6. oversize frame --------------------------------------------------------------------------------------

def test_an_oversize_frame_closes_the_connection_and_is_never_truncated(relay, signer):
    big = _fake(1)
    big["content"] = "x" * 20000

    def handler(ws, fake):
        req = fake.recv(ws)
        ws.send(json.dumps(["EVENT", req[1], _fake(0)]))
        ws.send(json.dumps(["EVENT", req[1], big]))
        ws.send(json.dumps(["EOSE", req[1]]))
        fake.recv(ws, timeout=2)

    fake = relay(handler)
    client = _client(fake.url, signer, verifier=_Accept(), max_size=4096)
    result = client.query([{}])
    assert result["ended"] == "connection_closed" and [e["id"] for e in result["events"]] == [_fake(0)["id"]]
    assert client.last_close_code == 1009  # message too big
    assert reconnect_delay(client.last_close_code, 0) > 0

    def big_ok(ws, fake):
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], True, "y" * 20000]))

    fake = relay(big_ok)
    client = _client(fake.url, signer, max_size=4096)
    assert client.publish(_event(signer))["accepted"] is None


# 7. reconnect_delay -------------------------------------------------------------------------------------

def test_reconnect_delay_matrix():
    assert reconnect_delay(1000, 0) is None and reconnect_delay(1000, 5) is None
    for code in (1001, 1006, 1012, None, 1002, 4000):
        delays = [reconnect_delay(code, n) for n in range(9)]
        assert all(d is not None and d > 0 for d in delays)
        assert delays[0] < 2 and delays[1] < 3 and delays[3] < 9
        assert all(min(60, 2 ** n) <= d < min(60, 2 ** n) + 1 for n, d in enumerate(delays))
        assert delays[7] < 61 and delays[8] < 61
        assert reconnect_delay(code, 9) is None and reconnect_delay(code, 100) is None
    for code in (1011, 1013):
        assert 5 <= reconnect_delay(code, 0) < 6 and 5 <= reconnect_delay(code, 2) < 6
        assert reconnect_delay(code, 4) >= 16 and reconnect_delay(code, 9) is None
        assert reconnect_delay(code, 0) > reconnect_delay(1012, 0)
    assert reconnect_delay(1012, 3) == reconnect_delay(1012, 3)  # deterministic jitter
    assert 60 <= reconnect_delay(1012, 8) < 61
    for bad in (-1, True, "1", None, 1.5):
        with pytest.raises(ContractError):
            reconnect_delay(1012, bad)


# 8. proxy bypass ----------------------------------------------------------------------------------------

@pytest.fixture
def proxy_env(monkeypatch):
    for name in ("https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)


def test_the_environment_proxy_is_never_used(relay, signer, proxy_env):
    def handler(ws, fake):
        frame = fake.recv(ws)
        ws.send(json.dumps(["OK", frame[1]["id"], True, ""]))

    calls = []

    def spy(url, **kwargs):
        calls.append((url, kwargs))
        return real_connect(url, **kwargs)

    fake = relay(handler)
    client = _client(fake.url, signer, connect=spy, max_size=65536)
    assert client.publish(_event(signer))["accepted"] is True
    assert calls and calls[0][0] == fake.url
    assert calls[0][1]["proxy"] is None and calls[0][1]["compression"] is None
    assert calls[0][1]["max_size"] == 65536 and calls[0][1]["legacy"] is True
    client.close()

    fake = relay(handler)
    default = _client(fake.url, signer)  # the real websockets connect, with the proxy variables set
    assert default.publish(_event(signer))["accepted"] is True
    default.close()


# 9. publish on a dropped connection / timeout -------------------------------------------------------------

def test_publish_on_a_dropped_connection_or_timeout_is_unknown(relay, signer):
    fake = relay(lambda ws, r: (r.recv(ws), ws.close(1011)))
    client = _client(fake.url, signer)
    event = _event(signer)
    result = client.publish(event)
    assert result["accepted"] is None and result["prefix"] == "unknown" and result["id"] == event["id"]
    assert client.last_close_code == 1011

    fake = relay(lambda ws, r: (r.recv(ws), r.recv(ws, timeout=3)))
    client = _client(fake.url, signer, recv_timeout=0.3)
    result = client.publish(event)
    assert result["accepted"] is None and result["prefix"] == "unknown" and result["message"] == "timeout"
    client.close()


def test_publish_refuses_an_unsigned_event_before_any_connection(signer):
    client = _client("ws://127.0.0.1:9", signer)
    with pytest.raises(ContractError):
        client.publish({"kind": 1})
