import { formatNumber, formatValue } from "./format";
import { approxCount, summarizePlaces, type MuniPlaces, type PlacePoints } from "./placeStats";
import { municipalityPeriods } from "./periods";
import { nationalityTemplate, RANK_TEMPLATES, tag, type RankTemplate, type Tag, type Tone } from "./rankInsights";
import type { Indicator, ValueRow } from "./types";

/**
 * 地域ページ「データで見る〇〇」の考察。決まった条件ごとに、数字と推測の文を出す。
 * 推測は「〜と思われます」「〜と考えられます」「〜ようです」で書き、断定しない。数字はすべて公開しているデータの値で、
 * 新しい推計はしない。値がない指標は使わない（0 として扱わない）。
 * 全国で目立つ特徴（強い考察）を先に、どの地域にも当てはまる一般的な考察（昼夜間人口・年齢構成など）を後に並べ、
 * どの市区町村にも少なくとも1つは出るようにする。
 * 課題に当たる文（人口減少・高齢化・空き家など）が半分以上になるときは、その地域の良いところを1つ入れ、
 * ネガティブな文だけのページにしない。住む人の国籍と犯罪など、並べると偏見につながる組み合わせは作らない。
 */
export interface InsightData {
  indicator(id: string): Indicator | undefined;
  /** 指標の市区町村の値（全国）。period を省くと既定の時点 */
  rows(id: string, period?: string): ValueRow[];
  /** すべての指標（全国順位で目立つ指標を探すのに使う） */
  indicators(): Indicator[];
  /** 駅・空港・港・地価公示・天気の点（ないときは点の考察を出さない） */
  places?(): PlacePoints | null;
}

interface Stat {
  ind: Indicator;
  /** 使った時点と、その表示名 */
  period: string;
  label: string;
  value: number;
  text: string;
  /** 全国の市区町村の中の位置（0〜1）。top は大きい方から、bottom は小さい方から。1つの都道府県だけの指標は null */
  top: number | null;
  bottom: number | null;
  /** 大きい方からの順位（同じ値は同じ順位）、小さい方からの順位、値のある市区町村の数 */
  rankTop: number;
  rankBottom: number;
  total: number;
  /** 同じ値の市区町村の数（自分を含む） */
  same: number;
}

/** 良いところを探す範囲（全国の上位・下位それぞれ全体のこの割合まで） */
const BRIGHT_SHARE = 0.25;
/** 考察の数の上限（多すぎると読まれないため） */
const MAX_INSIGHTS = 8;
/** 課題に当たる文の数の上限（人口減少と高齢化など、似た課題の文が並んで暗いページにならないようにする） */
const MAX_NEGATIVE = 3;
/** 全国順位で目立つとみなす範囲（上位・下位それぞれ全体のこの割合まで）と、その考察の数の上限 */
const RANK_SHARE = 0.02;
/** 上の範囲に入る指標がない市区町村は、この範囲まで広げて一番目立つ指標を1つ挙げる */
const RANK_SHARE_FALLBACK = 0.2;
const MAX_RANK_INSIGHTS = 3;

/**
 * 2011年の東京電力福島第一原子力発電所の事故で、避難指示などの対象になった12市町村（田村市・南相馬市・川俣町・広野町・楢葉町・
 * 富岡町・川内村・大熊町・双葉町・浪江町・葛尾村・飯舘村）。避難と帰還で人口や住む人の顔ぶれが大きく動いたため、
 * ほかの地域と同じ読み方をすると誤る考察（住宅の開発で移り住む、職場の多いまち、新しく住み始める人が多いなど）は出さない
 */
const EVACUATION_AREAS = new Set(["07211", "07212", "07308", "07541", "07542", "07543", "07544", "07545", "07546", "07547", "07548", "07564"]
  .map((c) => `muni-${c}`));
/** 上の12市町村で出さない考察（考察を出す処理の名前と、全国順位の考察の指標の id） */
const EVACUATION_SKIP = new Set([
  "populationChange", "daytime", "ageStructure", "households", "housing", "foreignGap", "foreignShare",
  "persons_per_household", "households_with_children_share", "owner_occupied_share", "same_residence_5y_share",
  "residence_under1y_share", "residence_under5y_share", "residence_20y_share", "self_employed_share", "professional_share",
  "manager_share", "university_graduate_share", "commute_walk_share", "commute_bicycle_share", "commute_bus_share", "commute_car_share",
]);

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

/**
 * 考察のまとまり（テーマ）。ページではテーマごとに小見出しを付けてまとめる。
 * 並びは、題名の元になった考察のテーマを先に、あとは目立つ考察のあるテーマから（同じなら下の順）
 */
export const THEMES = ["気候と土地", "交通", "住む人", "住まい", "仕事と産業", "まちの財政", "子育てと学び", "安全と健康", "選挙"] as const;
export type Theme = (typeof THEMES)[number];
/** 全国順位の考察（rankInsights）のテーマ。指標のカテゴリから決め、合わないものは指標ごとに決める */
const CATEGORY_THEME: Record<string, Theme> = {
  "人口・世帯": "住む人", "年齢構成": "住む人", "外国人住民": "住む人", "学歴": "住む人", "所得・税": "住む人", "暮らし方": "住まい",
  "緑": "気候と土地", "通勤・通学": "交通", "働き方": "仕事と産業", "農業": "仕事と産業", "工業": "仕事と産業", "商業": "仕事と産業",
  "観光": "仕事と産業", "子育て": "子育てと学び", "教育": "子育てと学び", "交通事故": "安全と健康", "犯罪": "安全と健康", "選挙": "選挙",
  "土地": "気候と土地", "財政": "まちの財政",
};
const ID_THEME: Record<string, Theme> = {
  population_density: "気候と土地",
  total_fertility_rate: "住む人",
  households_with_children_share: "住む人",
  life_expectancy_male: "安全と健康",
  life_expectancy_female: "安全と健康",
};
const themeOf = (ind: Indicator): Theme => ID_THEME[ind.id] ?? CATEGORY_THEME[ind.category] ?? "安全と健康";

/** w は見出しに選ぶときの目立ち方（小さいほど目立つ。全国の中の位置など） */
/** lead: 土地・財政の文で、全国の上位・下位2%に入るときのその位置（全国順位の考察のすぐ後に置き、ほかの文より先に選ぶ） */
type Line = { text: string; strong: boolean; tone?: Tone; tag?: Tag; w: number; theme?: Theme; topic?: string; lead?: number };
/**
 * テーマの中の話の順（人口 → 年齢 → 世帯 → 外国人 → 住まい → 地価、のように話がつながる順）。
 * 考察を出す処理の名前と、全国順位の考察の指標の id（国籍別・政党別は名前の頭）で並べる。ないものはテーマの最後
 */
