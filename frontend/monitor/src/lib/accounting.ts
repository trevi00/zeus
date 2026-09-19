import type { Tone } from "./tones"

/**
 * One shared reading of the usage-accounting contract (`domain/usage_policy.py`,
 * local-operations-desk-001 SPEC Part A), used by the live 팀 작업 view and by the pinned report so
 * both say the same thing about the same capture.
 *
 * The producer (`domain/fleet.py` `projection`) puts two statements of the same fact on the
 * `urn:zeus:fleet-status:1` wire:
 * - `accounting_mode`: the derived mode string, `finite` or `subscription`;
 * - `budget.mode`: present only in the canonical subscription form. The legacy finite form is
 *   `{per_host, total}` with no `mode` key at all, and that absence is the finite statement.
 *
 * Reading rules, in order:
 * - both statements present and equal -> that mode;
 * - exactly one statement present -> that one explicit mode, whichever field carries it. A single
 *   explicit statement is the only statement; the absent field is an older or newer wire shape,
 *   not a second, contradicting claim, so `subscription` stated once is read as subscription;
 * - neither present -> `finite`, the legacy shape; this is the contract, not a guess;
 * - two present statements that disagree, or a present value outside the contract (wrong type,
 *   `null`, an unknown string) -> `unknown`: never silently finite, never claimed as subscription.
 *
 * In subscription mode `per_host`/`total` stay on the wire as retained migration metadata. They are
 * not ceilings, not a provider allowance, not free usage, not remaining money and not remaining
 * calls; every call is still reserved and recorded. In finite mode they are the true ceilings, and
 * the machine still applies them at start time (CallBudget), not here.
 *
 * Nothing in this module reads a snapshot, a clock or a request, so a captured reading stays fixed.
 */
export const FINITE = "finite"
export const SUBSCRIPTION = "subscription"

export type AccountingMode = "finite" | "subscription" | "unknown"
/** How the mode above was reached; kept so the UI can say why, and JSON readers can audit it. */
export type AccountingBasis = "agreed" | "budget_mode" | "top_level" | "legacy_absent" | "conflict" | "malformed"

export type Accounting = {
  mode: AccountingMode
  basis: AccountingBasis
  /** The raw wire statements, kept as metadata; `undefined` means the field was absent. */
  declared: { accounting_mode: unknown; budget_mode: unknown }
  /** `true` only in finite mode, `false` in subscription, `null` when the mode is unknown. */
  ceiling_applies: boolean | null
  /** Short badge text for the mode itself. */
  label: string
  /** Why this reading holds, with the wire statements it came from. */
  detail: string
  /** What the two numbers are in this mode, wherever they are shown. */
  numbers_label: string
  numbers_note: string
}

/** Title shared by the live control strip and the report control strip. */
export const ACCOUNTING_TITLE = "호출 회계"

type Declared = "finite" | "subscription" | "absent" | "malformed"

function declaredMode(value: unknown): Declared {
  if (value === undefined) return "absent"
  if (value === FINITE || value === SUBSCRIPTION) return value
  return "malformed"
}

/** The raw statement as written on the wire, for the detail line; never reinterpreted. */
function describe(value: unknown): string {
  if (value === undefined) return "없음"
  if (value === null) return "null"
  if (typeof value === "string") return `"${value}"`
  return `${typeof value} 값`
}

const READINGS: Record<"finite" | "subscription", Pick<Accounting, "label" | "numbers_label" | "numbers_note">> = {
  finite: {
    label: "유한 호출 상한",
    numbers_label: "호출 수 상한 (호스트당 / 전체)",
    numbers_note: "선언된 호출 수 상한 · 남은 호출·금액·실제 지출 장부 아님 · 실제 적용은 실행 직전 CallBudget",
  },
  subscription: {
    label: "구독 사용량 기록",
    numbers_label: "이관 메타데이터 (호스트당 / 전체)",
    numbers_note: "호출 수 상한 미적용 · 보존된 이관 메타데이터일 뿐 현재 상한 아님 · 제공자 허용량·무료 사용량·남은 호출·남은 금액 아님 · 모든 호출은 예약·기록됨",
  },
}

const UNKNOWN_READING: Pick<Accounting, "label" | "numbers_label" | "numbers_note"> = {
  label: "회계 방식 알 수 없음",
  numbers_label: "기록된 수치 (호스트당 / 전체)",
  numbers_note: "회계 방식을 확정하지 못해 이 수치가 상한인지 알 수 없음 · 유한 상한으로도 구독 기록으로도 해석하지 않음",
}

/**
 * Interpret the two wire statements. Pass the raw values: `undefined` for an absent field.
 * A value this function cannot place is never downgraded to the legacy finite reading.
 */
export function interpretAccounting(topLevelMode: unknown, budgetMode: unknown): Accounting {
  const declared = { accounting_mode: topLevelMode, budget_mode: budgetMode }
  const wire = `wire: accounting_mode ${describe(topLevelMode)} · budget.mode ${describe(budgetMode)}`
  const top = declaredMode(topLevelMode)
  const budget = declaredMode(budgetMode)

  if (top === "malformed" || budget === "malformed") {
    return { ...UNKNOWN_READING, mode: "unknown", basis: "malformed", declared, ceiling_applies: null,
      detail: `계약(finite·subscription)에 없는 회계 방식 값 · ${wire}` }
  }
  if (top === "absent" && budget === "absent") {
    // Neither field states a mode: the legacy finite shape, which is the contract, not a guess.
    return { ...READINGS.finite, mode: FINITE, basis: "legacy_absent", declared, ceiling_applies: true,
      detail: `두 표기가 모두 없음 · 이전 계약의 유한 형식(mode 키 없음)으로 읽음 · ${wire}` }
  }
  // Exactly one explicit statement is the only statement: the absent field is a different wire
  // shape, not a contradicting claim, so it is never used to outvote what was actually declared.
  if (top === "absent" || budget === "absent") {
    const stated = (top === "absent" ? budget : top) as "finite" | "subscription"
    const basis: AccountingBasis = top === "absent" ? "budget_mode" : "top_level"
    return { ...READINGS[stated], mode: stated, basis, declared, ceiling_applies: stated === FINITE,
      detail: `${top === "absent" ? "budget.mode" : "accounting_mode"} 한쪽만 기록됨(다른 표기는 없음) · 기록된 표기를 그대로 읽음 · ${wire}` }
  }
  if (top !== budget) {
    return { ...UNKNOWN_READING, mode: "unknown", basis: "conflict", declared, ceiling_applies: null,
      detail: `두 표기가 서로 다름 · ${wire} · 한쪽을 임의로 채택하지 않음` }
  }
  return { ...READINGS[top], mode: top, basis: "agreed", declared, ceiling_applies: top === FINITE,
    detail: `두 표기가 일치 · ${wire}` }
}

/**
 * One wording for the control strips. `numbers` is the already formatted `per_host / total` pair;
 * `value === null` means the screen must render its own 확인 불가 marker instead of a number.
 */
export function accountingDisplay(accounting: Accounting, numbers: string): { value: string | null; note: string } {
  if (accounting.mode === "finite") {
    return { value: numbers, note: `${accounting.numbers_label} · ${accounting.numbers_note}` }
  }
  if (accounting.mode === "subscription") {
    return { value: accounting.label, note: `${accounting.numbers_label} ${numbers} · ${accounting.numbers_note}` }
  }
  return { value: null, note: `${accounting.numbers_label} ${numbers} · ${accounting.numbers_note} · ${accounting.detail}` }
}

export function accountingTone(accounting: Accounting): Tone {
  return accounting.mode === "unknown" ? "unknown" : "neutral"
}
