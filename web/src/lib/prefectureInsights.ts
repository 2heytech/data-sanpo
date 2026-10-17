import { composeProfile, themeOf, type AreaProfile, type Line, type Theme } from "./areaInsights";
import { formatNumber, formatValue } from "./format";
import { prefecturePeriods } from "./periods";
import { nationalityTemplate, RANK_TEMPLATES, tag, type RankTemplate, type Tag, type Tone } from "./rankInsights";
import type { Indicator, ValueRow } from "./types";

/**
 * 都道府県ページ「データで見る〇〇県」の考察と、特徴を一言で表す題名（設計変更記録 #140）。
 * 市区町村の考察（areaInsights）と同じ決まりで書く: 推測は「〜と思われます」「〜と考えられます」「〜ようです」、
 * 地域や住む人を悪く言うように読める文（犯罪が多い、所得や学歴が低い、寿命が短いなど）は作らない、課題に当たる文は3つまで、
 * 国籍は題名に使わない、値がない指標は使わない（0 として扱わない）。
 * 全国47都道府県の中の順位で、上位・下位3位までに入る指標を目立つ特徴として書く。
 */
export interface PrefInsightData {
  indicator(id: string): Indicator | undefined;
  /** すべての指標（全国の順位で目立つ指標を探すのに使う） */
  indicators(): Indicator[];
  /** 指標の都道府県の値（47都道府県） */
  rows(id: string, period: string): ValueRow[];
}

interface Stat {
  ind: Indicator;
  period: string;
  label: string;
  value: number;
  text: string;
  /** 大きい方からの順位（同じ値は同じ順位）、小さい方からの順位、値のある都道府県の数、同じ値の都道府県の数（自分を含む） */
  rankTop: number;
  rankBottom: number;
  total: number;
  /** 公開している都道府県の数（値のない都道府県を含む） */
  count: number;
  same: number;
  /** 全国の中の位置（0〜1）。同じ値の都道府県は全部を数えた位置にする */
  top: number;
  bottom: number;
  /** ほかの都道府県と違う値があるか（すべて同じ値なら順位を書かない） */
  varied: boolean;
}

/** 全国の順位で目立つとみなす範囲（上位・下位それぞれこの順位まで） */
const RANK_LIMIT = 3;
/** 考察が少ない都道府県のために、一般的な考察として書く範囲（上位・下位それぞれこの順位まで） */
const GENERAL_LIMIT = 5;
/** 値のある都道府県がこの数より少ない指標は、全国の中の順位を書かない（一部の都道府県だけの指標のため） */
const MIN_PREFECTURES = 40;
/** 考察がこの数より少ない都道府県は、全国の上位・下位 FILL_LIMIT 位までの指標で足す（選挙・国籍・課題に当たる文は足さない） */
const MIN_LINES = 4;
const FILL_LIMIT = 10;
/** 全国の順位の考察で、同じ値の都道府県がこの数まではあっても書く（平均寿命など、値の刻みが粗い指標のため） */
const MAX_SAME = 3;
/** 良いところを探す範囲（全国の上位・下位それぞれ全体のこの割合まで） */
const BRIGHT_SHARE = 0.25;

/**
 * 全国の順位の考察の文。市区町村の文（RANK_TEMPLATES）が都道府県にも合うものはそのまま使い、
 * 合わないもの・都道府県で足すものはここで決める。null は都道府県では書かない指標（下の処理で別に書くものを含む）
 */
