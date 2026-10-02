"""Buzz relay client: a NIP-42 authenticated WebSocket connection to one Nostr relay (sync, one connection).

Layer: adapters
Context: observation
Owns: `BuzzRelayClient` (the `RelayClient` implementation: publish, query, the keyset pager `query_all`,
    subscribe, close; NIP-42 AUTH with one retry) and `reconnect_delay` (the close-code reconnect policy)
Does not own: the id/shape codec and the frame parsing (`observation.domain.nostr_event`), event verification
    and signing (injected `EventVerifier`/`EventSigner`), the outbox/inbox and the decision to reconnect or
    retry (callers: this client never loops on its own)
Entry points: BuzzRelayClient, reconnect_delay
Contracts: NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md;
    NIP-42 https://github.com/nostr-protocol/nips/blob/master/42.md;
    IANA WebSocket close codes https://www.iana.org/assignments/websocket/websocket.xhtml;
    websockets 17.1 sync client https://websockets.readthedocs.io/en/stable/reference/sync/client.html;
    RESEARCH-A A2/A5/A6, design §6.1 step 3 (duplicate), §6.2 step 4 (the one paging rule)

The connection is made with `proxy=None`, `compression=None` and a bounded `max_size` (RESEARCH A5): the
environment's proxy is never used, and a frame over `max_size` closes the connection (it is never truncated).
`legacy=True` is the documented way in websockets 17 to get the connection object directly (without it every
send warns that `connect()` must be used as a context manager).
The client is not thread-safe: one caller drives one connection.

One operation deadline (`op_deadline`, D5 F1): the TOTAL wall time of one request (a query, one `query_all` page or a
publish, including its AUTH retry), measured on the injected `clock`. It is checked in the receive loop, so frames
that keep arriving but answer nothing cannot extend it, and the receive timeout is clipped to what is left.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain import nostr_event as ne
from codex_harness.observation.ports import EventSigner, EventVerifier

MAX_RECONNECT_ATTEMPT = 8
_RESTARTS = frozenset({1001, 1006, 1012})
_BUSY = frozenset({1011, 1013})
_BUSY_FLOOR_SECONDS = 5.0
_MAX_BACKOFF_SECONDS = 60.0


def reconnect_delay(close_code: int | None, attempt: int) -> float | None:
    """Seconds to wait before reconnect number `attempt` (from 0), or None for no reconnect (RESEARCH A6).

    1000 (normal closure) never reconnects. 1001/1006/1012 (going away, abnormal, service restart) and every
    other code back off as `min(60, 2**attempt)` plus a deterministic jitter in [0, 1) derived from the attempt;
    1011/1013 (internal error, try again later) use a floor of 5 seconds. More than 8 attempts give None. A
    missing close code is an abnormal closure (1006).
    """
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise ContractError("relay: attempt is a non-negative integer")
    if close_code == 1000 or attempt > MAX_RECONNECT_ATTEMPT:
        return None
    base = min(_MAX_BACKOFF_SECONDS, float(2 ** attempt))
    if close_code in _BUSY:
        base = max(base, _BUSY_FLOOR_SECONDS)
    return base + ((attempt * 37) % 100) / 100


class _Lost(Exception):
    """The connection ended (closed by either side, or never opened); carries the reason."""


class _Timeout(Exception):
    pass


def _result(event_id: str | None, accepted: bool | None, prefix: str, message: str) -> dict:
    return {"id": event_id, "accepted": accepted, "prefix": prefix, "message": message}


class BuzzRelayClient:
    """`RelayClient` over websockets (sync).

    Close code of the last lost connection: `last_close_code` (feed it to `reconnect_delay`). `ended` and
    `accepted` values: see each method. NIP-42: the latest `["AUTH", challenge]` is kept per connection; on
    `OK false "auth-required: ..."` or `CLOSED "auth-required: ..."` the client sends an AUTH event
    (kind 22242, tags `relay` = the exact URL and `challenge`), waits for its OK and retries the request ONCE.
    `restricted:` and a second `auth-required` are final.
    """

    def __init__(self, url: str, *, auth_signer: EventSigner, auth_role: str, verifier: EventVerifier,
                 connect: Callable | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, max_size: int, open_timeout: float = 10,
                 recv_timeout: float = 30, page: int = 1000, op_deadline: float | None = None):
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ContractError("relay: page is a positive integer")
        if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size < 1:
            raise ContractError("relay: max_size is a positive integer")
        if op_deadline is not None and (isinstance(op_deadline, bool) or not isinstance(op_deadline, (int, float))
                                        or op_deadline <= 0):
            raise ContractError("relay: op_deadline is a positive number of seconds")
        if connect is None:
            from websockets.sync.client import connect as ws_connect
            connect = ws_connect
        self._url = url
        self._signer = auth_signer
        self._role = auth_role
        self._verifier = verifier
        self._connect = connect
        self._clock = clock
        self._sleep = sleep  # injected for callers' reconnect loops; this client never sleeps on its own
        self._max_size = max_size
        self._open_timeout = open_timeout
        self._recv_timeout = recv_timeout
        self._page = page
        self._op_deadline = op_deadline
        self._deadline: float | None = None  # the running operation's absolute end on `clock`; None between operations
        self._ws = None
        self._challenge: str | None = None
        self._subs: set[str] = set()
        self._queries = 0
        self.last_close_code: int | None = None

    # -- connection -------------------------------------------------------------------------------------

    @contextmanager
    def _operation(self):
        """One request's total time budget (`op_deadline`); a nested use keeps the outer deadline."""
        outer = self._deadline
        if outer is None and self._op_deadline is not None:
            self._deadline = self._clock() + self._op_deadline
        try:
            yield
        finally:
            self._deadline = outer

    def _left(self, limit: float) -> float:
        """`limit` clipped to the running operation's remaining time; `_Timeout` once it is spent."""
        if self._deadline is None:
            return limit
        left = self._deadline - self._clock()
        if left <= 0:
            raise _Timeout
        return min(limit, left)

    def _open(self):
        if self._ws is not None:
            return self._ws
        open_timeout = self._left(self._open_timeout)
        try:
            self._ws = self._connect(self._url, proxy=None, compression=None, max_size=self._max_size,
                                     open_timeout=open_timeout, legacy=True)
        except (OSError, TimeoutError, ConnectionError) as exc:
            self.last_close_code = 1006
            raise _Lost("connection_closed") from exc
        except Exception as exc:  # websockets handshake errors (InvalidURI, InvalidHandshake, ...)
            if type(exc).__module__.startswith("websockets"):
                self.last_close_code = 1006
                raise _Lost("connection_closed") from exc
            raise
        self._challenge = None
        return self._ws

    def _drop(self, code: int | None = None) -> None:
        ws, self._ws = self._ws, None
        self._challenge = None
        self._subs.clear()
        if ws is not None:
            if code is None:
                code = getattr(getattr(ws, "protocol", None), "close_code", None)
            self.last_close_code = code if isinstance(code, int) else 1006
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - already lost; closing is best effort
                pass

    def _send(self, text: str) -> None:
        ws = self._open()
        try:
            ws.send(text)
        except Exception as exc:
            if not type(exc).__module__.startswith("websockets") and not isinstance(exc, OSError):
                raise
            self._drop()
            raise _Lost("connection_closed") from exc

    def _next(self) -> ne.RelayFrame:
        """The next relay frame: AUTH challenges are kept, NOTICE is skipped, a malformed frame is `invalid`."""
        ws = self._open()
        while True:
            try:
                raw = ws.recv(timeout=self._left(self._recv_timeout))
            except TimeoutError as exc:
                raise _Timeout from exc
            except Exception as exc:
                if not type(exc).__module__.startswith("websockets") and not isinstance(exc, OSError):
                    raise
                # ConnectionClosed (OK or error, including a frame over max_size = 1009) or a socket error
                frame = getattr(exc, "rcvd", None) or getattr(exc, "sent", None)  # sent: our own 1009
                self._drop(getattr(frame, "code", None))
                raise _Lost("connection_closed") from exc
            if not isinstance(raw, str):
                return ne.RelayFrame("invalid")
            try:
                frame = ne.parse_relay_frame(raw)
            except ContractError:
                return ne.RelayFrame("invalid")
            if frame.kind == "AUTH":
                self._challenge = frame.challenge
                continue
            if frame.kind == "NOTICE":
                continue
            return frame

    def _best_effort(self, text: str) -> None:
        try:
            self._send(text)
        except (_Lost, _Timeout):
            pass

    # -- NIP-42 -----------------------------------------------------------------------------------------

    def _authenticate(self) -> bool:
        """Answer the stored challenge; True when the relay accepts the AUTH event."""
        if self._challenge is None:
            return False
        unsigned = ne.auth_event_template(self._url, self._challenge, int(self._clock()))
        signed = self._signer.sign(self._role, unsigned)
        self._send(ne.auth_frame(signed))
        while True:
            frame = self._next()
            if frame.kind == "OK" and frame.event_id == signed["id"]:
                return bool(frame.accepted)

    # -- publish ----------------------------------------------------------------------------------------

    def publish(self, event: dict) -> dict:
        """Send one signed event; `{"id", "accepted", "prefix", "message"}` from its OK.

        `duplicate:` is `accepted: True, prefix: "duplicate"` (design §6.1 step 3). A timeout or a closed
        connection is `accepted: None, prefix: "unknown"`: the outcome is unknown, never guessed.
        """
        frame_text = ne.event_frame(event)
        ident = event["id"]
        try:
            with self._operation():
                for attempt in (0, 1):
                    self._send(frame_text)
                    result = self._await_ok(ident)
                    if result["prefix"] == "auth-required" and attempt == 0 and self._authenticate():
                        continue
                    return result
        except _Lost as exc:
            return _result(ident, None, "unknown", str(exc))
        except _Timeout:
            return _result(ident, None, "unknown", "timeout")
        return result  # pragma: no cover - the loop always returns

    def _await_ok(self, ident: str) -> dict:
        while True:
            frame = self._next()
            if frame.kind == "OK" and frame.event_id == ident:
                prefix = ne.classify(frame.message)
                accepted = True if prefix == "duplicate" else bool(frame.accepted)
                return _result(ident, accepted, prefix, frame.message)

    # -- query ------------------------------------------------------------------------------------------

    def _sub_id(self) -> str:
        self._queries += 1
        return f"q{self._queries}"

    def query(self, filters: list[dict]) -> dict:
        """One REQ to EOSE: `{"events", "ended", "unverified", "received"}`.

        `events` are verified and deduplicated by id; those failing the verifier (or malformed) are dropped and
        counted in `unverified`; `received` counts every EVENT frame. `ended` is `eose`, `closed:<prefix>`,
        `timeout` or `connection_closed`. **`ended == "eose"` is NOT proof of completeness** (design §6.2
        step 4): the relay may cap or filter the history; the caller decides what a short page means.
        """
        sub_id = self._sub_id()
        events: dict[str, dict] = {}
        counts = {"unverified": 0, "received": 0}
        retried = False
        ended = "connection_closed"
        try:
            with self._operation():
                self._send(ne.req(sub_id, *filters))
                while True:
                    frame = self._next()
                    if frame.kind == "invalid":
                        counts["unverified"] += 1
                        counts["received"] += 1
                    elif frame.kind == "EVENT" and frame.sub_id == sub_id:
                        counts["received"] += 1
                        if self._verified(frame.event):
                            events.setdefault(frame.event["id"], frame.event)
                        else:
                            counts["unverified"] += 1
                    elif frame.kind == "EOSE" and frame.sub_id == sub_id:
                        ended = "eose"
                        break
                    elif frame.kind == "CLOSED" and frame.sub_id == sub_id:
                        prefix = ne.classify(frame.message)
                        if prefix == "auth-required" and not retried and self._authenticate():
                            retried = True
                            self._send(ne.req(sub_id, *filters))
                            continue
                        ended = f"closed:{prefix}"
                        return self._query_result(events, ended, counts)
                self._best_effort(ne.close(sub_id))
        except _Timeout:
            ended = "timeout"  # an observation, never proof (design §6.2 step 4); the operation deadline lands here too
            self._best_effort(ne.close(sub_id))
        except _Lost:
            ended = "connection_closed"
        return self._query_result(events, ended, counts)

    @staticmethod
    def _query_result(events: dict[str, dict], ended: str, counts: dict[str, int]) -> dict:
        return {"events": list(events.values()), "ended": ended, "unverified": counts["unverified"],
                "received": counts["received"]}

    def _verified(self, event: dict) -> bool:
        try:
            return bool(self._verifier.verify(event))
        except ContractError:
            return False

    def query_all(self, filter: dict, *, until: int | None = None,  # noqa: A002 - port signature
                  stop: Callable[[], bool] | None = None) -> dict:
        """Every event matching `filter`, paged by the relay's composite keyset (design §6.2 step 4).

        Pages of `page` events, in the relay's order (created_at desc, id asc); the next page asks
        `created_at < until OR (created_at == until AND id > before_id)` with `until`/`before_id` taken from
        the last event of the page. It stops when a page has fewer than `page` events or `ended` is not `eose`.
        The keyset must strictly advance and each page must add an event; otherwise `ended` is `stalled`.
        Returns `{"events", "ended", "pages", "unverified"}`; `ended == "eose"` here means every page ended
        by EOSE and the last was short, which is still the relay's word, not proof of completeness.

        `stop` (D5 F1) is read before each page: once true no further page is requested and `ended` is `stopped`,
        with the pages already read (the caller resumes from the keyset it committed). `None` never stops early.
        """
        events: dict[str, dict] = {}
        unverified = pages = 0
        cursor: tuple[int, str] | None = None
        ended = "eose"
        while True:
            if stop is not None and stop():
                ended = "stopped"
                break
            request = {**filter, "limit": self._page}
            if cursor is not None:
                request["until"], request["before_id"] = cursor
            elif until is not None:
                request["until"] = until
            result = self.query([request])
            pages += 1
            unverified += result["unverified"]
            fresh = [event for event in result["events"] if event["id"] not in events]
            for event in fresh:
                events[event["id"]] = event
            ended = result["ended"]
            if ended != "eose" or result["received"] < self._page:
                break
            if not fresh:
                ended = "stalled"
                break
            last = result["events"][-1]
            advanced = (last["created_at"], last["id"])
            if cursor is not None and not (advanced[0] < cursor[0]
                                           or (advanced[0] == cursor[0] and advanced[1] > cursor[1])):
                ended = "stalled"
                break
            cursor = advanced
        return {"events": list(events.values()), "ended": ended, "pages": pages, "unverified": unverified}

    # -- subscribe / close ------------------------------------------------------------------------------

    def subscribe(self, sub_id: str, filters: list[dict]) -> Iterator[dict]:
        """Yield verified live events; the generator's return value is the reason it ended
        (`closed:<prefix>` or `connection_closed`). A receive timeout only waits again; closing the
        generator sends CLOSE."""
        retried = False
        try:
            self._send(ne.req(sub_id, *filters))
            self._subs.add(sub_id)
            while True:
                try:
                    frame = self._next()
                except _Timeout:
                    continue
                if frame.kind == "EVENT" and frame.sub_id == sub_id:
                    if self._verified(frame.event):
                        yield frame.event
                elif frame.kind == "CLOSED" and frame.sub_id == sub_id:
                    prefix = ne.classify(frame.message)
                    if prefix == "auth-required" and not retried and self._authenticate():
                        retried = True
                        self._send(ne.req(sub_id, *filters))
                        continue
                    self._subs.discard(sub_id)
                    return f"closed:{prefix}"
        except _Lost:
            return "connection_closed"
        finally:
            if sub_id in self._subs:
                self._subs.discard(sub_id)
                if self._ws is not None:
                    self._best_effort(ne.close(sub_id))

    def close(self) -> None:
        """CLOSE every open subscription, then close the socket."""
        for sub_id in sorted(self._subs):
            self._best_effort(ne.close(sub_id))
        self._subs.clear()
        if self._ws is not None:
            self._drop(1000)
