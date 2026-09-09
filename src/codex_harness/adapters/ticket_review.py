"""Self-contained, inert human review of exact packet and evidence identities."""
import html
import json

from codex_harness.domain.model import canonical


def render_ticket_review(review, packet_path):
    remaining = 256 * 1024
    def esc(value):
        return html.escape(str(value), quote=True)
    def document(ref):
        nonlocal remaining
        value = review["documents"][ref]
        budget = min(65536, remaining)
        chunks, used, clipped = [], 0, False
        for chunk in json.JSONEncoder(ensure_ascii=False, indent=2).iterencode(value):
            data = chunk.encode("utf-8")
            take = data[:budget - used]
            chunks.append(take.decode("utf-8", errors="ignore"))
            used += len(take)
            if len(data) > len(take):
                clipped = True
                break
        remaining -= used
        preview = ''.join(chunks)
        notice = '<p class="notice">미리보기 일부만 표시됨 · 전체 문서를 확인해야 합니다.</p>' if clipped else ''
        return (f'<details><summary>증거 내용 보기 · {len(canonical(value).encode("utf-8")):,} bytes</summary>'
                f'<p class="hash">{esc(ref)}</p><p>관측 시각: {esc(value["observed_at"])}</p>'
                f'{notice}<pre>{esc(preview)}</pre></details>')
    ticket, packet, policy = review["ticket"], review["packet"], review["policy"]
    environment_preview = document(packet["environment_ref"])
    content = ticket["content"]
    humans = policy["required_human_signers"]
    people = ', '.join(humans) if humans else '사람 승인 요구 없음 — 이 정책은 자동화 서명만으로 종료할 수 있습니다.'
    signers = ''.join(f'<li>{esc(p)} <span class="muted">· {esc(next(s["role"] for s in policy["signers"] if s["principal"] == p))}</span></li>'
                      for p in policy["required_signers"])
    criteria = ''.join(f'<article class="criterion"><div class="eyebrow">인수 기준 {row["index"] + 1}</div>'
        f'<h3>{esc(content["acceptance_criteria"][row["index"]])}</h3>'
        '<p class="claim">제출 결과: 통과 · 사람의 승인 여부는 확인되지 않았습니다.</p>'
        + ''.join(document(ref) for ref in row["evidence_refs"]) + '</article>' for row in packet["criteria"])
    time_message = {'expired': '서명 기한이 지났습니다. 새 패킷을 준비해야 종료할 수 있습니다.',
                    'future': '패킷 발행 시각이 미래입니다. 현재 종료 요청에 사용할 수 없습니다.',
                    'recheck_at_close': '저장된 검토 화면입니다. 종료 요청 시 시각·개정·서명을 다시 검증합니다.'}[review["time_status"]]
    scope = ''.join(f'<li>{esc(value)}</li>' for value in content['scope'])
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'">
<title>Zeus 종료 검토 · {esc(content['title'])}</title>
<style>
:root{{--bg:#f4f6f8;--ink:#182a3b;--muted:#50677b;--line:#d7e0e7;--accent:#235a75;--paper:#fff;--warn:#754600}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,"Malgun Gothic",sans-serif}}
main{{max-width:1160px;margin:auto;padding:40px 24px 80px}}header{{border-top:6px solid var(--accent);padding:28px;background:var(--paper);border-radius:8px}}
h1{{font-size:clamp(25px,4vw,38px);line-height:1.25;margin:10px 0 18px;overflow-wrap:anywhere}}h2{{font-size:23px;margin:0 0 16px}}h3{{font-size:20px;margin:8px 0}}
p{{margin:10px 0}}.eyebrow{{font-size:13px;font-weight:700;letter-spacing:.08em;color:var(--accent)}}.muted{{color:var(--muted)}}
.notice{{background:#fff3d8;color:var(--warn);border-left:4px solid #bc861f;padding:12px 16px;border-radius:4px}}
.grid{{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:20px;margin:20px 0}}section,.criterion{{background:var(--paper);padding:24px;border:1px solid var(--line);border-radius:8px;margin-top:20px;min-width:0}}
.grid section{{margin:0}}.criterion{{border-left:4px solid var(--accent)}}.hash,code{{font:13px/1.6 ui-monospace,Consolas,monospace;overflow-wrap:anywhere}}
.claim{{color:var(--muted);font-size:14px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f7;padding:16px;border-radius:6px;font:13px/1.6 ui-monospace,Consolas,monospace;max-height:480px;overflow:auto}}
summary{{cursor:pointer;font-weight:600;padding:12px 0;color:var(--accent)}}summary:focus-visible{{outline:3px solid #bc861f;outline-offset:4px}}details{{border-top:1px solid var(--line);margin-top:12px}}li{{overflow-wrap:anywhere}}dl{{margin:0}}dt{{color:var(--muted);font-size:13px;margin-top:12px}}dd{{margin:2px 0;overflow-wrap:anywhere}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
@media(max-width:760px){{main{{padding:20px 12px 40px}}header,section,.criterion{{padding:18px}}h2{{font-size:21px}}}}
@media print{{body{{background:#fff}}main{{padding:0}}pre{{max-height:none}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div class="eyebrow">ZEUS · 종료 전 검토</div><h1>{esc(content['title'])}</h1>
<p>이 화면을 열거나 읽어도 승인·종료되지 않습니다. 기준 원문과 실제 관측 내용을 비교한 뒤 원본 패킷을 서명하세요.</p>
<p class="notice">{esc(time_message)}</p>
<p class="hash">{esc(ticket['id'])} · 개정 {packet['revision']} · 작업 주기 {packet['sequence']}</p></header>
<div class="grid"><section><h2>무엇을 해결했는가</h2><p>{esc(content['problem'])}</p>
<h3>영향</h3><p>{esc(content['impact'])}</p><h3>범위</h3><ul>{scope}</ul>
<h3>종료 요청 사유</h3><p>{esc(packet['reason'])}</p></section>
<section><h2>필요한 승인</h2><p class="notice">{esc(people)}</p><ul>{signers}</ul>
<p class="muted">서명 검증은 이 화면에서 실행하지 않습니다. 등록된 키의 권한과 실제 사람의 현장 확인은 별개입니다.</p>
<dl><dt>발행</dt><dd>{esc(packet['issued_at'])}</dd><dt>서명 기한</dt><dd>{esc(packet['expires_at'])}</dd>
<dt>해결 커밋</dt><dd class="hash">{esc(packet['solution_commit'])}</dd></dl></section></div>
<section><h2>인수 기준과 증거 · {len(packet['criteria'])}개</h2><p class="muted">‘통과’는 제출된 관측 결과입니다. 원문 기준을 충족하는지 검토자의 판단이 필요합니다.</p>{criteria}</section>
<section><h2>환경 확인</h2>{environment_preview}</section>
<section><h2>되돌리기</h2><p>{esc(content['rollback'])}</p></section>
<section><h2>서명할 원본 식별</h2><p>HTML이나 화면 복사본이 아닌 원본 JSON 파일을 서명하세요.</p>
<dl><dt>원본 파일</dt><dd class="hash">{esc(packet_path)}</dd><dt>원본 SHA-256 · {len(canonical(packet).encode('utf-8')):,} bytes</dt>
<dd class="hash">{esc(review['packet_ref'])}</dd><dt>신뢰 정책 커밋</dt><dd class="hash">{esc(packet['policy_commit'])}</dd>
<dt>정책 해시</dt><dd class="hash">{esc(packet['policy_hash'])}</dd></dl>
<details><summary>정확한 서명 대상 JSON 보기</summary><pre>{esc(canonical(packet))}</pre></details></section>
</main></body></html>'''
