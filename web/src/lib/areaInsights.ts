import { formatNumber, formatValue } from "./format";
import type { Indicator, ValueRow } from "./types";

/**
 * 地域ページ「データで見る〇〇」の考察。決まった条件ごとに、数字と推測の文を出す。
 * 推測は「〜と思われます」「〜と考えられます」「〜ようです」で書き、断定しない。数字はすべて公開しているデータの値で、
 * 新しい推計はしない。値がない指標は使わない（0 として扱わない）。
 * 全国で目立つ特徴（強い考察）を先に、どの地域にも当てはまる一般的な考察（昼夜間人口・年齢構成など）を後に並べ、
 * どの市区町村にも少なくとも1つは出るようにする。
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
const MAX_INSIGHTS = 5;

// 値を並べた配列は指標・時点ごとに1回だけ作る（ビルドで約1,900ページが同じ値の表を使うため）
const sortedCache = new WeakMap<ValueRow[], { values: number[]; nationwide: boolean }>();
function sortedOf(rows: ValueRow[]) {
  let s = sortedCache.get(rows);
  if (!s) {
    const withValue = rows.filter((r) => r.value !== null);
    s = {
      values: withValue.map((r) => r.value as number).sort((a, b) => a - b),
      nationwide: new Set(withValue.map((r) => r.entity_id.slice(5, 7))).size > 1,
    };
    sortedCache.set(rows, s);
  }
  return s;
}
/** 並べた配列で v より小さい値の数（lt）と v 以下の値の数（le） */
function countBelow(values: number[], v: number): { lt: number; le: number } {
  const search = (strict: boolean) => {
    let lo = 0, hi = values.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (strict ? values[mid] < v : values[mid] <= v) lo = mid + 1; else hi = mid;
    }
    return lo;
  };
  return { lt: search(true), le: search(false) };
}

type Line = { text: string; strong: boolean };

