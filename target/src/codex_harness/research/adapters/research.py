"""Research feed sources (INV-DISCOVERY-PRESSURE-001): the bounded fetch of the GitHub trending page and the GeekNews feed, the intent and pressure gate in front of a proactive fetch, the parsers and the GitHub repository detail.

Layer: adapters
Context: research
Owns: `ResearchSources`: the stdlib `urllib` fetch, the intent validation and pressure hold, the feed parsers, the artifact put and the repository detail read
Does not own: the pressure evaluator (injected as `pressure`), the artifact store (injected as `artifacts`), the pressure policy (research.domain.discovery_pressure)
Entry points: ResearchSources
Contracts: INV-DISCOVERY-PRESSURE-001

Moved from M7 `adapters/research.py` (SOURCE e38aa722) through one named rule (DESIGN-s8 §6 V11, A/evidence/rebuild/s8/research-sources-move/transcribe.py): R-s0 (each imported name from the target home of the module that defines it); every body is M7's. The M7 module has no docstring: this header is the §3.2 one.
"""
from __future__ import annotations

import base64
import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow
from codex_harness.research.domain.discovery_pressure import (
    ALLOW,
    HOLD,
    PROACTIVE,
    DiscoveryPaused,
    unrecorded_hold,
    validate_intent,
)


class ResearchSources:
    URLS = {"github": "https://github.com/trending", "geeknews": "https://news.hada.io/rss/news"}

    def __init__(self, artifacts, pressure=None):
        # INV-DISCOVERY-PRESSURE-001: the control store's pressure evaluator; None holds every PROACTIVE fetch
        # (fail-closed) and never touches the exempt intents.
        self.artifacts, self.pressure = artifacts, pressure

    def fetch(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": "codex-harness/0.1 (research)"})
        with urlopen(request, timeout=30) as response:
            data = response.read(2_000_001)
            require(len(data) <= 2_000_000, "Research response exceeds size budget")
            return data.decode("utf-8", errors="replace")

    def collect(self, source: str, *, intent: str) -> dict:
        """Fetch one feed. The caller states WHY (INV-DISCOVERY-PRESSURE-001): a missing or unknown intent refuses
        before any IO; a proactive fetch starts only when the pressure evaluator allows it now, and a held one
        raises `DiscoveryPaused` (never a network error or an empty feed). Exempt intents fetch normally."""
        validate_intent(intent)
        require(source in self.URLS, "Unknown research source")
        if intent == PROACTIVE:
            # The policy boundary covers the evaluation only: a failing evaluator is an unknown-pressure hold, while
            # the fetch below keeps its own source/network failures.
            try:
                decision = (self.pressure.admit() if self.pressure is not None
                            else {"decision": HOLD, "reason_code": "pressure_unavailable"})
            except Exception:
                decision = unrecorded_hold("evaluation_failed")
            if not isinstance(decision, dict) or decision.get("decision") != ALLOW:
                raise DiscoveryPaused(decision if isinstance(decision, dict) else unrecorded_hold("evaluation_invalid"))
        url = self.URLS[source]
        body = self.fetch(url)
        receipt = self.artifacts.put(body, url)
        items = self.parse_github(body) if source == "github" else self.parse_feed(body)
        require(bool(items), "Research source returned no parseable entries")
        return {"source": url, "fetched_at": utcnow(), "artifact": receipt["ref"], "items": items[:15]}

    @staticmethod
    def parse_github(body: str) -> list[dict]:
        items = []
        for article in re.findall(r"<article\b.*?</article>", body, re.S):
            header = re.search(r"<h2\b.*?</h2>", article, re.S)
            match = re.search(r'href="(/[^"?#]+/[^"?#]+)"', header[0]) if header else None
            if match:
                description = re.search(r"<p\b[^>]*>(.*?)</p>", article, re.S)
                items.append({"url": "https://github.com" + match[1], "title": match[1][1:],
                              "summary": unescape(re.sub(r"<[^>]+>", "", description[1])).strip()
                              if description else ""})
        return items

    @staticmethod
    def parse_feed(body: str) -> list[dict]:
        root = ET.fromstring(body)
        items = []
        for node in root.findall(".//item"):
            items.append({"url": node.findtext("link", ""), "title": node.findtext("title", ""),
                          "summary": re.sub(r"<[^>]+>", "", node.findtext("description", ""))[:1500]})
        for node in root.findall("{http://www.w3.org/2005/Atom}entry"):
            prefix = "{http://www.w3.org/2005/Atom}"
            link = node.find(prefix + "link")
            items.append({"url": link.get("href", "") if link is not None else "",
                          "title": node.findtext(prefix + "title", ""),
                          "summary": re.sub(r"<[^>]+>", "", node.findtext(prefix + "content", ""))[:1500]})
        return [item for item in items if item["url"].startswith("https://")]

    def github_detail(self, url: str) -> dict:
        require(bool(re.fullmatch(r"https://github.com/[\w.-]+/[\w.-]+", url)), "Invalid repository URL")
        api = "https://api.github.com/repos/" + url.removeprefix("https://github.com/")
        metadata = json.loads(self.fetch(api))
        commit = json.loads(self.fetch(api + "/commits/" + quote(metadata["default_branch"], safe="")))["sha"]
        require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "Invalid source revision")
        readme = json.loads(self.fetch(api + "/readme?ref=" + commit))
        require(readme.get("encoding") == "base64", "Unsupported README encoding")
        text = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")
        receipt = self.artifacts.put(text, url + "/blob/" + commit + "/" + readme["path"])
        return {"url": url, "description": metadata.get("description"),
                "license": (metadata.get("license") or {}).get("spdx_id"),
                "default_branch": metadata["default_branch"], "archived": metadata["archived"],
                "pushed_at": metadata["pushed_at"], "fetched_at": utcnow(),
                "revision": commit, "readme_ref": receipt["ref"], "readme_excerpt": text.encode("utf-8")[:10000].decode("utf-8", errors="ignore")}
