"""Shared S8 scenario steps (`research.sources`): `ResearchSources` of M7 `adapters/research.py` (`collect`, `parse_github`,
`parse_feed`, `github_detail`) and the discovery-pressure hold before its fetch (`adapters/discovery_pressure.py`,
`application/discovery_pressure.py`, `domain/discovery_pressure.py`), characterized BEFORE step 3 moves them (DESIGN-s8 §1 V5
the sources bullet and V2e; RESEARCH-S8 R2: urllib proxies and redirects, the stub sits at the `fetch` seam; TRACE-s8 §4).

- **parse**: `parse_github` and `parse_feed` over each RECORDED body (a trending-like page, an RSS feed, an Atom feed, a
  mixed feed, a malformed page and feed, a body of exactly 2,000,001 bytes), and the cap as `collect` returns it.
- **collect**: each source kind, a fetch that raises (HTTP error, timeout, OSError), an unparseable or empty body, the
  `collect_live` swallow of those exceptions (type only), `github_detail` success and each failure.
- **transport**: the real `fetch` (request headers, the 30 second timeout, the 2,000,001-byte read, the size refusal, the
  lossy decode) over a LABELLED transport double that replaces the module's `urlopen` name; the real `urlopen` is never called.
- **pressure_hold** (F-2 row 6; INV-DISCOVERY-PRESSURE-001): a proactive collect while the policy holds makes ZERO fetch calls
  (the stub counts them), every exempt intent never consults pressure, `validate_intent`, `validate_policy`, `decide`
  hysteresis, `unrecorded_hold`, `sample_fresh`, the census over labelled rows and the evaluator over a MemoryStore.
- **proxy_independence** (R2): the same cases with `http_proxy`/`https_proxy` set in the driver environment (restored after)
  give equal results, because the stub never reaches `urlopen`.

Layer: harness (never shipped). This module never imports `codex_harness`: the product arrives through `api`. No network,
no provider: every body is a RECORDED fixture below, the `fetch` of every `ResearchSources` here is the labelled `Stub`
(set on the instance), and the transport cases replace `urlopen` with `Transport`. An unreachable case is
`{"unreachable": "<why>"}`.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import os
import socket
import urllib.error
from datetime import datetime, timedelta
from types import SimpleNamespace

# ---- recorded bodies (LABELLED fixtures; no network, never fetched) ---------------------------------------------------------
GITHUB_HTML = """<html><body><main>
<article class="Box-row"><h2 class="h3 lh-condensed"><a href="/acme/pgtool" data-view="x">acme / pgtool</a></h2>
<p class="col-9 color-fg-muted my-1 pr-4">Postgres &amp; <b>advisory</b> locks   </p></article>
<article class="Box-row"><h2><a href="/acme/no-description?tab=readme">acme / no-description</a></h2></article>
<article class="Box-row"><h2><a href="/login?return_to=x">sign in</a></h2><p>query-only link: no match</p></article>
<article class="Box-row"><p>no heading at all</p></article>
<article class="Box-row"><h2><a href="/acme/with#anchor">fragment</a></h2><p>fragment link: no match</p></article>
<article class="Box-row"><h2><a href="/org/repo.name-1">org / repo.name-1</a></h2><p></p></article>
</main></body></html>"""

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>geek</title>
<item><title>Advisory lock patterns</title><link>https://news.hada.io/topic?id=1</link>
<description>&lt;p&gt;Locks &lt;b&gt;everywhere&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Plain http link</title><link>http://news.hada.io/topic?id=2</link><description>dropped: not https</description></item>
<item><title>No link</title><description>dropped: empty url</description></item>
<item><title>No description</title><link>https://news.hada.io/topic?id=3</link></item>
<item><title>Long</title><link>https://news.hada.io/topic?id=4</link><description>""" + "x" * 1600 + """</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>atom</title>
<entry><title>Atom one</title><link href="https://example.org/a1"/><content>&lt;p&gt;body &lt;i&gt;one&lt;/i&gt;&lt;/p&gt;</content></entry>
<entry><title>Atom http</title><link href="http://example.org/a2"/><content>dropped</content></entry>
<entry><title>Atom no link</title><content>dropped: no link element</content></entry>
<entry><title>Atom no href</title><link rel="self"/><content>dropped: empty href</content></entry>
<entry><title>Atom no content</title><link href="https://example.org/a3"/></entry>
</feed>"""

MIXED = """<root><item><title>rss-in-atom-doc</title><link>https://example.org/r</link><description>d</description></item>
<entry xmlns="http://www.w3.org/2005/Atom"><title>e</title><link href="https://example.org/e"/></entry></root>"""

MALFORMED_PAGE = "<html><body><article><h2><a href=\"/acme/broken\">broken</h2><p>never closed"
MALFORMED_FEED = "<rss><channel><item><title>unclosed</title><link>https://news.hada.io/x</link></channel>"
NO_ENTRIES = "<rss version=\"2.0\"><channel><title>empty</title></channel></rss>"
NOT_XML = "this is not a feed"
SMALL_RSS = ("<rss><channel><item><link>https://news.hada.io/topic?id=1</link><title>t</title></item></channel></rss>")


def many_repos(count=17):
    return "<html>" + "".join(
        '<article><h2><a href="/own%02d/repo%02d">r</a></h2><p>desc %d</p></article>' % (i, i, i)
        for i in range(count)) + "</html>"


def exact_cap_body(length):
    """A feed padded with a comment to exactly `length` bytes (the transport cap is on BYTES, so ASCII only)."""
    head, tail = "<rss><channel><item><link>https://news.hada.io/topic?id=9</link><title>t</title></item></channel></rss>", ""
    pad = length - len(head) - len("<!---->")
    return head + "<!--" + "z" * pad + "-->" + tail


OVERSIZE = exact_cap_body(2_000_001)
AT_CAP = exact_cap_body(2_000_000)
BODIES = {"github_html": GITHUB_HTML, "rss": RSS, "atom": ATOM, "mixed": MIXED, "malformed_page": MALFORMED_PAGE,
          "malformed_feed": MALFORMED_FEED, "no_entries": NO_ENTRIES, "not_xml": NOT_XML, "small_rss": SMALL_RSS,
          "oversize_2000001": OVERSIZE, "at_cap_2000000": AT_CAP}
