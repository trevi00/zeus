"""Record completed static reads; never import or execute upstream code."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / ".runtime/absorption/sources/harness"
NAMES = {"harness:skills/diagram:001", "harness:skills/mobile:001",
         "harness:skills/ontology:001", "harness:skills/reverse:001"}
NOTES = {
    "component-diagram": "의존과 데이터 소유 경계 분리. prose →/Mermaid -->는 의도적 분리; 전체 문서 정규식과 코드·의미 정합은 별개.",
    "diagram-anchor": "소비자와 실제 앵커 선확정. 역사적 0건 공허 PASS는 현행 검사기에서 FAIL이며 렌더·의미 증거를 대체하지 않음.",
    "flowchart": "UC/FLOW 출처·구체적 분기·실패 경로. 현재 모든 FLOW 문자열 커버리지와 원문의 사용자 노출 흐름 범위 조정 필요.",
    "screen-flow": "화면·컨트롤·선 종류 및 비전환을 분리. 실제 UI와 도표 양방향 대응은 기기 검증 전 후보 자산.",
    "sequence-diagram": "UC/EP 참여자·순서·실패 우선순위, API 계약 중복 방지. 문자열 존재는 보상·금전 재시도 순서를 증명하지 않음.",
    "state-diagram": "상태와 사건 로그 구분 및 guard/side effect/terminal. boolean 일반화는 채택하지 않으며 *_state 게이트는 의미 검증 아님.",
    "flutter-layering": "세 Flutter 앱 계층·예외·registry와 버전별 Notifier/DI 차이. 원문 테스트 확인 부재, SDK·실기기 재현 자산은 아님.",
    "ontology-anchor": "다축 분류·앵커·소유권. 현재 CON 및 중복/dangling 방어 존재; 빈 JSONL과 axis-2 문자열 게이트의 의미 공백은 별도.",
    "reverse-extraction": "extracted 재추출 원칙. origin 없는 파일 보호·dirty 입력 해시·텍스트와 바이트 검증·빈 선택 범위는 현행 정적 경계.",
}
SUPPORT = {
    "ontology/graph-queries.yaml": [[1, 156]],
    "scripts/engine/graph_queries.py": [[78, 115], [383, 414]],
    "scripts/engine/reverse.py": [[1, 110], [140, 263]],
    "scripts/validators/ontology_validator.py": [[1, 170], [173, 218]],
    "pipelines/core.yaml": [[59, 112], [253, 270], [428, 445]],
    "tests/unit/test_graph_smoke.py": [[1, 145]],
    "tests/unit/test_reverse_smoke.py": [[1, 227]],
    "tests/unit/test_router_smoke.py": [[196, 215]],
    "tests/contract/test_ontology_smoke.py": [[183, 215], [295, 336]],
    "templates/_common/state-diagram.template.md": [[1, 26]],
    "templates/_common/component-diagram.template.md": [[1, 27]],
    "templates/_common/ontology-topology.template.md": [[1, 27]],
}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")


def verified(path):
    row = index[path]
    raw = (SOURCE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert sha == row["snapshot_sha256"] and blob == row["object"]
    assert len(raw) == row["bytes"]
    return {"source": "harness", "revision": manifest["revision"], "path": path,
            "git_blob": blob, "pinned_sha256": sha, "bytes": len(raw)}


manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
assert manifest["revision"] == "a3f8b3be9a0a389329de6e16a6c7db81782041a3"
index = {r["path"]: r for r in manifest["inventory"]}
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
selected = [p for p in partitions if p["partition"] in NAMES]
assert len(selected) == 4
rows = []
for partition in selected:
    for item in partition["paths"]:
        path = item["path"]
        row = verified(path)
        row.update({"partition": partition["partition"], "disposition": "semantically_reviewed",
                    "read_extent": "full_body", "semantic_summary": NOTES[Path(path).stem],
                    "review_ref": "docs/full-analysis/diagram-mobile-assets/review.md",
                    "tests_executed": [],
                    "test_limits": "정적 읽기만 수행. 원본 실행·설치·기기 조작 없음. 역사적 실측은 원문 주장; 현재 공식 자료 검증과 실제 재현 미실행.",
                    "remaining": ["실제 Claude 독립 검수", "격리 재현과 기존 테스트 실행",
                                  "현재 공식 자료·라이선스 확인", "Zeus 적응 설계와 승인"],
                    "adoption_status": "not_approved_not_incorporated"})
        rows.append(row)
assert len(rows) == len({r["path"] for r in rows}) == 9
assert sum(r["bytes"] for r in rows) == 30400
write("files.json", rows)
support = []
for path, ranges in SUPPORT.items():
    row = verified(path)
    row.update({"read_extent": "listed_line_ranges_only", "line_ranges": ranges,
                "counted_in_partition_coverage": False, "tests_executed": []})
    support.append(row)
path = "src/codex_harness/adapters/sdd.py"
support.append({"source": "zeus-working-tree", "path": path,
                "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                "line_ranges": [[73, 178]], "read_extent": "listed_line_ranges_only",
                "counted_in_partition_coverage": False, "tests_executed": []})
write("supporting-evidence.json", support)
write("checkpoint.json", {
    "source": "harness", "revision": manifest["revision"], "partitions": sorted(NAMES),
    "expected": 9, "full_body_reviewed": 9, "bytes_verified": 30400,
    "unreviewed_paths_in_partition": [], "tests_executed": [],
    "subsystem_complete": False, "adoption_approved": False,
    "claude_independent_review": "pending",
    "status": "static_review_complete_execution_and_independent_review_pending",
    "review_ref": "docs/full-analysis/diagram-mobile-assets/review.md",
    "prior_router_and_zeus_domain_trace": "docs/full-analysis/frontend-assets/supporting-evidence.json",
    "correction": "frontend-assets 화살표 충돌 주장을 DM-01에서 정정. 역사적 0건 PASS를 현행 결함으로 처리하지 않음.",
    "deferred": ["Samsung 실기기", "Device Farm SDK/MCP/live/replay 구축·인수"],
})
print(json.dumps({"reviewed": len(rows), "bytes_verified": sum(r["bytes"] for r in rows),
                  "supporting_files": len(support), "tests_executed": 0}))
