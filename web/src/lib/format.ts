import type { Indicator, Status, ValueRow } from "./types";

export const STATUS_LABEL: Record<Status, string> = {
  observed: "",
  estimated: "推計値",
  derived: "算出値",
  missing: "データなし",
  suppressed: "秘匿（公表されていません）",
  withheld: "非表示（対象人数が少ないため）",
  not_applicable: "対象外",
};

export function formatNumber(value: number, digits: number): string {
  return new Intl.NumberFormat("ja-JP", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** 凡例の目盛り用の短い表記（1.2万・350万・1.5億）。1万未満はそのまま。 */
export function compactNumber(value: number, digits: number): string {
  const a = Math.abs(value);
  const [div, unit] = a >= 1e8 ? [1e8, "億"] : a >= 1e4 ? [1e4, "万"] : [1, ""];
  if (!unit) return formatNumber(value, digits);
  const x = value / div;
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits: Math.abs(x) < 10 ? 1 : 0 }).format(x) + unit;
}

/** 値と単位。値がない場合はゼロではなく理由を返す。 */
export function formatValue(row: Pick<ValueRow, "value" | "status"> | undefined, ind: Indicator): string {
  if (!row) return "データなし";
  if (row.value === null) return STATUS_LABEL[row.status] || "データなし";
  // 増減率は増加に「+」を付ける（減少は「−」が付く）
  const sign = ind.kind === "change" && row.value > 0 ? "+" : "";
  return `${sign}${formatNumber(row.value, ind.digits)}${ind.unit === "%" ? "%" : ` ${ind.unit}`}`;
}

/** 率の内訳（例: 1,234 / 5,678）。 */
export function formatFraction(row: ValueRow | undefined, ind: Indicator): string | null {
  if (!row || row.value === null || row.numerator === undefined || row.denominator === undefined) {
    return null;
  }
  if (ind.kind === "ratio") {
    const [nu, du] = ind.fraction_units ?? ["人", "人"];
    // 「〜の割合」は全体のうちの数として書く（例: 1,000 人のうち 250 人）
    if (nu === du && ind.unit === "%" && !!ind.name?.includes("割合")) {
      return `${formatNumber(row.denominator, 0)} ${du}のうち ${formatNumber(row.numerator, 0)} ${nu}`;
    }
    return `${formatNumber(row.numerator, 0)} ${nu} ÷ ${formatNumber(row.denominator, 0)} ${du}`;
  }
  if (ind.kind === "change") {
    const sign = row.numerator > 0 ? "+" : row.numerator < 0 ? "−" : "±";
    return `前回 ${formatNumber(row.denominator, 0)} 人から ${sign}${formatNumber(Math.abs(row.numerator), 0)} 人`;
  }
  if (ind.kind === "density") {
    return `人口 ${formatNumber(row.numerator, 0)} 人 ÷ 面積 ${formatNumber(row.denominator, 2)} km²`;
  }
  return null;
}

// 値の求め方を短く書いたもの（地域の情報で、計算の内訳の後ろに添える）。書き換えた注記は note を出さない
const BASIS_NOTES: Record<string, string> = {
  "市区町村の分子・分母を合計して計算": "市区町村の数を合計して計算",
  "市区町村の値の合計": "市区町村の値の合計",
};
export function formatBasis(row: Pick<ValueRow, "value" | "status" | "note"> | undefined, hasFraction: boolean): { text: string | null; note: string | null } {
  if (!row || row.value === null) return { text: null, note: row?.note ?? null };
  const fromNote = row.note ? BASIS_NOTES[row.note] : undefined;
  const text = fromNote ?? (row.status === "estimated" ? "推計値"
    : row.status === "derived" && !hasFraction ? "公表された数から計算" : null);
  return { text, note: fromNote ? null : row.note ?? null };
}

/** 値の大きい順の順位（同値は同順位）。値がない地域は順位に含めない。 */
export function rankOf(rows: ValueRow[], entityId: string): { rank: number; total: number } | null {
  const values = rows.filter((r) => r.value !== null).map((r) => r.value as number);
  const target = rows.find((r) => r.entity_id === entityId);
  if (!target || target.value === null) return null;
  const rank = values.filter((v) => v > (target.value as number)).length + 1;
  return { rank, total: values.length };
}

/** 順位を出す範囲として意味があるときだけ数える（すべて同じ値なら出さない。例: 県内がすべて0%） */
export function rankIfVaried(rows: ValueRow[], entityId: string): { rank: number; total: number } | null {
  return new Set(rows.map((r) => r.value).filter((v) => v !== null)).size > 1 ? rankOf(rows, entityId) : null;
}