const TOPIC_ORDER = [
  // 気候と土地
  "area", "population_density", "terrain", "altitude", "landuse", "forest", "farmland", "landChange", "bamboo", "weather",
  // 交通
  "airport", "port", "station", "commute", "commute_walk_share", "commute_bicycle_share", "commute_bus_share", "commute_car_share",
  // 住む人
  "evacuation", "populationChange", "ageStructure", "total_fertility_rate", "foreignGap", "foreignShare", "census_foreign", "households",
  "persons_per_household", "households_with_children_share", "university_graduate_share", "taxable_income_per_taxpayer",
  "income_levy_taxpayer_share", "income",
  // 住まい
  "same_residence_5y_share", "residence_20y_share", "residence_under5y_share", "residence_under1y_share",
  "housing", "owner_occupied_share", "high_rise_household_share", "land", "vacancy", "vacant_house_rate",
  // 仕事と産業
  "daytime", "industry", "manufacturing_shipments", "agri_output_rice", "agri_output_vegetables", "agri_output_fruits",
  "agri_output_livestock", "wholesale_sales", "shopping", "inbound_guest_nights", "inbound_guest_share",
  "self_employed_share", "professional_share", "manager_share", "furusato",
  // まちの財政
  "fiscal",
  // 子育てと学び
  "childcare_usage_rate", "preschool_kindergarten_share", "preschool_nursery_share", "preschool_kodomoen_share",
  "elem_class_size", "jhs_class_size", "jhs_students_private", "education", "hs_grad_vocational_rate",
  // 安全と健康
  "life_expectancy_male", "life_expectancy_female", "traffic_accidents_per_100_residents", "street_crime_total_per_100_residents",
  // 選挙
  "voter_turnout", "vote_share",
];
/** どの地域にも出やすい、ありきたりな考察（昼と夜の人口がほぼ同じ、平均的な年齢構成など）。ほかに考察が多いときは出さない */
const isFiller = (l: Line) => !l.strong && l.w >= 0.8;
/** ありきたりな考察を外しても、この数以上の考察が残るときは外す */
const MIN_WITHOUT_FILLER = 6;

// 点のデータの市区町村ごとのまとめは、点のデータ1つにつき1回だけ作る
const placeCache = new WeakMap<PlacePoints, Map<string, MuniPlaces>>();

/** 「データで見る〇〇」の見出し（特徴を一言で表す文）と考察（テーマごとのまとまりと、その順に並べた文） */
export interface AreaProfile { title: string | null; groups: { theme: Theme; lines: string[] }[]; lines: string[] }

export function areaInsights(muniId: string, data: InsightData): string[] {
  return areaProfile(muniId, data).lines;
}