const PREF_TEMPLATES: Record<string, RankTemplate | null> = {
  population_density: { ...RANK_TEMPLATES.population_density, low: "山林や農地が広く、土地の広さに比べて住む人の少ない地域と考えられます。" },
  persons_per_household: { ...RANK_TEMPLATES.persons_per_household, highTag: tag("family", "大家族が多く", "大家族の多い"),
    high: "三世代で暮らす家族など、大きな世帯が多いと考えられます。" },
  single_person_household_share: { high: "単身で働く人や学生などが多く住んでいると思われます。" },
  owner_occupied_share: { highTag: tag("settled", "持ち家が多く", "持ち家の多い"), high: "長く住み続ける人の多い地域と考えられます。", highTone: "pos",
    lowTag: tag("rent", "借家に住む人が多く", "借家に住む人の多い"), low: "借家や賃貸マンションに住む人が多い地域のようです。" },
  commute_rail_share: { highTag: tag("rail", "鉄道で通いやすく", "鉄道網の発達した"), high: "鉄道で通勤・通学する人が多く、鉄道網の発達した地域と考えられます。" },
  commute_bicycle_share: { highTag: RANK_TEMPLATES.commute_bicycle_share.highTag, high: "自転車で通勤・通学する人が多い地域のようです。" },
  // 都道府県全体では鉄道で通う人も多いことがあるので、「鉄道より」とは書かない
  commute_bus_share: { highTag: tag("bus", "路線バスがよく使われ", "路線バスがよく使われる"), high: "路線バスで通勤・通学する人が多い地域のようです。" },
  commute_car_share: { ...RANK_TEMPLATES.commute_car_share, highTag: tag("car", "車が暮らしの足となり", "車が暮らしの足となる"),
    high: "車が欠かせない暮らしの地域と思われます。" },
  hs_grad_university_rate: { high: "高校を卒業して、大学などへ進学する人が多い地域のようです。" },
  hs_grad_vocational_rate: { high: "高校を卒業して、専門学校で資格や技術を身につける進路を選ぶ人が多いようです。" },
  // 低い方の「都市部などで低くなりやすい」は市区町村の人口密度で確かめる文なので、都道府県では高い方だけ
  total_fertility_rate: { highTag: RANK_TEMPLATES.total_fertility_rate.highTag, high: RANK_TEMPLATES.total_fertility_rate.high, highTone: "pos" },
  crime_npa_total_per_100_residents: { lowTag: tag("calm", "犯罪の件数が少なく", "落ち着いた"),
    low: "住民の数に比べて犯罪の件数が少ない、落ち着いた地域のようです。", lowTone: "pos" },
  household_income_1000plus_share: { high: "所得の高い世帯が比較的多く住んでいると思われます。" },
  furusato_amount_per_capita: { highTag: tag("furusato", "ふるさと納税で人気を集め", "ふるさと納税で人気の"),
    high: "返礼品などで人気を集める市町村が多いようです。", highTone: "pos" },
  land_price_residential: { high: "住まいの需要が高い地域と考えられます。" },
  employees_commerce_share: { high: "卸売業・小売業が地域を支える産業の1つのようです。" },
  farmland_parcel_area: { highTag: tag("bigfarm", "大きな区画の田畑が広がり", "大きな区画の田畑が広がる"),
    high: "大きな区画で機械を使う、規模の大きな農業が行われていると考えられます。", highTone: "pos" },
  vegetation_bamboo_share: { high: "竹林のある里山の風景が身近な地域のようです。" },
  vegetation_natural_forest_share: { highTag: tag("forest", "豊かな自然が残り", "豊かな自然の残る"),
    high: "ブナ林など、もともとの自然の林が多く残る地域と考えられます。", highTone: "pos" },
  vegetation_secondary_forest_share: { highTag: tag("forest", "里山の林が広がり", "里山の林が広がる"),
    high: "コナラやアカマツなど、人が手を入れてきた里山の林が多い地域と考えられます。" },
  vegetation_plantation_share: { highTag: tag("forest", "スギやヒノキの林が広がり", "スギやヒノキの林が広がる"), high: "スギやヒノキなどを植えた林が多く、林業が営まれてきた地域と考えられます。" },
  university_student_share: { highTag: tag("campus", "大学が集まり", "大学の集まる"), high: "大学が多く、全国から学生が集まる地域と考えられます。" },
  // 4つの教科は同じ系統（gakuryoku）として1つだけ。低い方は書かない
  ...Object.fromEntries(["gakuryoku_elem_japanese", "gakuryoku_elem_math", "gakuryoku_jhs_japanese", "gakuryoku_jhs_math"].map((id) => [id,
    { highTag: tag("study", "子どもの学力が高く", "子どもの学力が高い"), high: "学んだことがしっかり身についている子どもが多いと考えられます。", highTone: "pos" as Tone }])),
  retail_sales_per_capita: { high: "お店での買い物が多い、商業の盛んな地域と考えられます。" },
  preschool_kodomoen_share: { ...RANK_TEMPLATES.preschool_kodomoen_share, highTag: tag("kodomoen", "認定こども園に通う子が多く", "認定こども園に通う子の多い") },
  // 徒歩で通う人の割合は、農家など職場と住まいが同じ人の多い地域でも高くなり、都道府県全体では「歩いて暮らせる」と読めないため書かない
  commute_walk_share: null,
  // 下の処理で書く（人口の増減・年齢構成・昼夜間人口・面積・地形・土地利用・産業の割合）
  population_change_rate: null, aged_65_plus_share: null, children_0_14_share: null, daytime_night_ratio: null, area: null,
  elevation_mean: null, land_use_forest_share: null, land_use_paddy_share: null, land_use_field_share: null, land_use_building_share: null,
  employees_manufacturing_share: null, employees_agriculture_share: null,
};
/** 指標の分類と違うテーマに置くもの（大学生の割合は分類が「通勤・通学」だが学びの話として、住宅地の地価は住まいの話として読む） */
const PREF_THEMES: Record<string, Theme> = { university_student_share: "子育てと学び", land_price_residential: "住まい" };
const prefThemeOf = (ind: Indicator): Theme => PREF_THEMES[ind.id] ?? themeOf(ind);
/** 文の頭に使う指標の名前を、都道府県の文に合わせて言い換えるもの */
const PREF_NAMES: Record<string, string> = {
  crime_npa_total_per_100_residents: "住民100人当たりの犯罪の認知件数",
};
/** 住む人の国籍の指標（題名や、考察が少ないときに足す文には使わない） */
const isOrigin = (id: string) => /^(census_foreign_|foreign_|zairyu_foreign_)/.test(id);
const templateOf = (ind: Indicator): RankTemplate | null =>
  ind.id in PREF_TEMPLATES ? PREF_TEMPLATES[ind.id] : RANK_TEMPLATES[ind.id] ?? nationalityTemplate(ind.id, ind.name);

