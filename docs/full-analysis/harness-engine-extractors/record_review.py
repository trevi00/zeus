"""Create static-review receipts; upstream source is never imported or executed."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/harness"
REVISION = "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
PARTITION = "harness:scripts/engine/extractors:001"
REF = "docs/full-analysis/harness-engine-extractors/review.md"
NOTES = {
    "doc_classifier": ("X07", "파일명/앞 4000자 힌트의 단일 후보. 정렬 동점·읽기 실패/미분류 관측 공백; 보고 전용이며 정확도 승인 아님.",
                       ["tests/integration/test_scaffold_smoke.py", "tests/contract/test_artifact_type_registry_contract.py"]),
    "intent_seed": ("X07", "README/docs 인용 후보 최대40·bullet160자, seed 재작성. 요구/사람 oracle 아님; 절단·출처 진위·untrusted 경계 별도.",
                    ["tests/integration/test_scaffold_smoke.py"]),
    "python_api": ("X03", "특정 root/main/routes/router 이름·공통 include prefix 합성. 순번 EP·고정 confidence·응답 타입명은 실제 API 계약과 다름.",
                   ["tests/unit/test_reverse_smoke.py", "tests/contract/test_extractor_canary_contract.py"]),
    "python_conceptual": ("X04", "모든 py 클래스의 tablename/Enum/FK 문자열 관측. models.py 모집단과 비대칭, CON 순번·관계 span/어휘값 제한.",
                          ["tests/integration/test_scaffold_smoke.py", "tests/contract/test_extractor_canary_contract.py"]),
    "python_convention": ("X04", "package·snake 비율·도구 존재·tests 배치4축. 규범 아님; 고정 entries와 spans 계수는 항목별 파일행 증거와 다름.",
                          ["tests/integration/test_scaffold_smoke.py"]),
    "python_flows": ("X05", "AST 방문순 call tail 이름 최대8 중복 제거. runtime 제어흐름·분기·횟수·사용자 여정·GWT oracle 아님.",
                     ["tests/integration/test_scaffold_smoke.py", "tests/contract/test_extractor_canary_contract.py"]),
    "python_imports": ("X06", "하위 package 의존·대표 import 증거. relative/alias/직속파일/parse-error 경계, 0edge 출력은 현행 acyclic에서 FAIL.",
                       ["tests/unit/test_reverse_smoke.py", "tests/contract/test_extractor_canary_contract.py"]),
    "python_models": ("X04", "models.py Mapped 관측. scalar1:1·schema FK 첫 조각·nullable 비True 해석·고정 alembic실측문장·ENT/TBL 소비 비대칭.",
                      ["tests/unit/test_reverse_smoke.py", "tests/contract/test_extractor_canary_contract.py"]),
    "tshelp": ("X03", "tree-sitter Python parse/text/call/string helper. has_error 강제·실행 문자열 평가 없음, helper는 구조 관측 원자.",
               ["tests/unit/test_reverse_smoke.py", "tests/integration/test_scaffold_smoke.py"]),
    "typescript_imports": ("X06", "TS/TSX 지연문법·부재와 unreadable 구분·parse메타. root/scanned0·alias·slug·package-cycle·기본 acyclic 미배선.", []),
}
SUPPORT = {
    "scripts/engine/reverse.py": [[1, 152], [155, 181], [195, 259]],
    "pipelines/reverse-onboarding.yaml": [[1, 93]],
    "scripts/validators/intent_doc_floor.py": [[1, 98]],
    "tests/unit/test_reverse_smoke.py": [[1, 227]],
    "tests/integration/test_scaffold_smoke.py": [[35, 76], [117, 177]],
    "tests/contract/test_extractor_canary_contract.py": [[1, 170]],
    "tests/contract/test_artifact_type_registry_contract.py": [[382, 391]],
    "requirements.txt": [[1, 13]],
    "scripts/cli/extractor_canary_cmd.py": [[43, 267]],
    "scripts/cli/autoheart_cmd.py": [[768, 817], [850, 921]],
    "ontology/graph-queries.yaml": [[46, 80], [114, 126], [152, 156]],
    "scripts/engine/graph_queries.py": [[78, 115], [358, 414]],
    "scripts/engine/mirror.py": [[31, 35], [50, 79]],
    "scripts/handlers/pre_tool/extracted_guard.py": [[1, 38]],
    "scripts/handlers/registry.py": [[42, 57]],
    ".claude/commands/onboard.md": [[1, 16]],
    "scripts/engine/checks.py": [[91, 144]],
}


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def verified(path):
    entry = inventory[path]
    raw = (SOURCE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert (sha, blob, len(raw)) == (entry["snapshot_sha256"], entry["object"], entry["bytes"])
    return {"source": "harness", "revision": REVISION, "path": path,
            "pinned_sha256": sha, "git_blob": blob, "bytes": len(raw)}


manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
assert manifest["revision"] == REVISION
inventory = {r["path"]: r for r in manifest["inventory"]}
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
partition = next(p for p in partitions if p["partition"] == PARTITION)
rows = []
for item in partition["paths"]:
    path = item["path"]
    row = verified(path)
    section, note, tests = NOTES[Path(path).stem]
    row.update({"partition": PARTITION, "disposition": "semantically_reviewed",
                "read_extent": "full_body", "semantic_summary": note,
                "review_ref": REF, "finding_sections": [section, "X01", "X02"],
                "caller_or_dependency_trace": ["scripts/engine/reverse.py"] if Path(path).stem != "tshelp"
                else ["scripts/engine/extractors/python_api.py", "scripts/engine/extractors/python_models.py",
                      "scripts/engine/extractors/python_flows.py", "scripts/engine/extractors/python_conceptual.py",
                      "scripts/engine/extractors/python_convention.py"],
                "tests_read_in_part": tests, "tests_executed": [],
                "test_limits": "원본 실행·설치·probe·기기 조작 0건. 합성 소스/본문 카운트/분기 테스트는 실제 앱 또는 인수 증거가 아님. TS 직접명 검색0건은 전체 테스트 부재 증명 아님.",
                "remaining": ["실제 Claude 독립 교차 검수", "현재 공식 자료와 라이선스 확인",
                              "격리된 기존 테스트와 플랫폼/semantic 경계 재현",
                              "전체 consumer 추적 및 Zeus 적응", "사람 oracle와 실제 실행 증거 기반 인수"],
                "adoption_status": "not_approved_not_incorporated"})
    rows.append(row)
assert len(rows) == len({r["path"] for r in rows}) == 10
assert sum(r["bytes"] for r in rows) == partition["bytes"] == 47850
write("files.json", rows)
support = []
for path, ranges in SUPPORT.items():
    row = verified(path)
    n = len((SOURCE / "pinned" / path).read_text(encoding="utf-8").splitlines())
    assert all(1 <= a <= z <= n for a, z in ranges), (path, n)
    row.update({"line_ranges": ranges, "read_extent": "listed_line_ranges_only",
                "counted_in_partition_coverage": False, "tests_executed": []})
    support.append(row)
path = "src/codex_harness/domain/sdd.py"
raw = (ROOT / path).read_bytes()
support.append({"source": "zeus-working-tree", "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(), "line_ranges": [[169, 202]],
                "read_extent": "listed_line_ranges_only", "counted_in_partition_coverage": False,
                "tests_executed": []})
write("supporting-evidence.json", support)
write("checkpoint.json", {
    "source": "harness", "revision": REVISION, "partitions": [PARTITION],
    "scope_sha256": partition["scope_sha256"], "expected": 10, "full_body_reviewed": 10,
    "bytes_verified": 47850, "unreviewed_paths_in_partition": [],
    "tests_executed": [], "upstream_execution_count": 0,
    "blocked_probe_retried_or_bypassed": False, "subsystem_complete": False,
    "adoption_approved": False, "claude_independent_review": "pending",
    "status": "static_review_complete_execution_and_independent_review_pending", "review_ref": REF,
    "searches": [{"scope": ["tests", "pipelines", "ontology/graph-queries.yaml"],
                  "source": "harness-pinned", "pattern": "typescript_imports|component-diagram-typescript|TypeScriptUnreadable",
                  "matches": 0, "limit": "Exact text search only; indirect tests not ruled out"}],
    "search_limits": "config/handlers.yaml 추정 경로 부재. rg --files로 실제 scripts/handlers/registry.py 확인 후 직접 읽음. supporting 구간만 조회했으며 전체 consumer 감사 아님.",
    "deferred": ["Samsung 실기기", "Device Farm SDK/MCP/Replay 구축·인수", "Astra→Sol→Terra 실행 자격 증명"],
})
print(json.dumps({"reviewed": len(rows), "bytes_verified": sum(r["bytes"] for r in rows),
                  "supporting_files": len(support), "upstream_executions": 0}))