export function areaInsights(muniId: string, data: InsightData): string[] {
  const stat = (id: string, period?: string): Stat | null => {
    const ind = data.indicator(id);
    if (!ind) return null;
    const p = period ?? ind.default_period;
    const rows = data.rows(id, p);
    const row = rows.find((r) => r.entity_id === muniId);
    if (!row || row.value === null) return null;
    const { values, nationwide: spans } = sortedOf(rows);
    // 全国の位置は、複数の都道府県に値があり、値に違いがある指標だけで見る
    const nationwide = spans && values[0] !== values[values.length - 1];
    const { lt, le } = countBelow(values, row.value);
    return {
      ind, value: row.value, text: formatValue(row, ind),
      label: ind.periods.find((x) => x.period === p)?.label ?? "",
      top: nationwide ? (values.length - le + 1) / values.length : null,
      bottom: nationwide ? (lt + 1) / values.length : null,
    };
  };
  // 型の絞り込みはしない（false のときに null と見なされるため）。真のときは値があるので ! で読む
  const isTop = (s: Stat | null, share: number): boolean => !!s && s.top !== null && s.top <= share;
  const isBottom = (s: Stat | null, share: number): boolean => !!s && s.bottom !== null && s.bottom <= share;
  const strong = (text: string): Line => ({ text, strong: true });
  const general = (text: string): Line => ({ text, strong: false });

  const gap = foreignGap();
  const lines = [gap, gap ? null : foreignShare(), daytime(), populationChange(), ageStructure(), households(), housing(),
    commute(), industry(), shopping(), furusato(), income(), vacancy(), education()]
    .filter((l): l is Line => !!l);
  // 強い考察を先に（並びは上の順のまま）、一般的な考察で埋める
  return [...lines.filter((l) => l.strong), ...lines.filter((l) => !l.strong)].slice(0, MAX_INSIGHTS).map((l) => l.text);

  /** 外国人: 国勢調査（10月1日）と住民基本台帳（1月1日）の差。数え方の違いに加え、季節で住む人が入れ替わる地域で大きく開く */
  function foreignGap(): Line | null {
    const census = data.indicator("foreign_resident_share");
    const juki = data.indicator("foreign_residents_share");
    if (!census || !juki) return null;
    // 国勢調査の最新の回と、その後6か月以内の住民基本台帳の時点を比べる
    const cp = census.periods.map((p) => p.period).sort().reverse().find((p) => stat("foreign_resident_share", p));
    if (!cp) return null;
    const c = stat("foreign_resident_share", cp)!;
    const limit = new Date(cp);
    limit.setMonth(limit.getMonth() + 6);
    const jp = juki.periods.map((p) => p.period).sort().find((p) => p > cp && new Date(p) <= limit);
    const j = jp ? stat("foreign_residents_share", jp) : null;
    if (!j) return null;
    const cCount = data.rows("census_foreign_population", cp).find((r) => r.entity_id === muniId)?.value ?? null;
    const jCount = data.rows("foreign_residents", jp!).find((r) => r.entity_id === muniId)?.value ?? null;
    // 人数が少ない地域は数人の違いで割合が大きく動くので見ない
    if (cCount === null || jCount === null || Math.max(cCount, jCount) < 30) return null;
    const head = `外国人住民の割合は、住民基本台帳（${j!.label}）では${j!.text}、国勢調査（${c!.label}）では${c!.text}です。`;
    if (j.value >= c.value * 1.5 && j.value - c.value >= 2) {
      return strong(head + "1月の時点の方がかなり多く、冬の観光や農作業など、季節的に働きに来る外国人が多いと考えられます" +
        "（2つの統計は調べ方も違います）。");
    }
    if (c.value >= j.value * 1.5 && c.value - j.value >= 2) {
      return strong(head + "10月の時点の方がかなり多く、収穫や工事など、時期によって働きに来る外国人が入れ替わっているようです" +
        "（2つの統計は調べ方も違います）。");
    }
    return null;
  }

  function foreignShare(): Line | null {
    const s = stat("foreign_residents_share");
    if (!isTop(s, 0.05)) return null;
    // 人数が少ない地域は数人で割合が大きく動くので見ない
    const count = data.rows("foreign_residents").find((r) => r.entity_id === muniId)?.value ?? null;
    if (count === null || count < 30) return null;
    const mfg = stat("employees_manufacturing_share");
    const agri = stat("employees_agriculture_share");
    const why = isTop(mfg, 0.25) ? "工場で働く外国人が多く住んでいると思われます"
      : isTop(agri, 0.25) ? "農業や水産業で働く外国人が多く住んでいると思われます"
      : "働く人や留学生など、多くの外国人が暮らしている地域のようです";
    return strong(`外国人住民の割合が${s!.text}と全国でも高い方です（${s!.label}）。${why}。`);
  }

  function daytime(): Line | null {
    const s = stat("daytime_night_ratio");
    if (!s) return null;
    const head = `昼間の人口は住んでいる人の`;
    if (s.value >= 130) {
      return strong(`${head}${formatNumber(s.value / 100, 1)}倍です（${s!.label}）。周りから通勤・通学で人が集まる、職場や学校の多いまちと思われます。`);
    }
    if (s.value <= 85) {
      return strong(`${head}${formatNumber(s.value, 0)}%です（${s!.label}）。周りのまちへ通勤・通学する人が多い、住宅地としての性格が強いと考えられます。`);
    }
    if (s.value >= 110) {
      return general(`${head}${formatNumber(s.value, 0)}%です（${s!.label}）。周りの地域から働きに来る人がやや多く、地域の中心的なまちのようです。`);
    }
    if (s.value <= 95) {
      return general(`${head}${formatNumber(s.value, 0)}%です（${s!.label}）。まちの外へ通勤・通学する人がやや多いようです。`);
    }
    return general(`${head}${formatNumber(s.value, 0)}%で、昼と夜の人口がほぼ同じです（${s!.label}）。多くの人がまちの中で働き、暮らしていると思われます。`);
  }

  function populationChange(): Line | null {
    const s = stat("population_change_rate");
    if (!s) return null;
    const amount = s.text.replace(/^[+−-]/, "");
    if (isTop(s, 0.1) && s.value > 0) {
      return strong(`人口は5年前から${amount}増えていて（${s!.label}）、全国の市区町村の中でも増え方が大きい方です。住宅の開発などで移り住む人が多いと考えられます。`);
    }
    if (isBottom(s, 0.1) && s.value < 0) {
      return strong(`人口は5年前から${amount}減っていて（${s!.label}）、全国の市区町村の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。`);
    }
    if (s.value > 0) {
      return general(`人口は5年前から${amount}増えています（${s!.label}）。全国で人口が減る市区町村が多い中、人が集まっている地域のようです。`);
    }
    if (s.value === 0) return general(`人口は5年前からほとんど変わっていません（${s!.label}）。`);
    if (isTop(s, 0.5)) {
      return general(`人口は5年前から${amount}減っていますが（${s!.label}）、全国の市区町村の中では減り方が小さい方です。人口が比較的保たれている地域と考えられます。`);
    }
    if (isBottom(s, 0.3)) {
      return general(`人口は5年前から${amount}減っていて（${s!.label}）、全国の市区町村の中では減り方がやや大きい方です。人口減少が進んでいる地域と考えられます。`);
    }
    return general(`人口は5年前から${amount}減っています（${s!.label}）。全国の多くの市区町村と同じく、少しずつ人口が減っているようです。`);
  }

  function ageStructure(): Line | null {
    const aged = stat("aged_65_plus_share");
    const kids = stat("children_0_14_share");
    if (isTop(aged, 0.1) && isBottom(kids, 0.25)) {
      return strong(`65歳以上の人が${aged!.text}、15歳未満の子どもが${kids!.text}です（${aged!.label}）。全国の中でも高齢化が進んだ地域と思われます。`);
    }
    if (isTop(kids, 0.1)) {
      return strong(`15歳未満の子どもの割合が${kids!.text}と全国でも高い方です（${kids!.label}）。子育て中の世帯が多く住んでいると思われます。`);
    }
    if (!aged) return null;
    if (isTop(aged, 0.3)) {
      return general(`65歳以上の人の割合は${aged!.text}で、全国の市区町村の中では高めです（${aged!.label}）。高齢化が進みつつある地域と考えられます。`);
    }
    if (isBottom(aged, 0.3)) {
      return general(`65歳以上の人の割合は${aged!.text}で、全国の市区町村の中では低めです（${aged!.label}）。働く世代や子育て世代が比較的多いようです。`);
    }
    if (aged.top === null) return general(`65歳以上の人の割合は${aged!.text}です（${aged!.label}）。`);
    return general(`65歳以上の人の割合は${aged!.text}で、全国の市区町村の中ではほぼ真ん中くらいです（${aged!.label}）。全国の平均的な年齢構成に近い地域と考えられます。`);
  }

  function households(): Line | null {
    const single = stat("single_person_household_share");
    if (isTop(single, 0.1)) {
      const students = stat("university_student_share");
      // 学生のまちと読むのは、大学生・大学院生が人口の5%以上いるときだけ（都心の区は割合の順位だけなら上位に入る）
      if (isTop(single, 0.05) && isTop(students, 0.05) && students!.value >= 5) {
        return strong(`一人暮らしの世帯が${single!.text}、大学生・大学院生が人口の${students!.text}で、どちらも全国で高い方です（${single!.label}）。学生の一人暮らしが多いまちと思われます。`);
      }
      // 高齢化が進んだ地域の一人暮らしは、働く人より高齢の人と考える方が自然
      if (isTop(stat("aged_65_plus_share"), 0.1)) {
        return strong(`一人暮らしの世帯が${single!.text}と全国でも高い方です（${single!.label}）。高齢の人の一人暮らしが多いと思われます。`);
      }
      return strong(`一人暮らしの世帯が${single!.text}と全国でも高い方です（${single!.label}）。単身で働く人や学生などが多く住んでいると思われます。`);
    }
    const size = stat("persons_per_household");
    if (isTop(size, 0.1)) {
      return strong(`1世帯あたりの人数が${size!.text}と全国でも多い方です（${size!.label}）。三世代で暮らす家族など、大きな世帯が多いと考えられます。`);
    }
    return null;
  }

  function housing(): Line | null {
    const owner = stat("owner_occupied_share");
    if (isTop(owner, 0.1)) {
      return strong(`持ち家に住む世帯が${owner!.text}と全国でも多い方です（${owner!.label}）。長く住み続ける人が多い地域と考えられます。`);
    }
    const rented = stat("private_rented_share");
    if (isTop(rented, 0.1)) {
      return strong(`民営の借家に住む世帯が${rented!.text}と全国でも多い方です（${rented!.label}）。進学や転勤などで移り住む人が多いようです。`);
    }
    return null;
  }

  function commute(): Line | null {
    const rail = stat("commute_rail_share");
    // 通勤圏と読むのは、昼間に人が出ていく（昼夜間人口比率が100%未満の）地域だけ。都心は鉄道で人が集まる側なので除く
    const day = stat("daytime_night_ratio");
    if (isTop(rail, 0.1) && day && day.value < 100) {
      return strong(`通勤・通学に鉄道を使う人が${rail!.text}と多く（${rail!.label}）、大きな都市への通勤圏にあると思われます。`);
    }
    const car = stat("commute_car_share");
    if (isTop(car, 0.1)) {
      return strong(`通勤・通学に自家用車を使う人が${car!.text}と多く（${car!.label}）、車が欠かせない暮らしと思われます。`);
    }
    return null;
  }

  function industry(): Line | null {
    const mfg = stat("employees_manufacturing_share");
    if (isTop(mfg, 0.1)) {
      return strong(`まちの事業所で働く人のうち製造業が${mfg!.text}を占めていて（${mfg!.label}）、工場の多いものづくりのまちと思われます。`);
    }
    const agri = stat("employees_agriculture_share");
    if (isTop(agri, 0.1)) {
      return strong(`まちの事業所で働く人のうち農林漁業が${agri!.text}を占めていて（${agri!.label}）、農業や漁業が暮らしを支えていると思われます。`);
    }
    const commerce = stat("employees_commerce_share");
    if (isTop(commerce, 0.1)) {
      return strong(`まちの事業所で働く人のうち卸売業・小売業が${commerce!.text}を占めていて（${commerce!.label}）、商業がまちを支える産業のようです。`);
    }
    // 目立つ産業がないときは、3つのうち全国の中で最も高い位置にあるものを挙げる
    const options: { s: Stat | null; name: string }[] = [{ s: mfg, name: "製造業" }, { s: agri, name: "農林漁業" }, { s: commerce, name: "卸売業・小売業" }];
    const best = options
      .filter((x): x is { s: Stat; name: string } => !!x.s && x.s.top !== null && x.s.top <= 0.4)
      .sort((a, b) => a.s.top! - b.s.top!)[0];
    if (!best) return null;
    return general(`まちの事業所で働く人のうち${best.name}が${best.s.text}で、全国の市区町村の中では多めです（${best.s.label}）。${best.name}がまちの主な産業の1つと考えられます。`);
  }

  function shopping(): Line | null {
    const s = stat("retail_sales_per_capita");
    if (!isTop(s, 0.05)) return null;
    return strong(`住民1人あたりの小売業の販売額が${s!.text}と全国でも大きい方です（${s!.label}）。周りから買い物に来る人が多い、商業の中心と思われます。`);
  }

  function furusato(): Line | null {
    const s = stat("furusato_amount_per_capita");
    if (!isTop(s, 0.03)) return null;
    return strong(`ふるさと納税の受入額が住民1人あたり${s!.text}と全国でも多い方です（${s!.label}）。返礼品などで人気を集めているようです。`);
  }

  function income(): Line | null {
    const high = stat("household_income_1000plus_share");
    if (isTop(high, 0.05)) {
      return strong(`世帯年収1000万円以上の世帯が${high!.text}と全国でも高い方です（${high!.label}）。所得の高い世帯が比較的多く住んでいると思われます。`);
    }
    return null;
  }

  function vacancy(): Line | null {
    const s = stat("vacant_house_rate");
    if (!isTop(s, 0.1)) return null;
    return strong(`空き家率が${s!.text}と全国でも高い方です（${s!.label}）。住む人が減り、使われなくなった家が増えていると考えられます。`);
  }

  function education(): Line | null {
    const univ = stat("hs_grad_university_rate");
    if (isTop(univ, 0.1)) {
      return strong(`まちにある高校の卒業者のうち大学などに進んだ人が${univ!.text}と全国でも高い方です（${univ!.label}、学校の所在地で数えています）。進学を目指す高校が多い地域のようです。`);
    }
    const job = stat("hs_grad_employment_rate");
    if (isTop(job, 0.1)) {
      return strong(`まちにある高校の卒業者のうち就職した人が${job!.text}と全国でも高い方です（${job!.label}、学校の所在地で数えています）。卒業後すぐに働き始める人の多い高校があると考えられます。`);
    }
    return null;
  }
}