export function prefectureProfile(prefCode: string, name: string, data: PrefInsightData): AreaProfile {
  const entity = `pref-${prefCode}`;
  // period を省くと、国勢調査の新しい回（2025年）を先に使い、その都道府県に値がなければ既定の時点を使う（市区町村と同じ。#118）
  const stat = (id: string, period?: string): Stat | null => {
    const ind = data.indicator(id);
    if (!ind) return null;
    for (const p of period ? [period] : prefecturePeriods(ind)) {
      const listed = data.rows(id, p);
      const rows = listed.filter((r) => r.value !== null);
      const row = rows.find((r) => r.entity_id === entity);
      if (!row) continue;
      const v = row.value as number;
      const values = rows.map((r) => r.value as number);
      const lt = values.filter((x) => x < v).length;
      const le = values.filter((x) => x <= v).length;
      const n = values.length;
      return {
        ind, period: p, value: v, text: formatValue(row, ind), label: ind.periods.find((x) => x.period === p)?.label ?? "",
        rankTop: n - le + 1, rankBottom: lt + 1, total: n, count: listed.length, same: le - lt, top: (n - lt) / n, bottom: le / n, varied: le - lt < n,
      };
    }
    return null;
  };
  // 全国の中で比べられる指標か（ほとんどの都道府県に値があり、値に違いがある）
  const comparable = (s: Stat | null): s is Stat => !!s && s.total >= MIN_PREFECTURES && s.varied;
  // 型の絞り込みはしない（false のときに null と見なされるため）。真のときは値があるので ! で読む
  const isTop = (s: Stat | null, rank = RANK_LIMIT): boolean => comparable(s) && s.rankTop <= rank && s.same === 1;
  const isBottom = (s: Stat | null, rank = RANK_LIMIT): boolean => comparable(s) && s.rankBottom <= rank && s.same === 1;
  // 上位・下位に入るときだけ値を返す（入らないときは null）
  const topOf = (s: Stat | null, rank = RANK_LIMIT): Stat | null => (isTop(s, rank) ? s : null);
  const bottomOf = (s: Stat | null, rank = RANK_LIMIT): Stat | null => (isBottom(s, rank) ? s : null);
  const jp = (n: number) => n.toLocaleString("ja-JP");
  // 「県内」「都内」「道内」「府内」
  const inside = `${name.slice(-1)}内`;
  const highest = (s: Stat, word: string) => (s.rankTop === 1 ? `最も${word}` : `${s.rankTop}番目に${word}`);
  const lowest = (s: Stat, word: string) => (s.rankBottom === 1 ? `最も${word}` : `${s.rankBottom}番目に${word}`);
  const line = (theme: Theme, topic: string, text: string, opts: { strong?: boolean; tone?: Tone; tag?: Tag; w: number }): Line =>
    ({ text, strong: opts.strong ?? true, tone: opts.tone, tag: opts.tag, w: opts.w, theme, topic });

  // 「全国47都道府県」。値のない都道府県があるとき（2025年の静岡県など）は、値のある数で数えたことを書く
  const among = (s: Stat) => (s.total < s.count ? `値のある全国${s.total}都道府県` : `全国${s.total}都道府県`);

  const own = [populationChange(), history(), ageStructure(), daytime(), areaSize(), terrain(), landUse(), industry()]
    .filter((l): l is Line => !!l);
  const ranked = rankCandidates();
  ranked.push(...fillCandidates(MIN_LINES - own.length - ranked.length));
  // 目立つ順（強い考察を先に）。同じ目立ち方なら、この都道府県向けに書いた文を先にする
  const byWeight = (a: Line, b: Line) => a.w - b.w;
  const rankLines = ranked.map((f) => line(f.theme, f.id, f.text,
    { strong: f.rank <= RANK_LIMIT, tone: f.tone, tag: f.pos <= 0.1 ? f.tag : undefined, w: f.pos }));
  const all = [...own, ...rankLines].sort((a, b) => Number(b.strong) - Number(a.strong) || byWeight(a, b));
  const extra = ranked.filter((f) => f.pos <= 0.1 && f.tag && f.tone !== "neg")
    .map((f) => line(f.theme, f.id, f.text, { tone: f.tone, tag: f.tag, w: f.pos }));
  const profile = composeProfile(all, { extra, bright: brightSide(), place: name });
  if (profile.title) return profile;
  // 題名にできる言い回しがないときは、全国の10位までの指標からも探す（選挙・国籍・課題に当たる文は使わない）
  const wider = allCandidates().filter((f) => f.rank <= FILL_LIMIT && f.tag && f.tone !== "neg" && f.theme !== "選挙" && !isOrigin(f.id))
    .slice(0, 1).map((f) => line(f.theme, f.id, f.text, { strong: false, tone: f.tone, tag: f.tag, w: f.pos }));
  if (!wider.length) return profile;
  // すでに考察に入っている文なら、その文に言い回しを付ける（同じ文を2回出さない）
  const withTag = all.map((l) => (l.text === wider[0].text ? { ...l, tag: wider[0].tag } : l));
  return composeProfile(withTag, { extra: wider, bright: brightSide(), place: name });

  /** 全国の中で比較的よい位置にある、良いところに当たる指標を1つ（課題に当たる文が多いときに入れる） */
  function brightSide(): Line[] {
    const best = [...allCandidates()].filter((f) => f.tone === "pos" && f.pos <= BRIGHT_SHARE).sort((a, b) => a.pos - b.pos)[0];
    return best ? [line(best.theme, best.id, best.text, { tone: "pos", w: best.pos })] : [];
  }

  /** 考察の文がある指標で、全国の上位・下位5位までに入るもの（同じ系統の指標は1つだけ。3位までを目立つ考察にする） */
  type Ranked = { id: string; pos: number; rank: number; group: string; text: string; tone?: Tone; tag?: Tag; theme: Theme };
  function rankCandidates(): Ranked[] {
    const seen = new Set<string>();
    return allCandidates().filter((f) => f.rank <= GENERAL_LIMIT)
      .filter((f) => !seen.has(f.group) && !!seen.add(f.group));
  }
  /** 考察が少ないときに足す、全国の上位・下位10位までの指標（目立つ考察にはしない） */
  function fillCandidates(count: number): Ranked[] {
    if (count <= 0) return [];
    const used = new Set(ranked.map((f) => f.group));
    return allCandidates().filter((f) => f.rank > GENERAL_LIMIT && f.rank <= FILL_LIMIT && f.tone !== "neg" && f.theme !== "選挙" && !isOrigin(f.id))
      .filter((f) => !used.has(f.group) && !!used.add(f.group)).slice(0, count);
  }
  function allCandidates(): Ranked[] {
    const found: Ranked[] = [];
    for (const ind of data.indicators()) {
      const t = templateOf(ind);
      if (!t) continue;
      const s = stat(ind.id);
      if (!comparable(s) || s.same > MAX_SAME) continue;
      if (t.minCountOf) {
        const n = data.rows(t.minCountOf, s.period).find((r) => r.entity_id === entity)?.value ?? null;
        if (n === null || n < (t.minCount ?? 0)) continue;
      }
      // 国籍別の外国人の割合は、住む人の0.1%以上で全国の3位までのときだけ（ごく少ない人数の違いで順位が付くため）
      if (ind.id.startsWith("census_foreign_") && (s.value < 0.1 || Math.min(s.rankTop, s.rankBottom) > RANK_LIMIT)) continue;
      const group = ind.family ?? ind.id;
      const head = `${PREF_NAMES[ind.id] ?? ind.name}は${s.text}で`;
      const label = s.same > 1 ? `${s.label}、${s.same}都道府県が同じ値` : s.label;
      if (t.high && s.top <= 0.5 && (!t.low || s.top <= s.bottom)) {
        found.push({ id: ind.id, pos: s.top, rank: s.rankTop, group, tone: t.highTone, tag: t.highTag, theme: prefThemeOf(ind),
          text: `${head}、${among(s)}のうち${s.rankTop}位です（${label}）。${t.high}` });
      } else if (t.low && s.bottom <= 0.5) {
        const where = s.rankBottom === 1 ? "最も低い値です" : `低い方から${s.rankBottom}番目です`;
        found.push({ id: ind.id, pos: s.bottom, rank: s.rankBottom, group, tone: t.lowTone, tag: t.lowTag, theme: prefThemeOf(ind),
          text: `${head}、${among(s)}の中で${where}（${label}）。${t.low}` });
      }
    }
    return found.sort((a, b) => a.pos - b.pos);
  }

  /** 人口の増減。増えているとき、減り方が全国で特に小さい・大きいときだけ（減っていることは冒頭の文に書くため） */
  function populationChange(): Line | null {
    const s = stat("population_change_rate");
    if (!comparable(s)) return null;
    const amount = s.text.replace(/^[+−-]/, "");
    if (s.value > 0) {
      const rows = data.rows("population_change_rate", s.period).filter((r) => r.value !== null && r.value > 0);
      const only = rows.length === 1 ? `全国の都道府県で人口が増えたのは${name}だけです。` : `人口が増えたのは全国で${rows.length}都道府県です。`;
      return line("住む人", "populationChange", `人口は5年前から${amount}増えていて（${s.label}）、${only}進学や仕事などで、ほかの地域から移り住む人が多いと考えられます。`,
        { tone: "pos", tag: tag("grow", "人口が増え", "人口が増えている"), w: s.top });
    }
    if (isTop(s, 5)) {
      return line("住む人", "populationChange", `人口は5年前から${amount}減っていますが（${s.label}）、全国の都道府県の中では${s.rankTop}番目に減り方が小さく、人口が比較的保たれている地域と考えられます。`,
        { strong: false, tone: "pos", w: 0.3 });
    }
    if (isBottom(s, 5)) {
      return line("住む人", "populationChange", `人口は5年前から${amount}減っていて（${s.label}）、全国の都道府県の中でも減り方が大きい方です。若い世代の転出や高齢化が進んでいると思われます。`,
        { tone: "neg", w: 0.1 });
    }
    return null;
  }

  /** 1920年（最初の国勢調査）からの100年の人口の移り変わり。全国より大きく増えた（3倍以上）ときだけ */
  function history(): Line | null {
    const ind = data.indicator("population_history");
    if (!ind) return null;
    const periods = ind.periods.filter((p) => p.levels.includes("prefecture")).map((p) => p.period).sort();
    const [first, last] = [periods[0], periods.at(-1)];
    if (!first || !last || first === last) return null;
    const sum = (p: string) => {
      const rows = data.rows(ind.id, p);
      return rows.length && rows.every((r) => r.value !== null) ? rows.reduce((a, r) => a + (r.value as number), 0) : null;
    };
    const a = stat(ind.id, first), b = stat(ind.id, last);
    const na = sum(first), nb = sum(last);
    if (!a || !b || a.value <= 0 || !na || !nb) return null;
    const ratio = b.value / a.value;
    if (ratio < 3) return null;
    const years = Number(last.slice(0, 4)) - Number(first.slice(0, 4));
    return line("住む人", "history", `国勢調査が始まった${first.slice(0, 4)}年の${a.text}から、${last.slice(0, 4)}年は${b.text}と、` +
      `${years}年で約${formatNumber(ratio, 1)}倍になりました（全国は約${formatNumber(nb / na, 1)}倍）。大都市やその周りに人が集まってきた、この${years}年の移り変わりが表れていると考えられます。`,
      { tone: "pos", w: 0.05 });
  }

  /** 年齢構成。子どもの割合が高い、65歳以上の割合が低い、高齢化が進んでいる、のどれか1つ */
  function ageStructure(): Line | null {
    const aged = stat("aged_65_plus_share");
    const kids = stat("children_0_14_share");
    const many = topOf(kids), young = bottomOf(aged), old = topOf(aged);
    if (many) {
      return line("住む人", "ageStructure", `15歳未満の子どもの割合は${many.text}で、全国の都道府県で${highest(many, "高く")}なっています（${many.label}）。子育て中の世帯が多く住んでいると思われます。`,
        { tone: "pos", tag: tag("kids", "子育て世代が多く", "子育て世代の多い"), w: many.top });
    }
    if (young) {
      return line("住む人", "ageStructure", `65歳以上の人の割合は${young.text}で、全国の都道府県で${lowest(young, "低く")}なっています（${young.label}）。働く世代や子育て世代が比較的多いようです。`,
        { tag: tag("young", "働く世代が多く", "働く世代の多い"), w: young.bottom });
    }
    if (old && kids && isBottom(kids, 10)) {
      return line("住む人", "ageStructure", `65歳以上の人が${old.text}、15歳未満の子どもが${kids.text}です（${old.label}）。全国の都道府県の中でも高齢化が進んだ地域と思われます。`,
        { tone: "neg", w: 0.1 });
    }
    return null;
  }

  /** 昼夜間人口比率。昼に人が集まる（上位で100%を大きく超える）か、周りの大都市へ通う人が多い（下位で95%以下）とき */
  function daytime(): Line | null {
    const s = stat("daytime_night_ratio");
    if (!comparable(s)) return null;
    const head = `昼間の人口は住んでいる人の${formatNumber(s.value, 1)}%で（${s.label}）`;
    if (isTop(s) && s.value >= 103) {
      return line("仕事と産業", "daytime", `${head}、全国の都道府県で${highest(s, "高く")}なっています。周りの地域から通勤・通学で人が集まる地域と思われます。`,
        { tone: "pos", tag: tag("hub", "周りから人が集まり", "周りから人が集まる"), w: s.top });
    }
    if (isBottom(s, 4) && s.value <= 95) {
      return line("仕事と産業", "daytime", `${head}、全国の都道府県で${lowest(s, "低く")}なっています。周りの大都市へ通勤・通学する人が多く、住宅地としての性格が強い地域と考えられます。`,
        { tag: tag("bed", "大都市への通勤圏にあり", "大都市への通勤圏にある"), w: s.bottom });
    }
    return null;
  }

  /** 面積。全国で特に広い・小さい（上位・下位3位まで）とき。広い方は日本の面積に占める割合も（47都道府県の合計から） */
  function areaSize(): Line | null {
    const s = stat("area");
    const wide = topOf(s), small = bottomOf(s);
    if (wide) {
      const rows = data.rows("area", wide.period);
      const total = rows.every((r) => r.value !== null) ? rows.reduce((a, r) => a + (r.value as number), 0) : 0;
      const share = total ? `、日本の面積の約${formatNumber((wide.value / total) * 100, 0)}%を占めます` : "なっています";
      return line("気候と土地", "area", `面積は${wide.text}で、全国の都道府県で${highest(wide, "広く")}${share}（${wide.label}）。`,
        { tag: tag("wide", "面積が広く", "面積の広い"), w: wide.top });
    }
    if (small) {
      return line("気候と土地", "area", `面積は${small.text}で、全国の都道府県で${lowest(small, "小さく")}なっています（${small.label}）。限られた土地に市街地や暮らしがまとまっている地域のようです。`,
        { tone: "pos", tag: tag("compact", "コンパクトにまとまり", "コンパクトにまとまった"), w: small.bottom });
    }
    return null;
  }

  /** 地形（平均標高）。全国で特に高い・低い（上位・下位3位まで）とき */
  function terrain(): Line | null {
    const s = stat("elevation_mean");
    const high = topOf(s), low = bottomOf(s);
    const m = (v: number) => `${jp(Math.round(v))}m`;
    if (high) {
      return line("気候と土地", "terrain", `土地の平均標高は${m(high.value)}で、全国の都道府県で${highest(high, "高く")}なっています。土地の多くを山地や高原が占める地域のようです。`,
        { tag: tag("mountain", "山々に囲まれ", "山々に囲まれた"), w: high.top });
    }
    if (low) {
      return line("気候と土地", "terrain", `土地の平均標高は${m(low.value)}で、全国の都道府県で${lowest(low, "低く")}なっています。高い山が少なく、なだらかな土地の多い地域のようです。`,
        { tag: tag("flat", "なだらかな土地が広がり", "なだらかな土地の広がる"), w: low.bottom });
    }
    return null;
  }

  /** 土地利用（土地利用細分メッシュ）。森林・田・畑・建物用地のうち、全国で特に割合の高い（上位3位まで）ものを1つ */
  function landUse(): Line | null {
    const options: { s: Stat | null; text: (s: Stat) => string; tone?: Tone; tag?: Tag }[] = [
      { s: stat("land_use_forest_share"), text: (s) => `土地の${s.text}が森林で（${s.label}）、全国の都道府県で${highest(s, "森林の割合が高く")}なっています。緑の豊かな地域と考えられます。`,
        tag: tag("forest", "森林が多く", "森林の多い") },
      { s: stat("land_use_paddy_share"), text: (s) => `土地の${s.text}が田で（${s.label}）、全国の都道府県で${highest(s, "田の割合が高く")}なっています。平野に田んぼが広がる、米づくりの盛んな地域と考えられます。`,
        tone: "pos", tag: tag("agri", "田んぼが広がり", "田んぼの広がる") },
      { s: stat("land_use_field_share"), text: (s) => `土地の${s.text}が畑や果樹園、牧草地などで（${s.label}）、全国の都道府県で${highest(s, "割合が高く")}なっています。畑作や酪農、果樹など、田んぼ以外の農業が盛んな地域と考えられます。`,
        tone: "pos", tag: tag("agri", "畑や牧草地が広がり", "畑や牧草地の広がる") },
      { s: stat("land_use_building_share"), text: (s) => `土地の${s.text}に建物が建っていて（建物用地、${s.label}）、全国の都道府県で${highest(s, "割合が高く")}なっています。市街地が広く続く地域と考えられます。` },
    ];
    const best = options.map((o) => ({ ...o, s: topOf(o.s) })).filter((o) => o.s).sort((a, b) => a.s!.top - b.s!.top)[0];
    return best ? line("気候と土地", "landuse", best.text(best.s!), { tone: best.tone, tag: best.tag, w: best.s!.top }) : null;
  }

  /** 産業（経済センサスの事業所で働く人の割合）。製造業・農林漁業のうち、全国で特に割合の高い（上位3位まで）ものを1つ */
  function industry(): Line | null {
    const mfg = topOf(stat("employees_manufacturing_share"));
    const agri = topOf(stat("employees_agriculture_share"));
    const head = (s: Stat, what: string) => `${inside}の事業所で働く人のうち${what}が${s.text}で（${s.label}）、全国の都道府県で${highest(s, "高い割合")}です。`;
    if (mfg && (!agri || mfg.top <= agri.top)) {
      return line("仕事と産業", "industry", `${head(mfg, "製造業")}工場の多い、ものづくりの盛んな地域と思われます。`,
        { tone: "pos", tag: tag("mfg", "ものづくりが盛んで", "ものづくりの盛んな"), w: mfg.top });
    }
    if (agri) {
      return line("仕事と産業", "industry", `${head(agri, "農林漁業")}農業や林業、漁業が暮らしを支える地域と思われます。`,
        { tone: "pos", tag: tag("agri", "農林漁業が盛んで", "農林漁業の盛んな"), w: agri.top });
    }
    return null;
  }
}