export function areaProfile(muniId: string, data: InsightData): AreaProfile {
  // period を省くと、国勢調査の新しい回（2025年）を先に使い、その市区町村に値がなければ既定の時点を使う（設計変更記録 #118）。
  // 順位・全国の位置は、使った時点の市区町村の中で数える
  const stat = (id: string, period?: string): Stat | null => {
    const ind = data.indicator(id);
    if (!ind) return null;
    let p = "", rows: ValueRow[] = [], row: ValueRow | undefined;
    for (const candidate of period ? [period] : municipalityPeriods(ind)) {
      rows = data.rows(id, candidate);
      row = rows.find((r) => r.entity_id === muniId && r.value !== null);
      if (row) { p = candidate; break; }
    }
    if (!row || row.value === null) return null;
    const { values, nationwide: spans } = sortedOf(rows);
    // 全国の位置は、複数の都道府県に値があり、値に違いがある指標だけで見る
    const nationwide = spans && values[0] !== values[values.length - 1];
    const { lt, le } = countBelow(values, row.value);
    return {
      ind, period: p, value: row.value, text: formatValue(row, ind),
      label: ind.periods.find((x) => x.period === p)?.label ?? "",
      // 同じ値の市区町村が多いとき（件数0など）は、その全部を数えた位置にする（同じ値の多くが「上位1件」に見えないように）
      top: nationwide ? (values.length - lt) / values.length : null,
      bottom: nationwide ? le / values.length : null,
      rankTop: values.length - le + 1, rankBottom: lt + 1, total: values.length, same: le - lt,
    };
  };
  // 型の絞り込みはしない（false のときに null と見なされるため）。真のときは値があるので ! で読む
  const isTop = (s: Stat | null, share: number): boolean => !!s && s.top !== null && s.top <= share;
  const isBottom = (s: Stat | null, share: number): boolean => !!s && s.bottom !== null && s.bottom <= share;
  const strong = (text: string, tone?: Tone, t?: Tag, w = 0.1): Line => ({ text, strong: true, tone, tag: t, w });
  const general = (text: string, tone?: Tone, t?: Tag, w = 0.5): Line => ({ text, strong: false, tone, tag: t, w });
  const pts = data.places?.() ?? null;
  let place: MuniPlaces = {};
  if (pts) {
    let m = placeCache.get(pts);
    if (!m) { m = summarizePlaces(pts); placeCache.set(pts, m); }
    place = m.get(muniId) ?? {};
  }

  const evacuated = EVACUATION_AREAS.has(muniId);
  const gap = foreignGap();
  const ranked = rankCandidates();
  const on = (theme: Theme, topic: string, l: Line | null): Line | null => {
    if (l) { l.theme ??= theme; l.topic ??= topic; }
    return l;
  };
  // 面積・地形・土地利用・農地・財政の文。全国の上位・下位2%に入るものは、目立つ順に2つまで全国順位の考察と同じように先に選ぶ
  const land = [on("気候と土地", "area", areaSize()), on("気候と土地", "terrain", terrain()), ...landUse().map((l) => on("気候と土地", "landuse", l)),
    on("気候と土地", "farmland", farmland()), on("気候と土地", "landChange", landChange()), on("気候と土地", "bamboo", bamboo()),
    on("まちの財政", "fiscal", fiscal())].filter((l): l is Line => !!l);
  const leading = land.filter((l) => l.lead !== undefined).sort((a, b) => a.lead! - b.lead!).slice(0, 2);
  const all = [on("住む人", "evacuation", evacuation()), on("住む人", "foreignGap", gap), ...rankNotables(), ...leading, on("交通", "airport", airport()), on("交通", "port", port()),
    on("交通", "station", station()), ...weather().map((l) => on("気候と土地", "weather", l)), on("住まい", "land", landPrice()),
    on("住む人", "foreignShare", gap ? null : foreignShare()), on("仕事と産業", "daytime", daytime()),
    on("住む人", "populationChange", populationChange()), on("住む人", "ageStructure", ageStructure()),
    on("住む人", "households", households()), on("住まい", "housing", housing()), on("交通", "commute", commute()),
    on("仕事と産業", "industry", industry()), on("仕事と産業", "shopping", shopping()), on("仕事と産業", "furusato", furusato()),
    on("住む人", "income", income()), on("住まい", "vacancy", vacancy()), on("子育てと学び", "education", education()),
    on("住まい", "land", landGeneral()), on("交通", "station", stationGeneral()), ...land.filter((l) => !leading.includes(l))]
    .filter((l): l is Line => !!l && !(evacuated && EVACUATION_SKIP.has(l.topic ?? "")))
    // 同じことを言う考察は1つにする（持ち家が少ない方の全国順位があれば、借家が多いという文は出さない）
    .filter((l, _, list) => !(l.topic === "housing" && l.text.startsWith("民営の借家") && list.some((x) => x.topic === "owner_occupied_share")));
  // ほかに考察が十分あるときは、どの地域にも出やすいありきたりな考察を外す
  const lines = all.filter((l) => !isFiller(l)).length >= MIN_WITHOUT_FILLER ? all.filter((l) => !isFiller(l)) : all;
  // 強い考察を先に（並びは上の順のまま）、一般的な考察で埋める
  const ordered = [...lines.filter((l) => l.strong), ...lines.filter((l) => !l.strong)];
  const picked = balance(ordered.filter((l) => l.tone !== "neg" || ordered.filter((x) => x.tone === "neg").indexOf(l) < MAX_NEGATIVE)
    .slice(0, MAX_INSIGHTS));
  const titleLines: Line[] = [];
  const title = headline(picked);
  const groups = arrange(picked);
  return { title, groups: groups.map((g) => ({ theme: g.theme, lines: g.lines.map((l) => l.text) })),
    lines: groups.flatMap((g) => g.lines.map((l) => l.text)) };

  /**
   * 読む順に並べる。同じテーマの考察はまとめ、題名の元になった考察のテーマを先頭に（題名のすぐ下で理由が分かるように）、
   * あとは最初の文が目立つテーマから。課題に当たる文は目立ち方を割り引き、地域の特徴から読み始められるようにする。
   * 政党の得票率などの選挙は、まちの第一印象が支持政党にならないよう、最後の方にする。
   * テーマの中は、題名の元になった考察を先に、あとは話がつながる順（TOPIC_ORDER）にする
   */
  function arrange(list: Line[]): { theme: Theme; lines: Line[] }[] {
    const score = (l: Line) => {
      // 避難指示などの対象になった市町村は、ほかの値を読む前提になるので、その文を最初に置く
      if (l.topic === "evacuation") return -20;
      const t = titleLines.indexOf(l);
      if (t >= 0) return t - 10;
      // 住む人の国籍の文は、題名と同じく、まちの第一印象にしない
      const origin = l.topic === "foreignShare" || l.topic?.startsWith("census_foreign_");
      // 財政は自治体の評価として読まれないよう、まちの特徴（土地・人・産業）の後にする
      return l.w + (l.tone === "neg" ? 0.5 : 0) + (origin ? 0.5 : 0) + (l.theme === "選挙" ? 1 : 0) + (l.theme === "まちの財政" ? 0.5 : 0);
    };
    const topic = (l: Line) => {
      if (l.topic === "evacuation") return -2;
      if (titleLines.includes(l)) return -1;
      const t = l.topic ?? "";
      // 指標の系統（国籍別の外国人・政党別の得票率）は名前の頭で見る
      const i = TOPIC_ORDER.indexOf(t) >= 0 ? TOPIC_ORDER.indexOf(t) : TOPIC_ORDER.findIndex((x) => t.startsWith(`${x}_`));
      return i < 0 ? TOPIC_ORDER.length : i;
    };
    const byTheme = new Map<Theme, Line[]>();
    for (const l of list) {
      const theme = l.theme ?? "安全と健康";
      byTheme.set(theme, [...(byTheme.get(theme) ?? []), l]);
    }
    // テーマは、その最初の文（読む人が最初に目にする文）の目立ち方で並べる
    return [...byTheme].map(([theme, lines]) => ({ theme, lines: [...lines].sort((a, b) => topic(a) - topic(b) || score(a) - score(b)) }))
      .sort((a, b) => score(a.lines[0]) - score(b.lines[0]) || THEMES.indexOf(a.theme) - THEMES.indexOf(b.theme));
  }

  /**
   * 特徴を一言で表す見出し。表示する考察のうち全国の中で目立つものから、課題に当たらない言い回しを2つまで選んで
   * 「雪が多く、米どころのまち」のようにつなぐ。選んだ考察にないときは、ほかの考察からも探す
   */
  function headline(list: Line[]): string | null {
    // 表示する考察のほか、全国の上位・下位10%に入る指標の考察も候補にする（選んだときは考察にも加える）
    const extra = ranked.filter((f) => f.pos <= 0.1 && f.tag && f.tone !== "neg" && !list.some((l) => l.text === f.text))
      .map((f) => ({ ...strong(f.text, f.tone, f.tag, f.pos), theme: f.theme, topic: f.id }));
    const usable = (ls: Line[]) => ls.filter((l) => l.tag && l.tone !== "neg").sort((a, b) => a.w - b.w);
    let candidates = usable([...list, ...extra, ...lines.filter((l) => !list.includes(l))]);
    // ほかに言い回しがないときだけ、外したありきたりな考察（職場と住まいが近いなど）からも作る
    if (!candidates.length) candidates = usable(all.filter((l) => !lines.includes(l)));
    const chosen: Line[] = [];
    for (const l of candidates) {
      if (chosen.some((x) => x.tag!.key === l.tag!.key)) continue;
      // 「盛ん」が2回続くなど、同じ言葉が重なる組み合わせは避ける
      if (chosen.length === 1 && ["盛ん", "多く", "多い"].some((w) => chosen[0].tag!.renyou.includes(w) && l.tag!.rentai.includes(w))) continue;
      chosen.push(l);
      if (chosen.length === 2) break;
    }
    if (!chosen.length) return null;
    // 見出しの元になった考察が表示する考察にないときは、いちばん後ろの一般的な考察と入れ替えて加える
    for (const l of chosen) {
      if (list.includes(l)) continue;
      if (list.length >= MAX_INSIGHTS) {
        // 良いところの文（ネガティブな文だけにしないために入れたもの）は残す
        const drop = list.findLastIndex((x) => !x.strong && x.tone !== "pos");
        if (drop < 0) continue;
        list.splice(drop, 1);
      }
      list.splice(list.filter((x) => x.strong).length, 0, l);
    }
    titleLines.push(...chosen);
    const [a, b] = chosen.map((l) => l.tag!);
    return b ? `${a.renyou}、${b.rentai}まち` : `${a.rentai}まち`;
  }

  /** 課題に当たる文が半分以上なら、良いところの文を1つ入れる（最後の課題の文と入れ替える） */
  function balance(list: Line[]): Line[] {
    const negatives = list.filter((l) => l.tone === "neg");
    if (negatives.length * 2 < list.length || list.some((l) => l.tone === "pos")) return list;
    const used = new Set(list.map((l) => l.text));
    const bright = [...lines, ...brightSide()].find((l) => l.tone === "pos" && !used.has(l.text))
      ?? lines.find((l) => l.tone !== "neg" && !used.has(l.text));
    if (!bright) return list;
    if (list.length < MAX_INSIGHTS) return [...list, bright];
    const last = list.lastIndexOf(negatives[negatives.length - 1]);
    return list.map((l, i) => (i === last ? bright : l));
  }

  /**
   * 全国の中で比較的よい位置にある、良いところに当たる指標を1つ。上位・下位25%までは考察の文も付け、
   * それより下（半分まで）は考察を言い過ぎにならないよう、順位と「半分に入る」ことだけを書く
   */
  function brightSide(): Line[] {
    const best = ranked.find((f) => f.tone === "pos");
    if (!best) return [];
    if (best.pos <= BRIGHT_SHARE) return [{ ...strong(best.text, best.tone, best.pos <= 0.1 ? best.tag : undefined, best.pos), theme: best.theme, topic: best.id }];
    return [{ ...general(`${best.fact}全国の中では${best.high ? "大きい" : "小さい"}方の半分に入ります。`, best.tone), theme: best.theme, topic: best.id }];
  }

  /** 全国の市区町村の中で順位が特に高い・低い指標（上位・下位2%）に、指標ごとの考察を付ける。目立つ順に3つまで */
  function rankNotables(): Line[] {
    const sorted = ranked.filter((f) => f.pos <= RANK_SHARE_FALLBACK);
    const within = sorted.filter((f) => f.pos <= RANK_SHARE);
    return (within.length ? within.slice(0, MAX_RANK_INSIGHTS) : sorted.slice(0, 1))
      .map((f) => ({ ...strong(f.text, f.tone, f.pos <= 0.1 ? f.tag : undefined, f.pos), theme: f.theme, topic: f.id }));
  }

  /** 考察の文がある指標を、全国の中で目立つ順に（同じ系統の指標は1つだけ） */
  type Ranked = { id: string; pos: number; group: string; text: string; fact: string; high: boolean; tone?: Tone; tag?: Tag; theme: Theme };
  function rankCandidates(): Ranked[] {
    const jp = (n: number) => n.toLocaleString("ja-JP");
    const found: Ranked[] = [];
    for (const ind of data.indicators()) {
      const t: RankTemplate | null = RANK_TEMPLATES[ind.id] ?? nationalityTemplate(ind.id, ind.name);
      if (!t || (evacuated && EVACUATION_SKIP.has(ind.id))) continue;
      const s = stat(ind.id);
      if (!s || s.top === null || s.bottom === null || s.total < 100) continue;
      if (t.minCountOf) {
        const n = data.rows(t.minCountOf, s.period).find((r) => r.entity_id === muniId)?.value ?? null;
        if (n === null || n < (t.minCount ?? 0)) continue;
      }
      const group = ind.family ?? ind.id;
      // 同じ値の市区町村がほかにもあるときは、その数を添える（件数0の市区町村が並ぶときに「1番目」とだけ書かない）
      const same = s.same > 1 ? `、同じ値の市区町村が${jp(s.same)}あります` : "";
      if (t.high && s.top <= 0.5 && (!t.low || s.top <= s.bottom)) {
        const fact = `${ind.name}は${s.text}で、全国${jp(s.total)}市区町村のうち${jp(s.rankTop)}位です（${s.label}${same}）。`;
        found.push({ id: ind.id, pos: s.top, group, tone: t.highTone, tag: t.highTag, fact, high: true, text: fact + t.high, theme: themeOf(ind) });
      } else if (t.low && s.bottom <= 0.5 && (!t.lowWhen || isTop(stat(t.lowWhen.id), t.lowWhen.top))) {
        const fact = s.rankBottom === 1 && s.same > 1
          ? `${ind.name}は${s.text}で、全国${jp(s.total)}市区町村の中で最も低い値です（${s.label}${same}）。`
          : `${ind.name}は${s.text}で、全国${jp(s.total)}市区町村の中で低い方から${jp(s.rankBottom)}番目です（${s.label}${same}）。`;
        found.push({ id: ind.id, pos: s.bottom, group, tone: t.lowTone, tag: t.lowTag, fact, high: false, text: fact + t.low, theme: themeOf(ind) });
      }
    }
    const seen = new Set<string>();
    return found.sort((a, b) => a.pos - b.pos).filter((f) => !seen.has(f.group) && !!seen.add(f.group));
  }

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
      // 冬の観光で人が集まると書くのは、雪の多い地域（近くの観測所の年間の降雪量が200cm以上）だけ
      const snow = Math.max(place.weather?.values.snowfall_normal?.value ?? 0, place.snowNearby ?? 0);
      if (snow >= 200) {
        return strong(head + "1月の時点の方がかなり多く、冬の観光や農作業など、季節的に働きに来る外国人が多いと考えられます" +
          "（2つの統計は調べ方も違います）。", undefined, tag("season", "冬に人が集まり", "冬に人が集まる"), 0.005);
      }
      return strong(head + "1月の時点の方がかなり多く、時期によって働きに来る外国人が入れ替わっていることや、" +
        "2つの統計の調べ方の違いが表れていると考えられます。", undefined, undefined, 0.005);
    }
    if (c.value >= j.value * 1.5 && c.value - j.value >= 2) {
      return strong(head + "10月の時点の方がかなり多く、収穫や工事など、時期によって働きに来る外国人が入れ替わっているようです" +
        "（2つの統計は調べ方も違います）。", undefined, tag("season", "季節ごとに働く人が集まり", "季節ごとに働く人が集まる"), 0.005);
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
    // 題名には使わない（住む人の国籍でまちを言い表すことになり、偏見につながるおそれがあるため）
    return strong(`外国人住民の割合が${s!.text}と全国でも高い方です（${s!.label}）。${why}。`);
  }

  function daytime(): Line | null {
    const s = stat("daytime_night_ratio");
    if (!s) return null;
    const head = `昼間の人口は住んでいる人の`;
    if (s.value >= 130) {
      return strong(`${head}${formatNumber(s.value / 100, 1)}倍です（${s!.label}）。周りから通勤・通学で人が集まる、職場や学校の多いまちと思われます。`, "pos", tag("hub", "周りから人が集まり", "周りから人が集まる"), 0.04);
    }
    if (s.value <= 85) {
      return strong(`${head}${formatNumber(s.value, 0)}%です（${s!.label}）。周りのまちへ通勤・通学する人が多い、住宅地としての性格が強いと考えられます。`, undefined, tag("bed", "住宅地としての性格が強く", "住宅地としての性格が強い"));
    }
    if (s.value >= 110) {
      return general(`${head}${formatNumber(s.value, 0)}%です（${s!.label}）。周りの地域から働きに来る人がやや多く、地域の中心的なまちのようです。`, undefined, tag("hub", "地域の中心となり", "地域の中心となる"), 0.4);
    }
    if (s.value <= 95) {
      return general(`${head}${formatNumber(s.value, 0)}%です（${s!.label}）。まちの外へ通勤・通学する人がやや多いようです。`, undefined,
        tag("out", "周りのまちへ通う人がやや多く", "周りのまちへ通う人がやや多い"), 0.8);
    }
    return general(`${head}${formatNumber(s.value, 0)}%で、昼と夜の人口がほぼ同じです（${s!.label}）。多くの人がまちの中で働き、暮らしていると思われます。`, undefined, tag("near", "職場と住まいが近く", "職場と住まいが近い"), 0.9);
  }

  /**
   * 避難指示などの対象になった12市町村は、国勢調査の人口の移り変わりを書く（5年前からの増減だけでは、
   * 避難と帰還で大きく動いた人口を読み違えるため）。住む人の年齢・世帯・住み始めた時期などの考察は出さない理由も添える
   */
  function evacuation(): Line | null {
    if (!evacuated) return null;
    const pop = data.indicator("population_total");
    const series = (pop?.periods.map((p) => p.period).sort() ?? [])
      .map((p) => ({ year: p.slice(0, 4), s: stat("population_total", p) }))
      .filter((x): x is { year: string; s: Stat } => x.s !== null);
    if (!series.length) return null;
    const list = series.map((x, i) => `${x.year}年${i === series.length - 1 ? "は" : "が"}${x.s.text}`).join("、");
    const [prev, last] = series.slice(-2).map((x) => x.s.value);
    const back = series.length >= 2 && last > prev
      ? "避難指示が解除された地域に戻った人や、復興の仕事などで新しく住む人が加わり、5年前より増えたと思われます。" : "";
    return strong(`2011年の東京電力福島第一原子力発電所の事故で、避難指示などの対象になった12市町村の1つです。` +
      `国勢調査の人口は${list}です。${back}住む人の年齢や世帯、住み始めた時期などの値も、避難と帰還の影響を大きく受けていると考えられます。`,
      undefined, undefined, 0.05);
  }

  function populationChange(): Line | null {
    const s = stat("population_change_rate");
    if (!s) return null;
    const amount = s.text.replace(/^[+−-]/, "");
    const since = sinceLong();
    if (isTop(s, 0.1) && s.value > 0) {
      return strong(`人口は5年前から${amount}増えていて（${s!.label}）、全国の市区町村の中でも増え方が大きい方です。${since}住宅の開発などで移り住む人が多いと考えられます。`, "pos", tag("grow", "人口が大きく増え", "人口が大きく増えている"), s.top!);
    }
    if (isBottom(s, 0.1) && s.value < 0) {
      return strong(`人口は5年前から${amount}減っていて（${s!.label}）、全国の市区町村の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。`, "neg");
    }
    if (s.value > 0) {
      return general(`人口は5年前から${amount}増えています（${s!.label}）。${since}全国で人口が減る市区町村が多い中、人が集まっている地域のようです。`, "pos", tag("grow", "人口が増え", "人口が増えている"), 0.4);
    }
    if (s.value === 0) return general(`人口は5年前からほとんど変わっていません（${s!.label}）。`);
    if (isTop(s, 0.5)) {
      return general(`人口は5年前から${amount}減っていますが（${s!.label}）、全国の市区町村の中では減り方が小さい方です。${since}人口が比較的保たれている地域と考えられます。`, "pos");
    }
    if (isBottom(s, 0.3)) {
      return general(`人口は5年前から${amount}減っていて（${s!.label}）、全国の市区町村の中では減り方がやや大きい方です。人口減少が進んでいる地域と考えられます。`, "neg");
    }
    return general(`人口は5年前から${amount}減っています（${s!.label}）。全国の多くの市区町村と同じく、少しずつ人口が減っているようです。`, "neg");
  }

  /**
   * 最も古い時点（2010年。今の区域に組み替えた値）からの人口の増え方。増えているときだけ文に添える
   * （人口の増減の文が減っている向きのときは、課題の文を重ねないため書かない）
   */
  function sinceLong(): string {
    const pop = data.indicator("population_total");
    const now = stat("population_total");
    const first = pop?.periods.map((p) => p.period).sort()[0];
    if (!now || !first || first >= now.period) return "";
    const then = stat("population_total", first);
    if (!then || then.value <= 0) return "";
    const rate = ((now.value - then.value) / then.value) * 100;
    const years = Number(now.period.slice(0, 4)) - Number(first.slice(0, 4));
    if (years <= 5 || rate < 0.05) return "";
    return `${first.slice(0, 4)}年からの${years}年では${formatNumber(rate, 1)}%増えています。`;
  }

  function ageStructure(): Line | null {
    const aged = stat("aged_65_plus_share");
    const kids = stat("children_0_14_share");
    if (isTop(aged, 0.1) && isBottom(kids, 0.25)) {
      return strong(`65歳以上の人が${aged!.text}、15歳未満の子どもが${kids!.text}です（${aged!.label}）。全国の中でも高齢化が進んだ地域と思われます。`, "neg");
    }
    if (isTop(kids, 0.1)) {
      return strong(`15歳未満の子どもの割合が${kids!.text}と全国でも高い方です（${kids!.label}）。子育て中の世帯が多く住んでいると思われます。`, "pos", tag("kids", "子育て世代が多く", "子育て世代の多い"), kids!.top!);
    }
    if (!aged) return null;
    if (isTop(aged, 0.3)) {
      return general(`65歳以上の人の割合は${aged!.text}で、全国の市区町村の中では高めです（${aged!.label}）。高齢化が進みつつある地域と考えられます。`, "neg");
    }
    if (isBottom(aged, 0.3)) {
      return general(`65歳以上の人の割合は${aged!.text}で、全国の市区町村の中では低めです（${aged!.label}）。働く世代や子育て世代が比較的多いようです。`, undefined, tag("young", "働く世代が多く", "働く世代の多い"), 0.4);
    }
    if (aged.top === null) return general(`65歳以上の人の割合は${aged!.text}です（${aged!.label}）。`);
    return general(`65歳以上の人の割合は${aged!.text}で、全国の市区町村の中ではほぼ真ん中くらいです（${aged!.label}）。全国の平均的な年齢構成に近い地域と考えられます。`,
      undefined, tag("avg", "全国の平均的な年齢構成で", "全国の平均的な年齢構成に近い"), 0.95);
  }

  function households(): Line | null {
    const single = stat("single_person_household_share");
    if (isTop(single, 0.1)) {
      const students = stat("university_student_share");
      // 学生のまちと読むのは、大学生・大学院生が人口の5%以上いるときだけ（都心の区は割合の順位だけなら上位に入る）
      if (isTop(single, 0.05) && isTop(students, 0.05) && students!.value >= 5) {
        // 2つの時点が違うとき（一人暮らしは2025年、大学生は2020年など）は、それぞれに時点を添える
        const same = single!.label === students!.label;
        const each = (x: Stat) => (same ? "" : `（${x.label}）`);
        return strong(`一人暮らしの世帯が${single!.text}${each(single!)}、大学生・大学院生が人口の${students!.text}${each(students!)}で、` +
          `どちらも全国で高い方です${same ? `（${single!.label}）` : ""}。学生の一人暮らしが多いまちと思われます。`, undefined, tag("students", "学生が多く", "学生の多い"), 0.02);
      }
      // 高齢化が進んだ地域の一人暮らしは、働く人より高齢の人と考える方が自然
      if (isTop(stat("aged_65_plus_share"), 0.1)) {
        return strong(`一人暮らしの世帯が${single!.text}と全国でも高い方です（${single!.label}）。高齢の人の一人暮らしが多いと思われます。`, "neg");
      }
      return strong(`一人暮らしの世帯が${single!.text}と全国でも高い方です（${single!.label}）。単身で働く人や学生などが多く住んでいると思われます。`);
    }
    const size = stat("persons_per_household");
    if (isTop(size, 0.1)) {
      return strong(`1世帯あたりの人数が${size!.text}と全国でも多い方です（${size!.label}）。三世代で暮らす家族など、大きな世帯が多いと考えられます。`, undefined, tag("family", "大家族が多く", "大家族の多い"), size!.top!);
    }
    return null;
  }

  function housing(): Line | null {
    const owner = stat("owner_occupied_share");
    if (isTop(owner, 0.1)) {
      return strong(`持ち家に住む世帯が${owner!.text}と全国でも多い方です（${owner!.label}）。長く住み続ける人が多い地域と考えられます。`, "pos", tag("settled", "持ち家が多く", "持ち家の多い"), owner!.top!);
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
      return strong(`通勤・通学に鉄道を使う人が${rail!.text}と多く（${rail!.label}）、大きな都市への通勤圏にあると思われます。`, undefined, tag("rail", "鉄道で都市へ通いやすく", "大きな都市への通勤圏にある"), rail!.top!);
    }
    const car = stat("commute_car_share");
    if (isTop(car, 0.1)) {
      return strong(`通勤・通学に自家用車を使う人が${car!.text}と多く（${car!.label}）、車が欠かせない暮らしと思われます。`, undefined, tag("car", "車が暮らしの足となり", "車が暮らしの足となる"), car!.top!);
    }
    return null;
  }

  function industry(): Line | null {
    const mfg = stat("employees_manufacturing_share");
    if (isTop(mfg, 0.1)) {
      return strong(`まちの事業所で働く人のうち製造業が${mfg!.text}を占めていて（${mfg!.label}）、工場の多いものづくりのまちと思われます。`, "pos", tag("mfg", "ものづくりが盛んで", "ものづくりの盛んな"), mfg!.top!);
    }
    const agri = stat("employees_agriculture_share");
    if (isTop(agri, 0.1)) {
      return strong(`まちの事業所で働く人のうち農林漁業が${agri!.text}を占めていて（${agri!.label}）、農業や漁業が暮らしを支えていると思われます。`, "pos", tag("agri", "農業や漁業が盛んで", "農業や漁業の盛んな"), agri!.top!);
    }
    const commerce = stat("employees_commerce_share");
    if (isTop(commerce, 0.1)) {
      return strong(`まちの事業所で働く人のうち卸売業・小売業が${commerce!.text}を占めていて（${commerce!.label}）、商業がまちを支える産業のようです。`, "pos", tag("commerce", "商業が盛んで", "商業の盛んな"), commerce!.top!);
    }
    // 目立つ産業がないときは、3つのうち全国の中で最も高い位置にあるものを挙げる
    const options: { s: Stat | null; name: string; key: string }[] = [{ s: mfg, name: "製造業", key: "mfg" }, { s: agri, name: "農林漁業", key: "agri" }, { s: commerce, name: "卸売業・小売業", key: "commerce" }];
    const best = options
      .filter((x): x is { s: Stat; name: string; key: string } => !!x.s && x.s.top !== null && x.s.top <= 0.4)
      .sort((a, b) => a.s.top! - b.s.top!)[0];
    if (!best) return null;
    return general(`まちの事業所で働く人のうち${best.name}が${best.s.text}で、全国の市区町村の中では多めです（${best.s.label}）。${best.name}がまちの主な産業の1つと考えられます。`, "pos",
      tag(best.key, `${best.name}が主な産業で`, `${best.name}が主な産業の`), 0.6);
  }

  function shopping(): Line | null {
    const s = stat("retail_sales_per_capita");
    if (!isTop(s, 0.05)) return null;
    // 人口の少ない町村では、道の駅や観光客の買い物で1人あたりの額が大きくなりやすく、「商業の中心」とは言いにくいので書かない
    if ((stat("population_total")?.value ?? 0) < 10000) return null;
    return strong(`住民1人あたりの小売業の販売額が${s!.text}と全国でも大きい方です（${s!.label}）。周りから買い物に来る人が多い、商業の中心と思われます。`, "pos", tag("commerce", "買い物客が集まり", "買い物客の集まる"), s!.top!);
  }

  function furusato(): Line | null {
    const s = stat("furusato_amount_per_capita");
    if (!isTop(s, 0.03)) return null;
    return strong(`ふるさと納税の受入額が住民1人あたり${s!.text}と全国でも多い方です（${s!.label}）。返礼品などで人気を集めているようです。`, "pos", tag("furusato", "ふるさと納税で人気を集め", "ふるさと納税で人気の"), s!.top!);
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
    // 空き家には別荘や入居者を募集中の賃貸住宅も含まれる。人口が減っていない地域（別荘地など）では、使われなくなった家とは書かない
    const change = stat("population_change_rate");
    const head = `空き家率が${s!.text}と全国でも高い方です（${s!.label}）。`;
    // 4割を超えるのは別荘地・リゾート地（軽井沢町・熱海市など）。人口が減っていても、使われなくなった家とは書かない
    if (s!.value >= 40) return strong(head + "別荘やリゾートマンションなど、ふだん人が住んでいない住宅が多い地域と考えられます。");
    if (!change) return strong(head + "別荘や入居者を募集中の賃貸住宅、長く使われていない家など、ふだん人が住んでいない住宅が多いようです。");
    if (change.value >= 0) {
      return strong(head + "人口は減っていないので、別荘や入居者を募集中の賃貸住宅など、ふだん人が住んでいない住宅が多いと考えられます。");
    }
    return strong(head + "空き家には別荘や賃貸用の住宅も含まれますが、人口も減っていることから、長く使われていない家も多いと考えられます。", "neg");
  }

  function education(): Line | null {
    const univ = stat("hs_grad_university_rate");
    if (isTop(univ, 0.1)) {
      return strong(`まちにある高校の卒業者のうち大学などに進んだ人が${univ!.text}と全国でも高い方です（${univ!.label}、学校の所在地で数えています）。進学を目指す高校が多い地域のようです。`);
    }
    // 就職した人が多い方は、進学の少なさ（学歴）として読まれかねないので書かない（設計変更記録 #133）
    return null;
  }

  // --- 土地（面積・標高・土地利用・植生・農地の区画）と財政 ---

  function jpn(n: number) { return n.toLocaleString("ja-JP"); }
  /** 全国の上位・下位2%（全国順位の考察と同じ範囲）に入るときは、その位置を lead に記す */
  function leadIf(l: Line, pos: number | null | undefined): Line {
    if (pos !== null && pos !== undefined && pos <= RANK_SHARE) l.lead = pos;
    return l;
  }
  function meters(n: number) { return `${jpn(Math.round(n))}m`; }

  /** 面積。全国でも特に広い（上位1%）か、特に小さい（下位2%）とき */
  function areaSize(): Line | null {
    const s = stat("area");
    if (!s || s.top === null) return null;
    if (s.top <= 0.01) {
      const rank = s.rankTop === 1 ? "最も広い市区町村です" : `${jpn(s.rankTop)}番目の広さです`;
      return leadIf(strong(`面積は${s.text}で、全国の市区町村の中で${rank}（${s.label}）。広い市域に、まちの中心から山や農村まで、いろいろな土地を抱えていると考えられます。`,
        undefined, tag("wide", "広い市域を持ち", "広い市域を持つ"), s.top * 3), s.top);
    }
    if (s.bottom! <= 0.02) {
      return leadIf(strong(`面積は${s.text}で、全国の市区町村の中でも小さい方です（${s.label}）。まちの範囲がコンパクトにまとまっているようです。`,
        "pos", tag("compact", "コンパクトにまとまり", "コンパクトにまとまった"), s.bottom! * 3), s.bottom);
    }
    return null;
  }

  /**
   * 地形（平均標高と高低差。標高タイルの約30m間隔の点から）。高低差が全国で特に大きい（上位3%）、平均標高が500m以上、
   * 平均標高が全国で特に低い（3m以下）のどれか1つ。観測所の標高が高いときだけ、夏のすずしさにふれる
   */
  function terrain(): Line | null {
    const mean = stat("elevation_mean");
    const range = stat("elevation_range");
    if (!mean) return null;
    const w = place.weather;
    const cool = w && w.altitude !== null && w.altitude >= 500
      ? `気象庁の観測所「${w.station}」も標高${meters(w.altitude)}にあり、夏も比較的すずしい気候と思われます。` : "";
    if (range && range.top !== null && range.top <= 0.03) {
      return leadIf(strong(`まちの中の高低差（いちばん低い所と高い所の差）は${meters(range.value)}と、全国の市区町村の中でも大きい方です（平均標高は${meters(mean.value)}）。` +
        `平地から高い山々まで、変化に富んだ地形のまちと考えられます。${cool}`, undefined, tag("mountain", "高い山々を抱え", "高い山々を抱える"), range.top), range.top);
    }
    if (mean.value >= 500) {
      // 平均は山の上も含み、まちの中心は低い谷や盆地にあることも多い（盛岡市など）。題名は「標高が高い」とは書かず、
      // 平均が特に高い（700m以上）ときだけ「高原や山地が広がる」とする
      const wide = mean.value >= 700;
      const rank = mean.rankTop === 1 ? "全国の市区町村の中で最も高くなっています" : `全国の市区町村のうち${jpn(mean.rankTop)}番目の高さです`;
      return leadIf(strong(`まちの土地の平均標高は${meters(mean.value)}で、${rank}。土地の多くが高原や山地にあるまちのようです。${cool}`,
        undefined, wide ? tag("high", "高原や山地が広がり", "高原や山地の広がる") : undefined, wide ? Math.min(0.02, mean.top ?? 0.02) : 0.2), mean.top);
    }
    if (mean.value <= 3 && range && range.value <= 50) {
      return strong(`まちの土地の平均標高は${formatNumber(mean.value, 1)}mと${mean.value < 0 ? "海面より低く" : "低く"}、高低差も${meters(range.value)}ほどの平らな土地です。` +
        "低い平野に広がるまちのようです。", undefined, tag("flat", "平らな低地に広がり", "平らな低地に広がる"), 0.05);
    }
    return null;
  }

  /**
   * 土地利用（土地利用細分メッシュ）と植生。森林・田・畑のうち全国で特に割合の高いものを1つ。
   * 森林は、植生図で自然林か植林地が特に多いときにその違いも書く
   */
  function landUse(): Line[] {
    const forest = stat("land_use_forest_share");
    const paddy = stat("land_use_paddy_share");
    const field = stat("land_use_field_share");
    const options: { pos: number; line: () => Line }[] = [];
    if (forest && forest.top !== null && forest.top <= 0.1) {
      options.push({ pos: forest.top, line: () => {
        const natural = stat("vegetation_natural_forest_share");
        const planted = stat("vegetation_plantation_share");
        const detail = natural && natural.top !== null && natural.top <= 0.05
          ? `植生図では土地の${natural.text}が自然林で（${natural.label}）、昔からの森が多く残っている地域と考えられます。`
          : planted && planted.top !== null && planted.top <= 0.05
            ? `植生図では土地の${planted.text}が、スギ・ヒノキやカラマツなどを植えた植林地で（${planted.label}）、木材をとるために植えられた森が多い地域と考えられます。`
            : "";
        return leadIf(strong(`まちの土地の${forest.text}が森林で（${forest.label}）、全国の市区町村の中でも森林の多い方です。${detail}`,
          undefined, tag("forest", "森に囲まれ", "森に囲まれた"), forest.top!), forest.top);
      } });
    }
    if (paddy && paddy.top !== null && paddy.top <= 0.05) {
      options.push({ pos: paddy.top, line: () => leadIf(strong(`まちの土地の${paddy.text}が田で（${paddy.label}）、全国の市区町村の中でも田の割合が高い方です。一面に田んぼが広がる地域と考えられます。`,
        "pos", tag("agri", "田んぼが広がり", "田んぼの広がる"), paddy.top!), paddy.top) });
    }
    if (field && field.top !== null && field.top <= 0.05) {
      options.push({ pos: field.top, line: () => leadIf(strong(`まちの土地の${field.text}が畑や果樹園、牧草地などで（${field.label}）、全国の市区町村の中でも割合が高い方です。` +
        "畑作や酪農など、田んぼ以外の農業が盛んな地域と考えられます。", "pos", tag("agri", "畑や牧草地が広がり", "畑や牧草地の広がる"), field.top!), field.top) });
    }
    const best = options.sort((a, b) => a.pos - b.pos)[0];
    return best ? [best.line()] : [];
  }

  /** 農地の1区画の平均面積（筆ポリゴン）。全国で特に広い（上位5%）とき */
  function farmland(): Line | null {
    const s = stat("farmland_parcel_area");
    if (!s || s.top === null || s.top > 0.05) return null;
    const share = (stat("farmland_paddy_share")?.value ?? 0) + (stat("farmland_field_share")?.value ?? 0);
    if (share < 10) return null;
    const ha = s.value >= 10_000 ? `約${formatNumber(s.value / 10_000, 1)}ha` : s.text;
    return leadIf(strong(`農地の1区画の平均面積は${ha}と、全国の市区町村の中でも広い方です（${s.label}の筆ポリゴン）。大きな区画で機械を使う、規模の大きな農業が行われていると考えられます。`,
      "pos", tag("bigfarm", "大きな区画の田畑が広がり", "大きな区画の田畑が広がる"), s.top), s.top);
  }

  /**
   * 建物用地の割合の30年間の変化（1991→2021年度）。20ポイント以上増え、途中の年度も増え続け、
   * 2010年からの人口も増えているときだけ（年度で判読の方法が違うため、ほかの裏付けがあるときに限る）
   */
  function landChange(): Line | null {
    const ind = data.indicator("land_use_building_share");
    if (!ind) return null;
    const periods = ind.periods.map((p) => p.period).sort().filter((p) => p >= "1991");
    const vals = periods.map((p) => stat("land_use_building_share", p));
    if (vals.length < 3 || vals.some((v) => !v)) return null;
    const first = vals[0]!, last = vals[vals.length - 1]!;
    if (last.value - first.value < 20 || vals.some((v, i) => i > 0 && v!.value < vals[i - 1]!.value)) return null;
    if (!sinceLong()) return null;
    return strong(`建物の建つ土地（建物用地）の割合は、${first.label.slice(0, 4)}年度の${first.text}から${last.label.slice(0, 4)}年度は${last.text}に増えました。` +
      "この30年で田畑や林が住宅地などに変わり、まちが広がってきたと考えられます（年度によって判読の方法が違うため、数字には判読の違いも含まれます）。",
      "pos", tag("develop", "新しい街並みが広がり", "街並みが広がってきた"), 0.08);
  }

  /** 竹林（植生図）。全国で特に多い（上位2%）とき。どの地域にもある話題ではないので一般的な考察として */
  function bamboo(): Line | null {
    const s = stat("vegetation_bamboo_share");
    if (!s || s.top === null || s.top > 0.02) return null;
    return general(`植生図では土地の${s.text}が竹林で（${s.label}）、全国の市区町村の中でも竹林の多い方です。竹林のある里山の風景が身近な地域のようです。`, undefined, undefined, 0.3);
  }

  /**
   * 財政力指数が1以上のときだけ（自前の収入で標準的な行政サービスの費用をまかなえる水準）。
   * 自治体の良し悪しの評価にならないよう、指標の意味を書くだけにし、低い方・借金などの指標は書かない
   */
  function fiscal(): Line | null {
    const s = stat("fiscal_strength_index");
    if (!s || s.value < 1) return null;
    // 理由は、ほかの指標で裏付けられるときだけ書く（工場が多い・昼に人が集まる職場が多い・住む人の所得が高い）
    const why = isTop(stat("manufacturing_shipments"), 0.1) ? "工場など企業からの税収が多いことが表れていると考えられます。"
      : !evacuated && (stat("daytime_night_ratio")?.value ?? 0) >= 130 ? "周りから人が通う職場が多く、企業や事業所からの税収が多いことが表れていると考えられます。"
      : isTop(stat("taxable_income_per_taxpayer"), 0.1) ? "所得の高い住民が多く、住民税の収入が多いことが表れていると考えられます。"
      : "税収など自前の収入が多いようです。";
    return leadIf(strong(`財政力指数は${s.text}で（${s.label}、3年度の平均）、全国の市区町村のうち${jpn(s.rankTop)}位です。1以上は、標準的な行政サービスの費用を自前の収入でまかなえる水準とされ、` +
      `国から普通交付税を受けないことが多くなります。${why}`, undefined, undefined, Math.max(0.03, s.top ?? 0.03)), s.top);
  }

  // --- 点のデータ（駅・空港・港・地価公示・天気） ---

  /** 空港。年に1,000人以上が乗り降りする空港があるときだけ */
  function airport(): Line | null {
    const a = place.airport;
    if (!a || a.value < 1000) return null;
    const name = /(空港|飛行場|ヘリポート)$/.test(a.name) ? a.name : `${a.name}空港`;
    const head = `まちには${name}があり、${a.label}は${approxCount(a.value)}が飛行機に乗り降りしました。`;
    const why = a.international >= a.value * 0.2 ? "国際線の利用も多く、海外との行き来の玄関口にもなっているようです。"
      : a.pos.top <= 0.1 ? "全国でも利用者の多い空港で、空の玄関口になっていると考えられます。"
      : "遠くのまちとの行き来を、飛行機が支えていると考えられます。";
    return strong(head + why, "pos", tag("airport", "空港があり", "空港のある"), 0.01);
  }

  /** 港。全国の港の中で利用者の多い方（上位半分）のときだけ */
  function port(): Line | null {
    const x = place.port;
    if (!x || x.pos.top > 0.5) return null;
    const name = /港$/.test(x.name) ? x.name : `${x.name}港`;
    const why = x.pos.top <= 0.1 ? "全国でも船の利用者が多い港で、島への航路や観光の船など、海の玄関口になっていると考えられます。"
      : "島への航路や観光の船など、船が暮らしや観光を支えているようです。";
    return strong(`${name}では、${x.label}に${approxCount(x.value)}が船に乗り降りしました。${why}`, "pos",
      tag("port", "港に船が行き交い", "船が行き交う港のある"), x.pos.top / 5);
  }

  function stationName(n: string) { return /駅$/.test(n) ? n : `${n}駅`; }
  function stationNote(st: NonNullable<MuniPlaces["station"]>) { return `${st.label}${st.operators > 1 ? `、${st.operators}事業者の合計` : ""}`; }

  /** 駅。まちでいちばん利用者の多い駅が、全国の市区町村の中で上位30%に入るとき */
  function station(): Line | null {
    const st = place.station;
    if (!st || st.pos.top > 0.3) return null;
    const head = `まちでいちばん利用者の多い駅は${stationName(st.name)}で、1日に${approxCount(st.total)}が乗り降りしています（${stationNote(st)}）。`;
    if (st.pos.top <= 0.03) {
      return strong(head + "全国の市区町村の中でも特に利用者の多い駅で、通勤・通学や乗り換えの拠点になっていると考えられます。", "pos",
        tag("station", "多くの人が使う駅があり", "多くの人が使う駅のある"), st.pos.top);
    }
    return general(head + "まちの玄関口として、多くの人が使う駅のようです。", "pos",
      st.pos.top <= 0.1 ? tag("station", "多くの人が使う駅があり", "多くの人が使う駅のある") : undefined, st.pos.top);
  }

  /** 駅（上の条件に当てはまらないとき）。駅の数と、いちばん利用者の多い駅 */
  function stationGeneral(): Line | null {
    const st = place.station;
    if (!st || st.pos.top <= 0.3) return null;
    const head = st.stationCount > 1 ? `まちには鉄道の駅が${st.stationCount}駅あり、いちばん利用者の多い${stationName(st.name)}では`
      : `まちの鉄道の駅は${stationName(st.name)}で、`;
    return general(`${head}1日に${approxCount(st.total)}が乗り降りしています（${stationNote(st)}）。`);
  }

  /** 天気（気象庁の観測所の平年値）。雪・日照・雨のうち全国の観測所の中で特に目立つものを1つと、観測所の標高 */
  function weather(): Line[] {
    const w = place.weather;
    if (!w) return [];
    const out: Line[] = [];
    const v = w.values;
    const where = (e: string) => `（気象庁の観測所「${v[e].station}」、${w.label}）`;
    const fmt = (n: number) => Math.round(n).toLocaleString("ja-JP");
    const options: { pos: number; line: () => Line }[] = [];
    if (v.snowfall_normal && v.snowfall_normal.value >= 300 && v.snowfall_normal.pos.top <= 0.2) {
      options.push({ pos: v.snowfall_normal.pos.top, line: () => strong(`年間の降雪量は${fmt(v.snowfall_normal.value)}cm${where("snowfall_normal")}と、全国の観測所の中でも多い方です。` +
        "冬は雪とともに暮らす、雪国のまちと考えられます。", undefined, tag("snow", "雪が多く", "雪の多い"), v.snowfall_normal.pos.top / 2) });
    }
    if (v.sunshine_normal && v.sunshine_normal.pos.top <= 0.1) {
      options.push({ pos: v.sunshine_normal.pos.top, line: () => strong(`日照時間は年間${fmt(v.sunshine_normal.value)}時間${where("sunshine_normal")}と、全国の観測所の中でも長い方です。` +
        "晴れの日が多い地域のようです。", "pos", tag("sun", "晴れの日が多く", "晴れの日が多い"), v.sunshine_normal.pos.top) });
    }
    if (v.precipitation_normal && v.precipitation_normal.pos.top <= 0.1) {
      options.push({ pos: v.precipitation_normal.pos.top, line: () => strong(`年間の降水量は${fmt(v.precipitation_normal.value)}mm${where("precipitation_normal")}と、全国の観測所の中でも多い方です。` +
        "雨の多い気候で、水や緑の豊かな地域と考えられます。", undefined, tag("rain", "雨が多く", "雨の多い"), v.precipitation_normal.pos.top) });
    }
    if (v.precipitation_normal && v.precipitation_normal.pos.bottom <= 0.1) {
      options.push({ pos: v.precipitation_normal.pos.bottom, line: () => strong(`年間の降水量は${fmt(v.precipitation_normal.value)}mm${where("precipitation_normal")}と、全国の観測所の中でも少ない方です。` +
        "雨の少ない気候のようです。", "pos", tag("dry", "雨が少なく", "雨の少ない"), v.precipitation_normal.pos.bottom) });
    }
    const best = options.sort((a, b) => a.pos - b.pos)[0];
    if (best) out.push({ ...best.line(), topic: "weather" });
    // 市区町村の平均標高があるときは、そちら（terrain）で書く（観測所1地点より、まちの土地全体を表すため）
    if (w.altitude !== null && w.altitude >= 500 && !stat("elevation_mean")) {
      out.push({ ...strong(`気象庁の観測所「${w.station}」は標高${fmt(w.altitude)}mにあり、高原や山あいのまちと考えられます。夏も比較的すずしい気候と思われます。`,
        undefined, tag("high", "標高が高く", "高原や山あいの"), 0.02), topic: "altitude" });
    }
    return out;
  }

  function yen(n: number) { return n >= 10_000 ? `約${(Math.round(n / 1_000) / 10).toLocaleString("ja-JP")}万円` : `${Math.round(n).toLocaleString("ja-JP")}円`; }
  function day(label: string) { return label.replace(/現在$/, ""); }

  /** 地価公示（住宅地）。価格が全国の市区町村の上位5%か、5年間の上がり方が上位5%のとき */
  function landPrice(): Line | null {
    const l = place.land;
    if (!l) return null;
    const c = l.change;
    if (c && c.pos.top <= 0.05 && c.rate >= 10) {
      return strong(`住宅地の地価公示の価格は、同じ地点で比べると${day(c.from)}から${formatNumber(c.rate, 1)}%上がっていて（${c.points}地点の中央値）、` +
        "全国の市区町村の中でも上がり方が大きい方です。住宅の開発や交通の便の向上などで、住まいとしての人気が高まっていると考えられます。",
        "pos", tag("landup", "地価が上がり", "地価が上がっている"), c.pos.top * 2);
    }
    if (l.pos.top <= 0.05) {
      return strong(`住宅地の地価公示の価格は、まちの${l.points}地点の中央値で1㎡あたり${yen(l.median)}（${l.label}）と、全国の市区町村の中でも高い方です。` +
        "住まいとしての人気が高い地域と考えられます。", undefined, tag("land", "住宅地の人気が高く", "住宅地の人気が高い"), l.pos.top);
    }
    return null;
  }

  /** 地価公示（住宅地）の価格と5年間の変化（上の条件に当てはまらないとき） */
  function landGeneral(): Line | null {
    const l = place.land;
    if (!l || l.pos.top <= 0.05 || (l.change && l.change.pos.top <= 0.05 && l.change.rate >= 10)) return null;
    const c = l.change;
    const change = c ? `同じ地点で比べた${day(c.from)}からの変化は${c.rate > 0 ? "+" : ""}${formatNumber(c.rate, 1)}%です。` : "";
    return general(`住宅地の${l.survey ? "都道府県地価調査" : "地価公示"}の価格は、まちの${l.points}地点の中央値で1㎡あたり${yen(l.median)}です（${l.label}）。${change}`);
  }
}