GH_API = "https://api.github.com/repos/acme/pgtool"
SHA = "a" * 40
README = "# pgtool\n" + "héllo " * 3000  # multi-byte: the excerpt cut is on UTF-8 bytes
METADATA = {"description": "Postgres tooling", "license": {"spdx_id": "MIT"}, "default_branch": "release/1.x",
            "archived": False, "pushed_at": "2028-01-01T00:00:00Z"}
T0 = "2026-09-28T00:00:00+00:00"
BUDGET = {"per_host": 192, "total": 192, "mode": "subscription"}
POLICY = {"schema": "urn:zeus:discovery-pressure-policy:1", "id": "fixture-policy", "k_pause": 3, "k_resume": 1,
          "threshold_status": "suggested_unconfirmed", "input_max_age_seconds": 300}
LEDGER = {"host": "fixture", "this_host": 0, "all_hosts": 0, "unreadable": 0}
LEDGER_DAMAGED = {"host": "fixture", "this_host": 1, "all_hosts": 1, "unreadable": 1}
LEDGER_FULL = {"host": "fixture", "this_host": 1, "all_hosts": 1, "unreadable": 0}
PROXY_ENV = {"http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def describe(body: str) -> dict:
    return {"chars": len(body), "sha256": sha256(body)}


# ---- doubles ----------------------------------------------------------------------------------------------------------------
class Artifacts:
    """LABELLED. A stand-in artifact store: `put(body, url)` records the call and returns the `{"ref": ...}` receipt shape."""

    def __init__(self, fail=False):
        self.puts, self.fail = [], fail

    def put(self, body, source):
        if self.fail:
            raise OSError("fixture artifact store down")
        self.puts.append({"source": source, **describe(body)})
        return {"ref": "sha256:" + sha256(body)}


class Stub:
    """LABELLED. The recorded-body replacement of `ResearchSources.fetch` (set on the instance): `calls` records every url, a
    value in `responses` is the body, an exception INSTANCE is raised; an unscripted url raises (never a network read)."""

    def __init__(self, responses):
        self.responses, self.calls = dict(responses), []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.responses:
            raise AssertionError("unscripted fetch " + url)
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        return value


class Holding:
    """LABELLED. M7 `Holding`: an evaluator that always holds and counts its consultations."""

    def __init__(self):
        self.calls = 0

    def admit(self):
        self.calls += 1
        return {"decision": "hold", "reason_code": "pressure_high"}


class Scripted:
    """LABELLED. An evaluator answering a scripted value (an exception instance is raised) and counting its consultations."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def admit(self):
        self.calls += 1
        value = self.answers.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class Response:
    """LABELLED. A stand-in for the object `urlopen` returns: a context manager whose `read(n)` returns the first n bytes."""

    def __init__(self, data):
        self.data, self.reads = data, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size):
        self.reads.append(size)
        return self.data[:size]


class Transport:
    """LABELLED. The replacement of the module's `urlopen` name: records the request and timeout, answers `data` (bytes)
    or raises `error`. The real `urlopen` is never called."""

    def __init__(self, data=b"", error=None):
        self.data, self.error, self.requests, self.responses = data, error, [], []

    def __call__(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "headers": sorted(request.header_items()), "timeout": timeout,
                              "method": request.get_method()})
        if self.error is not None:
            raise self.error
        response = Response(self.data)
        self.responses.append(response)
        return response


@contextlib.contextmanager
def environment(values):
    """LABELLED. Set environment variables for the block and restore them (absent stays absent) afterwards."""
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def outcome(fn, *args, **kwargs):
    """The characterized outcome of one call: `{"value": ...}` or the exception (type, reason_code, message)."""
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        result = {"raised": type(exc).__name__}
        for name in ("reason_code",):
            if hasattr(exc, name):
                result[name] = getattr(exc, name)
        result["message"] = str(exc)[:200]
        return result


def sources(api, stub, pressure=None, artifacts=None):
    """A real `ResearchSources` whose `fetch` is the LABELLED stub (instance attribute: `self.fetch(url)` resolves to it)."""
    artifacts = artifacts if artifacts is not None else Artifacts()
    instance = api.ResearchSources(artifacts, pressure=pressure)
    instance.fetch = stub
    return instance, artifacts


def collected(api, source, stub, intent="user_request", pressure=None, artifacts=None):
    instance, art = sources(api, stub, pressure, artifacts)
    return {"result": outcome(instance.collect, source, intent=intent), "fetch_calls": list(stub.calls), "artifact_puts": art.puts}


# ---- parse -----------------------------------------------------------------------------------------------------------------
def parse(api, ws=None):
    results = {}
    for name in ("github_html", "malformed_page", "no_entries", "not_xml", "rss"):
        results["parse_github_" + name] = outcome(api.ResearchSources.parse_github, BODIES[name])
    results["parse_github_empty"] = outcome(api.ResearchSources.parse_github, "")
    results["parse_github_seventeen"] = (lambda r: {"count": len(r["value"]), "first": r["value"][0], "last": r["value"][-1]})(
        outcome(api.ResearchSources.parse_github, many_repos(17)))
    for name in ("rss", "atom", "mixed", "malformed_feed", "malformed_page", "no_entries", "not_xml", "github_html", "small_rss"):
        results["parse_feed_" + name] = outcome(api.ResearchSources.parse_feed, BODIES[name])
    results["parse_feed_empty"] = outcome(api.ResearchSources.parse_feed, "")
    long_summary = outcome(api.ResearchSources.parse_feed, RSS)["value"]
    results["parse_feed_summary_bound"] = [len(item["summary"]) for item in long_summary]
    # The 2,000,001-byte body parsed directly (the cap is the transport's, not the parser's).
    results["oversize_body"] = {"body": describe(OVERSIZE), "bytes": len(OVERSIZE.encode("utf-8")),
                                "parse_feed": outcome(api.ResearchSources.parse_feed, OVERSIZE),
                                "parse_github": outcome(api.ResearchSources.parse_github, OVERSIZE)}
    results["at_cap_body"] = {"body": describe(AT_CAP), "bytes": len(AT_CAP.encode("utf-8")),
                              "parse_feed": outcome(api.ResearchSources.parse_feed, AT_CAP)}
    return results


# ---- collect ---------------------------------------------------------------------------------------------------------------
def collect(api, ws=None):
    urls = api.ResearchSources.URLS
    results = {"urls": dict(urls)}
    results["github"] = collected(api, "github", Stub({urls["github"]: GITHUB_HTML}))
    results["github_seventeen_items_bound"] = (lambda r: {"fetch_calls": r["fetch_calls"], "items": len(r["result"]["value"]["items"])})(
        collected(api, "github", Stub({urls["github"]: many_repos(17)})))
    results["geeknews_rss"] = collected(api, "geeknews", Stub({urls["geeknews"]: RSS}))
    results["geeknews_atom"] = collected(api, "geeknews", Stub({urls["geeknews"]: ATOM}))
    results["geeknews_mixed"] = collected(api, "geeknews", Stub({urls["geeknews"]: MIXED}))
    results["geeknews_malformed"] = collected(api, "geeknews", Stub({urls["geeknews"]: MALFORMED_FEED}))
    results["geeknews_no_entries"] = collected(api, "geeknews", Stub({urls["geeknews"]: NO_ENTRIES}))
    results["github_malformed_page"] = collected(api, "github", Stub({urls["github"]: MALFORMED_PAGE}))
    results["github_page_without_articles"] = collected(api, "github", Stub({urls["github"]: "<html></html>"}))
    results["unknown_source"] = collected(api, "reddit", Stub({}))
    results["empty_source"] = collected(api, "", Stub({}))
    # The size cap as `collect` returns it with the fetch stubbed: the stub's body reaches the artifact store and the parser
    # unchecked (the byte cap is the real `fetch`'s, see `transport`).
    results["oversize_2000001_stubbed"] = collected(api, "geeknews", Stub({urls["geeknews"]: OVERSIZE}))
    # A fetch that raises propagates out of `collect` unchanged (nothing is stored) ...
    errors = {
        "http_error": urllib.error.HTTPError(urls["github"], 503, "Service Unavailable", {}, None),
        "url_error": urllib.error.URLError("fixture: name resolution failed"),
        "timeout": TimeoutError("fixture timed out"), "socket_timeout": socket.timeout("fixture socket timeout"),
        "os_error": OSError("fixture connection reset"), "contract_error": api.ContractError("Research response exceeds size budget"),
        "value_error": ValueError("fixture bad value")}
    results["fetch_raises"] = {name: collected(api, "github", Stub({urls["github"]: error})) for name, error in errors.items()}
    results["artifact_store_down"] = collected(api, "geeknews", Stub({urls["geeknews"]: RSS}), artifacts=Artifacts(fail=True))
    # ... and `collect_live` swallows each into a status row recording the exception TYPE only.
    live = {}
    for name, error in errors.items():
        stub = Stub({urls["github"]: error, urls["geeknews"]: error})
        instance, art = sources(api, stub)
        status, items = api.collect_live(instance, intent="user_request")
        live[name] = {"status": status, "items": len(items), "fetch_calls": list(stub.calls), "artifact_puts": len(art.puts)}
    both = Stub({urls["github"]: GITHUB_HTML, urls["geeknews"]: RSS})
    instance, art = sources(api, both)
    status, items = api.collect_live(instance, intent="user_request")
    live["both_ok"] = {"status": status, "items": len(items), "fetch_calls": list(both.calls), "artifact_puts": len(art.puts)}
    mixed = Stub({urls["github"]: urllib.error.HTTPError(urls["github"], 404, "Not Found", {}, None), urls["geeknews"]: ATOM})
    instance, art = sources(api, mixed)
    status, items = api.collect_live(instance, intent="user_request")
    live["one_down"] = {"status": status, "items": len(items), "fetch_calls": list(mixed.calls), "artifact_puts": len(art.puts)}
    results["collect_live_swallow"] = live
    results["github_detail"] = github_detail(api)
    return results


def api_responses(metadata=METADATA, sha=SHA, readme=None):
    readme = readme if readme is not None else {"encoding": "base64", "path": "README.md",
                                                "content": base64.b64encode(README.encode("utf-8")).decode("ascii")}
    return {GH_API: json.dumps(metadata),
            GH_API + "/commits/release%2F1.x": json.dumps({"sha": sha}),
            GH_API + "/readme?ref=" + sha: json.dumps(readme)}


def detail(api, url, responses):
    stub, art = Stub(responses), Artifacts()
    instance = api.ResearchSources(art)
    instance.fetch = stub
    result = outcome(instance.github_detail, url)
    if "value" in result:
        value = dict(result["value"])
        value["readme_excerpt"] = {"bytes": len(value["readme_excerpt"].encode("utf-8")), "sha256": sha256(value["readme_excerpt"])}
        result = {"value": value}
    return {"result": result, "fetch_calls": list(stub.calls), "artifact_puts": art.puts}


def github_detail(api):
    results = {"success": detail(api, "https://github.com/acme/pgtool", api_responses())}
    no_license = {**METADATA, "license": None}
    results["no_license"] = detail(api, "https://github.com/acme/pgtool", api_responses(no_license))
    for bad in ("https://github.com/acme", "https://github.com/acme/pgtool/", "http://github.com/acme/pgtool",
                "https://github.com/acme/pgtool/tree/main", "https://gitlab.com/acme/pgtool", "", "https://github.com/a b/c"):
        results["invalid_url_" + bad.replace("/", "_").replace(":", "")[:40]] = detail(api, bad, {})
    results["invalid_revision"] = detail(api, "https://github.com/acme/pgtool", api_responses(sha="Z" * 40))
    results["short_revision"] = detail(api, "https://github.com/acme/pgtool", api_responses(sha="a" * 39))
    results["readme_encoding"] = detail(api, "https://github.com/acme/pgtool",
                                        api_responses(readme={"encoding": "none", "path": "README.md", "content": ""}))
    results["metadata_not_json"] = detail(api, "https://github.com/acme/pgtool", {GH_API: "<html>rate limited</html>"})
    results["metadata_without_branch"] = detail(api, "https://github.com/acme/pgtool", {GH_API: json.dumps({})})
    results["metadata_without_archived"] = detail(
        api, "https://github.com/acme/pgtool",
        api_responses({"default_branch": "release/1.x", "pushed_at": "x"}))
    results["http_error"] = detail(api, "https://github.com/acme/pgtool",
                                   {GH_API: urllib.error.HTTPError(GH_API, 403, "rate limit", {}, None)})
    results["timeout_on_commit"] = detail(api, "https://github.com/acme/pgtool", {
        GH_API: json.dumps(METADATA), GH_API + "/commits/release%2F1.x": TimeoutError("fixture timed out")})
    results["readme_missing_key"] = detail(api, "https://github.com/acme/pgtool", api_responses(readme={"encoding": "base64"}))
    return results


# ---- transport (the real `fetch` over the labelled urlopen double) --------------------------------------------------------
def transport(api, ws=None):
    results = {}

    def run(name, data=b"", error=None):
        double = Transport(data, error)
        with api.patch_urlopen(double):
            instance = api.ResearchSources(Artifacts())
            result = outcome(instance.fetch, "https://example.invalid/feed")
        if "value" in result:
            result = {"value": describe(result["value"])}
        results[name] = {"result": result, "requests": double.requests, "reads": [r.reads for r in double.responses]}
    run("small", SMALL_RSS.encode())
    run("at_cap_2000000", AT_CAP.encode())
    run("over_cap_2000001", OVERSIZE.encode())
    run("far_over_cap", b"x" * 2_500_000)
    run("empty", b"")
    run("invalid_utf8_replaced", b"<rss>\xff\xfe</rss>")
    run("multibyte", "<rss>한글</rss>".encode("utf-8"))
    run("http_error", error=urllib.error.HTTPError("https://example.invalid/feed", 500, "boom", {}, None))
    run("timeout", error=TimeoutError("fixture timed out"))
    run("os_error", error=OSError("fixture unreachable"))
    # a `collect` over the real `fetch` (transport double): the size refusal reaches the caller, nothing is stored.
    double, art = Transport(OVERSIZE.encode()), Artifacts()
    with api.patch_urlopen(double):
        got = outcome(api.ResearchSources(art).collect, "geeknews", intent="task_required")
    results["collect_over_cap"] = {"result": got, "puts": art.puts, "urls": [r["url"] for r in double.requests]}
    double, art = Transport(AT_CAP.encode()), Artifacts()
    with api.patch_urlopen(double):
        got = outcome(api.ResearchSources(art).collect, "geeknews", intent="task_required")
    results["collect_at_cap"] = {"result": got, "puts": art.puts, "urls": [r["url"] for r in double.requests]}
    return results


# ---- pressure hold before fetch --------------------------------------------------------------------------------------------
def fleet_store(api, max_parallel=2, budget=BUDGET):
    store = api.MemoryStore()
    api.Fleet(store).register({
        "schema": "urn:zeus:fleet:1", "id": "fleet-fixture", "max_parallel": max_parallel, "budget": dict(budget),
        "lanes": [{"id": lane, "team": lane, "repository": "/fixture/repo-" + lane, "schema": "lane_" + lane,
                   "redis_namespace": "fleet-" + lane, "runtime": "/fixture/rt-" + lane} for lane in ("a", "b")]})
    return store


def job(job_id, status="queued", lane="a", dependencies=(), paths=("src/x/",), budget=BUDGET, created=T0):
    """LABELLED FIXTURE fleet job row with the fields admission reads (M7 `test_discovery_pressure.job`)."""
    return {"id": job_id, "status": status, "lane": lane, "repository": "/fixture/repo-" + lane,
            "dependencies": list(dependencies), "created_at": created, "updated_at": created,
            "manifest": {"budget": dict(budget), "plan": {"allowed_paths": list(paths)}}}


def put(store, bucket, row, key=None):
    with store.transaction() as tx:
        tx.put(bucket, key or row["id"], row)


def queued(store, count, lane="a"):
    for index in range(count):
        put(store, "fleet_jobs", job(f"q{lane}{index}", lane=lane, paths=(f"src/{lane}{index}/",)))


def audits(api, store):
    with store.transaction() as tx:
        return [{key: row["attributes"].get(key) for key in ("version", "from_state", "to_state", "from_decision", "to_decision", "waiting", "capacity")}
                | {"reason_code": row.get("reason_code")}
                for row in tx.scan("observation_audit") if row.get("event_type") == "operations.discovery_pressure_changed"]


def evaluator(api, store, policy=POLICY, ledger=LEDGER, clock=None):
    observer = api.Observer(store, api.MemorySpool(api.new_process_run_id()), component="test-pressure", directory=api.MemoryDirectory())
    kwargs = {} if clock is None else {"clock": clock}
    return api.DiscoveryPressure(store, policy, observer, ledger=None if ledger is None else (lambda: ledger), **kwargs)


def brief(decision):
    """The decision the evaluator returned, without the wall-clock stamps."""
    return {key: value for key, value in decision.items() if key not in ("evaluated_at", "transitioned_at")}


def instants(*seconds):
    values = [(datetime.fromisoformat(T0) + timedelta(seconds=value)).isoformat() for value in seconds]
    return lambda: values.pop(0)


def census_of(api, store, ledger=LEDGER, control=None):
    with store.transaction() as tx:
        registry = api.Fleet._registry(tx)
        jobs = {row["id"]: row for row in tx.scan("fleet_jobs")}
        units = tx.scan("fleet_units")
        plans, intents = tx.scan("fleet_backlog_plans"), tx.scan("fleet_backlog_intents")
        continuation = tx.scan("continuation_intents")
    return api.census(config=None if registry is None else registry["config"], control=control or {"paused": False},
                      jobs=jobs, units=units, plans=plans, intents=intents, continuation_intents=continuation, ledger=ledger)


PLAN = {"schema": "urn:zeus:fleet-backlog:1", "plan_id": "plan-1", "repository": "r" * 64, "enabled": True,
        "items": [{"id": "item-1", "project_id": "p", "criterion_id": "c", "lane": "a", "manifest_path": "m.json",
                   "manifest_revision": "a" * 40, "manifest_sha256": "b" * 64, "priority": 1, "dependencies": []}]}


def put_plan(store, enabled=True):
    put(store, "fleet_backlog_plans", {"plan_id": "plan-1", "plan": {**PLAN, "enabled": enabled}, "plan_sha256": "c" * 64,
                                       "pin": {"revision": "a" * 40, "path": "b.json", "sha256": "d" * 64}}, "plan-1")


def pressure_hold(api, ws=None):
    results = {}
    urls = api.ResearchSources.URLS
    exempt = tuple(api.EXEMPT_INTENTS)
    results["intents"] = {"proactive": api.PROACTIVE, "exempt": list(exempt), "all": list(api.INTENTS)}

    # 1 validate_intent (and `collect` refusing before any IO)
    refusals = {}
    for label, intent in (("none", None), ("empty", ""), ("unknown", "research"), ("upper", "PROACTIVE"), ("number", 3)):
        pressure, stub = Holding(), Stub({})
        refused = collected(api, "github", stub, intent=intent, pressure=pressure)
        refusals[label] = {**refused, "pressure_calls": pressure.calls, "validate_intent": outcome(api.validate_intent, intent)}
    refusals["valid"] = {intent: outcome(api.validate_intent, intent) for intent in api.INTENTS}
    results["validate_intent"] = refusals

    # 2 proactive while the policy holds: ZERO fetch calls
    held = {}
    for label, pressure in (("holding_evaluator", Holding()), ("no_evaluator", None),
                            ("evaluator_raises", Scripted(RuntimeError("fixture evaluator failure"))),
                            ("non_dict_decision", Scripted("allow")), ("none_decision", Scripted(None)),
                            ("allow_flag_missing", Scripted({"decision": "hold"})),
                            ("unknown_decision_value", Scripted({"decision": "maybe", "reason_code": "x"}))):
        for source in ("github", "geeknews"):
            stub = Stub({urls[source]: GITHUB_HTML if source == "github" else RSS})
            got = collected(api, source, stub, intent="proactive", pressure=pressure)
            held[label + "_" + source] = {**got, "stub_fetch_calls": len(stub.calls),
                                          "pressure_calls": getattr(pressure, "calls", None)}
    results["proactive_held_zero_fetch"] = held
    results["zero_fetch_proof"] = {"cases": len(held), "stub_fetch_calls_total": sum(c["stub_fetch_calls"] for c in held.values()),
                                   "artifact_puts_total": sum(len(c["artifact_puts"]) for c in held.values())}

    # a DiscoveryPaused carries the decision and reason code
    stub = Stub({})
    instance, _ = sources(api, stub, Holding())
    try:
        instance.collect("github", intent="proactive")
    except api.DiscoveryPaused as exc:
        results["paused_exception"] = {"decision": exc.decision, "reason_code": exc.reason_code, "message": str(exc),
                                       "is_contract_error": isinstance(exc, api.ContractError)}

    # 3 proactive while the policy ALLOWS: one fetch
    allowed = Stub({urls["geeknews"]: SMALL_RSS})
    results["proactive_allowed"] = collected(api, "geeknews", allowed, intent="proactive",
                                             pressure=Scripted({"decision": "allow", "reason_code": "pressure_ok"}))

    # 4 every exempt intent never consults pressure (and with no evaluator wired)
    exempt_cases = {}
    for intent in exempt:
        pressure = Holding()
        stub = Stub({urls["geeknews"]: SMALL_RSS})
        got = collected(api, "geeknews", stub, intent=intent, pressure=pressure)
        none = collected(api, "geeknews", Stub({urls["geeknews"]: SMALL_RSS}), intent=intent)
        exempt_cases[intent] = {"with_holding_evaluator": {**got, "pressure_calls": pressure.calls},
                                "without_evaluator": none}
    results["exempt_never_consult"] = exempt_cases

    # 5 real evaluator over a MemoryStore: the hold reaches `collect` before fetch
    real = {}
    store = api.MemoryStore()
    stub = Stub({urls["github"]: GITHUB_HTML})
    real["unregistered_fleet"] = {**collected(api, "github", stub, "proactive", evaluator(api, store)), "stub_fetch_calls": len(stub.calls)}
    store = fleet_store(api)
    api.Fleet(store).pause()
    stub = Stub({urls["github"]: GITHUB_HTML})
    real["paused_fleet"] = {**collected(api, "github", stub, "proactive", evaluator(api, store)), "stub_fetch_calls": len(stub.calls)}
    store = fleet_store(api, max_parallel=1)
    queued(store, 3)
    stub = Stub({urls["github"]: GITHUB_HTML})
    real["pressure_high"] = {**collected(api, "github", stub, "proactive", evaluator(api, store)), "stub_fetch_calls": len(stub.calls)}
    store = fleet_store(api)
    stub = Stub({urls["geeknews"]: SMALL_RSS})
    real["pressure_ok"] = {**collected(api, "geeknews", stub, "proactive", evaluator(api, store)), "stub_fetch_calls": len(stub.calls)}
    store = fleet_store(api, max_parallel=1)
    queued(store, 3)
    stub = Stub({urls["geeknews"]: SMALL_RSS})
    real["exempt_while_high"] = {**collected(api, "geeknews", stub, "user_request", evaluator(api, store)), "stub_fetch_calls": len(stub.calls),
                                 "row_written": store_row(api, store) is not None}
    store = fleet_store(api, max_parallel=1)
    queued(store, 3)
    stub = Stub({})
    instance, _ = sources(api, stub, evaluator(api, store))
    status, items = api.collect_live(instance, intent="proactive")
    real["collect_live_proactive_high"] = {"status": status, "items": items, "stub_fetch_calls": len(stub.calls)}
    results["real_evaluator_holds_before_fetch"] = real
    results["real_evaluator_zero_fetch_total"] = sum(case["stub_fetch_calls"] for key, case in real.items() if key not in ("pressure_ok", "exempt_while_high"))

    # 6 validate_policy
    policy_cases = {"valid": POLICY, "float_thresholds": {**POLICY, "k_pause": 2.5, "k_resume": 0.5},
                    "zero_resume": {**POLICY, "k_resume": 0}, "confirmed": {**POLICY, "threshold_status": "confirmed"},
                    "not_dict": ["x"], "none": None, "wrong_schema": {**POLICY, "schema": "urn:zeus:other:1"},
                    "extra_key": {**POLICY, "extra": 1}, "missing_age": {k: v for k, v in POLICY.items() if k != "input_max_age_seconds"},
                    "resume_equals_pause": {**POLICY, "k_resume": 3}, "resume_above_pause": {**POLICY, "k_resume": 5},
                    "negative_resume": {**POLICY, "k_resume": -1}, "bool_pause": {**POLICY, "k_pause": True},
                    "string_pause": {**POLICY, "k_pause": "3"}, "nan_pause": {**POLICY, "k_pause": float("nan")},
                    "inf_pause": {**POLICY, "k_pause": float("inf")}, "bad_status": {**POLICY, "threshold_status": "guessed"},
                    "empty_id": {**POLICY, "id": ""}, "int_id": {**POLICY, "id": 1}, "zero_age": {**POLICY, "input_max_age_seconds": 0},
                    "float_age": {**POLICY, "input_max_age_seconds": 300.0}, "bool_age": {**POLICY, "input_max_age_seconds": True}}
    results["validate_policy"] = {name: outcome(api.validate_policy, copy.deepcopy(doc)) for name, doc in policy_cases.items()}
    results["packaged_policy"] = outcome(lambda: api.validate_policy(api.packaged_policy()))
    invalid = {}
    for name, doc in (("none", None), ("resume_above", {**POLICY, "k_resume": 5}), ("bad_status", {**POLICY, "threshold_status": "guessed"}),
                      ("missing_age", {k: v for k, v in POLICY.items() if k != "input_max_age_seconds"})):
        invalid[name] = brief(api.DiscoveryPressure(fleet_store(api), doc, evaluator(api, api.MemoryStore()).observer).admit())
    results["evaluator_with_invalid_policy"] = invalid

    # 7 decide hysteresis
    policy = api.validate_policy(POLICY)
    band = {}
    for waiting, prior in ((6, None), (5, None), (5, "paused"), (3, "paused"), (2, "paused"), (0, "paused"), (4, "active"), (7, "active"),
                           (1, None), (2, None), (3, "active"), (6, "paused")):
        observed = {"registered": True, "paused": False, "capacity": 2, "waiting": waiting, "complete": True}
        band["w%d_%s" % (waiting, prior)] = api.decide({"hysteresis_state": prior} if prior else None, observed, policy)
    results["decide_hysteresis"] = band
    other = {}
    base = {"registered": True, "paused": False, "capacity": 2, "waiting": 0, "complete": True}
    for name, observed, prior, pol in (
            ("unregistered", {"registered": False}, {"hysteresis_state": "paused"}, policy),
            ("paused_fleet", {**base, "paused": True}, None, policy), ("no_policy", base, {"hysteresis_state": "paused"}, None),
            ("capacity_zero", {**base, "capacity": 0}, None, policy), ("capacity_bool", {**base, "capacity": True}, None, policy),
            ("capacity_none", {**base, "capacity": None}, {"hysteresis_state": "paused"}, policy),
            ("incomplete", {**base, "complete": False, "waiting": 9}, {"hysteresis_state": "paused"}, policy),
            ("capacity_one_pause_at_three", {**base, "capacity": 1, "waiting": 3}, None, policy),
            ("capacity_one_resume_at_one", {**base, "capacity": 1, "waiting": 1}, {"hysteresis_state": "paused"}, policy),
            ("empty_prior_state", {**base, "waiting": 3}, {"hysteresis_state": None}, policy)):
        other[name] = outcome(api.decide, prior, observed, pol)
    results["decide_fallbacks"] = other

    # 8 unrecorded_hold
    results["unrecorded_hold"] = {name: api.unrecorded_hold(name) for name in ("evaluation_failed", "evaluation_invalid", "")}

    # 9 sample_fresh
    fresh = {}
    for label, sampled, evaluated, age in (
            ("fresh", T0, "2026-09-28T00:00:01+00:00", 300), ("limit", T0, "2026-09-28T00:05:00+00:00", 300),
            ("over_limit", T0, "2026-09-28T00:05:01+00:00", 300), ("backwards", "2026-09-28T00:00:01+00:00", T0, 300),
            ("offset", "2026-09-28T09:00:00+09:00", "2026-09-28T00:00:01+00:00", 300),
            ("both_naive", "2026-09-28T00:00:00", "2026-09-28T00:00:01", 300), ("mixed", "2026-09-28T00:00:00", "2026-09-28T00:00:01+00:00", 300),
            ("unparseable", "not a time", "2026-09-28T00:00:01+00:00", 300), ("none", None, "2026-09-28T00:00:01+00:00", 300)):
        fresh[label] = outcome(api.sample_fresh, sampled, evaluated, age)
    results["sample_fresh"] = fresh

    results["census"] = census_cases(api)
    results["evaluator"] = evaluator_cases(api)
    return results


def store_row(api, store):
    with store.transaction() as tx:
        return tx.get(api.BUCKET, api.KEY)


def census_cases(api):
    cases = {}
    cases["unregistered"] = census_of(api, api.MemoryStore())
    # a waiting-only (lane_busy) job counts as waiting; blocked jobs are excluded with their reason
    store = fleet_store(api)
    put(store, "fleet_jobs", job("running-a", status="dispatching", lane="a", paths=("src/shared/",)))
    put(store, "fleet_jobs", job("failed-dep", status="failed", lane="b", paths=("src/f/",)))
    put(store, "fleet_jobs", job("ready", lane="b", paths=("src/r/",)))
    put(store, "fleet_jobs", job("lane-only", lane="a", paths=("src/other/",)))
    put(store, "fleet_jobs", job("lane-and-conflict", lane="a", paths=("src/shared/",)))
    put(store, "fleet_jobs", job("dep-failed", lane="b", dependencies=("failed-dep",), paths=("src/d/",)))
    put(store, "fleet_jobs", job("stale", lane="b", budget={"per_host": 1, "total": 1}, paths=("src/s/",)))
    put(store, "fleet_jobs", job("unknown-held", status="unknown", lane="b", paths=("src/u/",)))
    cases["job_exclusions"] = census_of(api, store)
    store = fleet_store(api)
    put(store, "fleet_jobs", job("running-a", status="dispatching", lane="a", paths=("src/shared/",)))
    put(store, "fleet_jobs", job("lane-only", lane="a", paths=("src/other/",)))
    cases["waiting_only_lane_busy"] = census_of(api, store)
    store = fleet_store(api)
    put(store, "fleet_jobs", job("failed-dep", status="failed", lane="b", paths=("src/f/",)))
    put(store, "fleet_jobs", job("blocked", lane="b", dependencies=("failed-dep",), paths=("src/d/",)))
    put(store, "fleet_jobs", job("missing-dep", lane="b", dependencies=("nowhere",), paths=("src/m/",)))
    put(store, "fleet_jobs", job("waiting-dep", lane="b", dependencies=("blocked",), paths=("src/w/",)))
    cases["blocked_jobs"] = census_of(api, store)
    store = fleet_store(api)
    put(store, "fleet_units", {"id": "unit-held", "state": "held"})
    put(store, "fleet_units", {"id": "unit-released", "state": "released"})
    cases["held_unit"] = census_of(api, store)
    store = fleet_store(api)
    put_plan(store)
    cases["backlog_unknown"] = census_of(api, store)
    put_plan(store, enabled=False)
    cases["backlog_disabled"] = census_of(api, store)
    put_plan(store)
    put(store, "fleet_backlog_intents", {"id": "i-1", "plan_id": "plan-1", "item_id": "item-1", "state": "intended", "job_id": "job-of-item", "attempts": 1})
    put(store, "fleet_jobs", job("job-of-item"))
    cases["backlog_open_with_job"] = census_of(api, store)
    store = fleet_store(api)
    put(store, "continuation_intents", {"id": "i1", "route": "requalification", "state": "admitted", "successor_job": "succ-1"})
    cases["continuation_unknown"] = census_of(api, store)
    put(store, "fleet_jobs", job("succ-1"))
    cases["continuation_with_successor_job"] = census_of(api, store)
    put(store, "continuation_intents", {"id": "i2", "route": "research", "state": "intended"})
    cases["continuation_research_route"] = census_of(api, store)
    store = fleet_store(api)
    put(store, "continuation_intents", {"id": "held", "route": "correction", "state": "intended", "hold": {"reason_code": "authority_drift"}})
    cases["continuation_held"] = census_of(api, store)
    store = fleet_store(api)
    put(store, "continuation_intents", {"id": "c1", "route": "conductor", "state": "intended"})
    cases["continuation_conductor_intended"] = census_of(api, store)
    # the ledger: unreadable while jobs wait is unknown; exhausted removes the waiting jobs; with none waiting it is moot
    for budget_name, budget in (("subscription", BUDGET), ("finite", {"per_host": 4, "total": 8})):
        store = fleet_store(api, budget=budget)
        put(store, "fleet_jobs", job("ready", budget=budget))
        for label, ledger in (("none", None), ("broken", {"broken": True}), ("damaged", LEDGER_DAMAGED), ("clean", LEDGER)):
            cases["ledger_%s_%s" % (budget_name, label)] = census_of(api, store, ledger=ledger)
        cases["ledger_%s_none_without_waiting" % budget_name] = census_of(api, fleet_store(api, budget=budget), ledger=None)
    finite = {"per_host": 1, "total": 1}
    store = fleet_store(api, max_parallel=1, budget=finite)
    for index in range(3):
        put(store, "fleet_jobs", job(f"q{index}", budget=finite, paths=(f"src/{index}/",)))
    cases["ledger_finite_exhausted"] = census_of(api, store, ledger=LEDGER_FULL)
    cases["fleet_paused_control"] = census_of(api, store, ledger=LEDGER, control={"paused": True})
    return cases


def evaluator_cases(api):
    results = {}
    # the capacity is the configured slots, not the free ones
    store = fleet_store(api, max_parallel=2)
    put(store, "fleet_jobs", job("busy-a", status="dispatching", lane="a"))
    put(store, "fleet_jobs", job("busy-b", status="dispatching", lane="b", paths=("src/b/",)))
    results["capacity_is_configured_slots"] = brief(evaluator(api, store).admit())
    # the first reading is evaluated; a restart keeps the hysteresis memory; reading the status writes nothing
    store = fleet_store(api, max_parallel=1)
    queued(store, 3)
    first = brief(evaluator(api, store).admit())
    with store.transaction() as tx:
        tx.put("fleet_jobs", "qa0", {**tx.get("fleet_jobs", "qa0"), "status": "accepted"})
    restarted = brief(evaluator(api, store).admit())
    before = copy.deepcopy(store.data)
    results["first_reading_and_restart"] = {"first": first, "restarted_in_band": restarted,
                                            "status_row": api.status(store)["row"] and brief(api.status(store)["row"]),
                                            "status_writes_nothing": store.data == before,
                                            "status_unevaluated": api.status(api.MemoryStore())}
    # one transition, one audit event; a repeat only advances the evaluation sequence
    store = fleet_store(api, max_parallel=1)
    pressure = evaluator(api, store)
    one, two = pressure.admit(), pressure.admit()
    queued(store, 3)
    three = pressure.admit()
    results["transition_audit"] = {"versions": [one["version"], two["version"], three["version"]],
                                  "sequences": [one["evaluation_sequence"], two["evaluation_sequence"], three["evaluation_sequence"]],
                                  "state_after": three["hysteresis_state"], "audits": audits(api, store)}
    # a failed audit rolls back and holds unrecorded
    store = fleet_store(api)

    class Failing:
        def audit(self, tx, *args, **kwargs):
            raise RuntimeError("injected audit failure")  # LABELLED fault: the mandatory audit fails
    failed = api.DiscoveryPressure(store, POLICY, Failing()).admit()
    results["failed_audit"] = {"decision": failed, "row_written": store_row(api, store) is not None,
                               "next_evaluation_recorded": evaluator(api, store).admit()["recorded"]}
    results["observer_required"] = outcome(api.DiscoveryPressure, store, POLICY, None)
    # unknown input holds and keeps the memory; stale and naive clocks
    store = fleet_store(api, max_parallel=1)
    queued(store, 3)
    paused = brief(evaluator(api, store).admit())
    held = brief(evaluator(api, store, ledger=None).admit())
    with store.transaction() as tx:
        tx.put("fleet_jobs", "qa0", {**tx.get("fleet_jobs", "qa0"), "status": "accepted"})
    in_band = brief(evaluator(api, store).admit())
    results["unknown_keeps_memory"] = {"paused": paused, "unknown": held, "in_band_after": in_band}
    store = fleet_store(api, max_parallel=1)
    queued(store, 3)

    def admit(*seconds):
        return brief(evaluator(api, store, clock=instants(*seconds)).admit())
    stale = {"within": admit(0, 300), "stale": admit(0, 301)}
    for index in range(2):
        with store.transaction() as tx:
            tx.put("fleet_jobs", f"qa{index}", {**tx.get("fleet_jobs", f"qa{index}"), "status": "accepted"})
    stale["stale_does_not_resume"] = admit(0, 900)
    stale["backwards_clock"] = admit(10, 0)
    stale["fresh_resumes"] = admit(0, 1)
    results["ledger_freshness"] = stale
    store = fleet_store(api)
    queued(store, 1)
    values = ["2026-09-28T00:00:00", "2026-09-28T00:00:01"]
    results["naive_clock"] = brief(evaluator(api, store, clock=lambda: values.pop(0)).admit())
    # an evaluation that cannot complete is an unrecorded unknown hold
    damage = {}
    for name in ("registry_malformed", "jobs_unreadable", "store_unavailable"):
        store = fleet_store(api)
        queued(store, 1)
        if name == "registry_malformed":
            put(store, "fleet_registry", {"id": "second-fleet"}, "second-fleet")
            target = store
        elif name == "jobs_unreadable":
            target = FailingReads(store, "fleet_jobs")
        else:
            target = SimpleNamespace(transaction=lambda: (_ for _ in ()).throw(OSError("store unavailable")))
        observer = evaluator(api, store).observer
        decision = api.DiscoveryPressure(target, POLICY, observer, ledger=lambda: LEDGER).admit()
        damage[name] = {"decision": decision, "evaluated": api.status(store)["evaluated"], "audits": audits(api, store)}
    results["evaluation_cannot_complete"] = damage
    results["monitor_projection"] = monitor(api)
    return results


class FailingReads:
    """LABELLED FIXTURE (M7 `FailingReads`): a store whose scan of one bucket fails inside the evaluation transaction."""

    def __init__(self, store, bucket):
        self.store, self.bucket = store, bucket

    @contextlib.contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            yield ReadFailingTx(tx, self.bucket)


class ReadFailingTx:
    def __init__(self, tx, bucket):
        self.tx, self.bucket = tx, bucket

    def scan(self, bucket, *args, **kwargs):
        if bucket == self.bucket:
            raise OSError("injected read failure")
        return self.tx.scan(bucket, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.tx, name)


def monitor(api):
    store = fleet_store(api)
    before = api.discovery_pressure_facts(store)
    evaluator(api, store).admit()
    facts = api.discovery_pressure_facts(store)
    row = facts["row"]
    return {"before": before, "evaluated": facts["evaluated"], "waiting": row["waiting"], "capacity": row["capacity"],
            "threshold_status": row["policy"]["threshold_status"], "reason_code": row["reason_code"]}


# ---- proxy independence ------------------------------------------------------------------------------------------------------
def proxy_independence(api, ws=None):
    """R2: the stub never reaches `urlopen`, so the proxy variables change nothing: the same cases run once without and once
    with `http_proxy`/`https_proxy` set (restored afterwards) and the two results are compared."""
    def cases():
        urls = api.ResearchSources.URLS
        return {"collect": collected(api, "geeknews", Stub({urls["geeknews"]: RSS})),
                "github": collected(api, "github", Stub({urls["github"]: GITHUB_HTML})),
                "fetch_raises": collected(api, "github", Stub({urls["github"]: OSError("fixture")})),
                "held": collected(api, "github", Stub({}), intent="proactive", pressure=Holding()),
                "detail": detail(api, "https://github.com/acme/pgtool", api_responses()),
                "parse": api.ResearchSources.parse_feed(ATOM)}
    saved = {key: os.environ.get(key) for key in PROXY_ENV}
    without = cases()
    with environment(PROXY_ENV):
        seen = {key: os.environ.get(key) for key in PROXY_ENV}
        with_proxy = cases()
    restored = {key: os.environ.get(key) for key in PROXY_ENV} == saved
    return {"without_proxy": without, "proxy_variables_set": seen, "with_proxy": with_proxy, "equal": without == with_proxy,
            "environment_restored": restored}


GROUPS = (("parse", parse), ("collect", collect), ("transport", transport), ("pressure_hold", pressure_hold),
          ("proxy_independence", proxy_independence))


def run(api) -> dict:
    result, counts = {}, {}
    for name, group in GROUPS:
        result[name] = group(api)
        counts[name] = len(result[name])
    result["cases_per_group"] = counts
    return result
