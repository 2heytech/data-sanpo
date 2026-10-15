import { formatNumber, formatValue } from "./format";
import type { Indicator, ValueRow } from "./types";

/**
 * 地域ページ「データで見る〇〇」の考察。決まった条件に当てはまるときだけ、数字と推測の文を出す。
 * 推測は「〜と思われます」「〜かもしれません」で書き、断定しない。数字はすべて公開しているデータの値で、
 * 新しい推計はしない。値がない指標は使わない（0 として扱わない）。
 */
export interface InsightData {
  indicator(id: string): Indicator | undefined;
  /** 指標の市区町村の値（全国）。period を省くと既定の時点 */
  rows(id: string, period?: string): ValueRow[];
}

interface Stat {
  ind: Indicator;
  label: string;
  value: number;
  text: string;
  /** 全国の市区町村の中の位置（0〜1）。top は大きい方から、bottom は小さい方から。1つの都道府県だけの指標は null */
  top: number | null;
  bottom: number | null;
}

/** 考察の数の上限（多すぎると読まれないため） */
const MAX_INSIGHTS = 4;

export function areaInsights(muniId: string, data: InsightData): string[] {
  const stat = (id: string, period?: string): Stat | null => {
    const ind = data.indicator(id);
    if (!ind) return null;
    const p = period ?? ind.default_period;
    const rows = data.rows(id, p);
    const row = rows.find((r) => r.entity_id === muniId);
    if (!row || row.value === null) return null;
    const values = rows.map((r) => r.value).filter((v): v is number => v !== null);
    const nationwide = new Set(rows.filter((r) => r.value !== null).map((r) => r.entity_id.slice(5, 7))).size > 1;
    const v = row.value;
    return {
      ind, value: v, text: formatValue(row, ind),
      label: ind.periods.find((x) => x.period === p)?.label ?? "",
      top: nationwide ? (values.filter((x) => x > v).length + 1) / values.length : null,
      bottom: nationwide ? (values.filter((x) => x < v).length + 1) / values.length : null,
    };
  };
  const isTop = (s: Stat | null, share: number): s is Stat => !!s && s.top !== null && s.top <= share;
  const isBottom = (s: Stat | null, share: number): s is Stat => !!s && s.bottom !== null && s.bottom <= share;

  const out: string[] = [];
  for (const rule of [foreignGap, daytime, populationChange, ageStructure, singles, commute, industry, shopping,
    furusato, income, vacancy]) {
    const line = rule();
    if (line) out.push(line);
    if (out.length >= MAX_INSIGHTS) break;
  }
  return out;

  /** 外国人: 国勢調査（10月1日）と住民基本台帳（1月1日）の差。数え方の違いに加え、季節で住む人が入れ替わる地域で大きく開く */
  function foreignGap(): string | null {
    const census = data.indicator("foreign_resident_share");
    const juki = data.indicator("foreign_residents_share");
    if (!census || !juki) return null;
    // 国勢調査の最新の回と、その後6か月以内の住民基本台帳の時点を比べる
    const cPeriods = census.periods.map((p) => p.period).sort().reverse();
    for (const cp of cPeriods) {
      const c = stat("foreign_resident_share", cp);
      if (!c) continue;
      const limit = new Date(cp);
      limit.setMonth(limit.getMonth() + 6);
      const jp = juki.periods.map((p) => p.period).sort().find((p) => p > cp && new Date(p) <= limit);
      const j = jp ? stat("foreign_residents_share", jp) : null;
      if (!j) return null;
      const cCount = data.rows("census_foreign_population", cp).find((r) => r.entity_id === muniId)?.value ?? null;
      const jCount = data.rows("foreign_residents", jp!).find((r) => r.entity_id === muniId)?.value ?? null;
      // 人数が少ない地域は数人の違いで割合が大きく動くので見ない
      if (cCount === null || jCount === null || Math.max(cCount, jCount) < 30) return null;
      const head = `外国人住民の割合は、住民基本台帳（${j.label}）では${j.text}、国勢調査（${c.label}）では${c.text}です。`;
      if (j.value >= c.value * 1.5 && j.value - c.value >= 2) {
        return head + "1月の時点の方がかなり多く、冬の観光や農作業など、季節的に働きに来る外国人が多いのかもしれません" +
          "（2つの統計は調べ方も違います）。";
      }
      if (c.value >= j.value * 1.5 && c.value - j.value >= 2) {
        return head + "10月の時点の方がかなり多く、収穫や工事など、時期によって働きに来る外国人が入れ替わっているのかもしれません" +
          "（2つの統計は調べ方も違います）。";
      }
      return null;
    }
    return null;
  }

  function daytime(): string | null {
    const s = stat("daytime_night_ratio");
    if (!s) return null;
    const ratio = s.value / 100;
    if (s.value >= 130) {
      return `昼間の人口は住んでいる人の${formatNumber(ratio, 1)}倍です（${s.label}）。周りから通勤・通学で人が集まる、職場や学校の多いまちと思われます。`;
    }
    if (s.value <= 85) {
      return `昼間の人口は住んでいる人の${formatNumber(s.value, 0)}%です（${s.label}）。周りのまちへ通勤・通学する人が多い、住宅地としての性格が強いのかもしれません。`;
    }
    return null;
  }

  function populationChange(): string | null {
    const s = stat("population_change_rate");
    if (isTop(s, 0.1) && s.value > 0) {
      return `人口は5年前から${s.text.replace(/^\+/, "")}増えていて（${s.label}）、全国の市区町村の中でも増え方が大きい方です。住宅の開発などで移り住む人が多いのかもしれません。`;
    }
    if (isBottom(s, 0.1) && s.value < 0) {
      return `人口は5年前から${s.text.replace(/^[−-]/, "")}減っていて（${s.label}）、全国の市区町村の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。`;
    }
    return null;
  }

  function ageStructure(): string | null {
    const aged = stat("aged_65_plus_share");
    const kids = stat("children_0_14_share");
    if (isTop(aged, 0.1) && isBottom(kids, 0.25)) {
      return `65歳以上の人が${aged.text}、15歳未満の子どもが${kids!.text}です（${aged.label}）。全国の中でも高齢化が進んだ地域と思われます。`;
    }
    if (isTop(kids, 0.1)) {
      return `15歳未満の子どもの割合が${kids.text}と全国でも高い方です（${kids.label}）。子育て中の世帯が多く住んでいると思われます。`;
    }
    return null;
  }

  function singles(): string | null {
    const single = stat("single_person_household_share");
    if (!isTop(single, 0.1)) return null;
    const students = stat("university_student_share");
    // 学生のまちと読むのは、大学生・大学院生が人口の5%以上いるときだけ（都心の区は割合の順位だけなら上位に入る）
    if (isTop(single, 0.05) && isTop(students, 0.05) && students.value >= 5) {
      return `一人暮らしの世帯が${single.text}、大学生・大学院生が人口の${students.text}で、どちらも全国で高い方です（${single.label}）。学生の一人暮らしが多いまちなのかもしれません。`;
    }
    // 高齢化が進んだ地域の一人暮らしは、働く人より高齢の人と考える方が自然
    if (isTop(stat("aged_65_plus_share"), 0.1)) {
      return `一人暮らしの世帯が${single.text}と全国でも高い方です（${single.label}）。高齢の人の一人暮らしが多いと思われます。`;
    }
    return `一人暮らしの世帯が${single.text}と全国でも高い方です（${single.label}）。単身で働く人や学生などが多く住んでいると思われます。`;
  }

  function commute(): string | null {
    const rail = stat("commute_rail_share");
    // 通勤圏と読むのは、昼間に人が出ていく（昼夜間人口比率が100%未満の）地域だけ。都心は鉄道で人が集まる側なので除く
    const day = stat("daytime_night_ratio");
    if (isTop(rail, 0.1) && day && day.value < 100) {
      return `通勤・通学に鉄道を使う人が${rail.text}と多く（${rail.label}）、大きな都市への通勤圏にあると思われます。`;
    }
    const car = stat("commute_car_share");
    if (isTop(car, 0.1)) {
      return `通勤・通学に自家用車を使う人が${car.text}と多く（${car.label}）、車が欠かせない暮らしと思われます。`;
    }
    return null;
  }

  function industry(): string | null {
    const mfg = stat("employees_manufacturing_share");
    if (isTop(mfg, 0.1)) {
      return `働く人のうち製造業が${mfg.text}を占めていて（${mfg.label}）、工場の多いものづくりのまちと思われます。`;
    }
    const agri = stat("employees_agriculture_share");
    if (isTop(agri, 0.1)) {
      return `働く人のうち農林漁業が${agri.text}を占めていて（${agri.label}）、農業や漁業が暮らしを支えていると思われます。`;
    }
    return null;
  }

  function shopping(): string | null {
    const s = stat("retail_sales_per_capita");
    if (!isTop(s, 0.05)) return null;
    return `住民1人あたりの小売業の販売額が${s.text}と全国でも大きい方です（${s.label}）。周りから買い物に来る人が多い、商業の中心なのかもしれません。`;
  }

  function furusato(): string | null {
    const s = stat("furusato_amount_per_capita");
    if (!isTop(s, 0.03)) return null;
    return `ふるさと納税の受入額が住民1人あたり${s.text}と全国でも多い方です（${s.label}）。返礼品などで人気を集めているのかもしれません。`;
  }

  function income(): string | null {
    const s = stat("household_income_1000plus_share");
    if (!isTop(s, 0.05)) return null;
    return `世帯年収1000万円以上の世帯が${s.text}と全国でも高い方です（${s.label}）。所得の高い世帯が比較的多く住んでいると思われます。`;
  }

  function vacancy(): string | null {
    const s = stat("vacant_house_rate");
    if (!isTop(s, 0.1)) return null;
    return `空き家率が${s.text}と全国でも高い方です（${s.label}）。住む人が減り、使われなくなった家が増えているのかもしれません。`;
  }
}
