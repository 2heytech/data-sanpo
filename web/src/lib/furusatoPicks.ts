// 楽天ふるさと納税で返礼品を探すリンクを、見つけやすくし、載せるページを増やす（設計変更記録 #252、#189・#195 に足す）。
// 地域ページの欄の最初の1文（受入額と順位）と、指標ページ・都道府県ページ・寄り道に置く「上位のまちの返礼品」の箱の中身を作る。
// アフィリエイトID がなければリンクを作らず、箱も出さない。順位は上位のときだけ書き、低い順位は書かない
import { formatNumber } from "./format";
import { rakutenAffiliateUrl, rakutenFurusatoSearchUrl } from "./rakuten";

export interface FurusatoPick {
  /** 「1位」など */
  label: string;
  name: string;
  /** 名前の横に小さく添える言葉（都道府県名・受入額） */
  sub?: string;
  href: string;
}

export interface PickIndicator {
  /** 箱の見出し */
  heading: string;
  /** 楽天の検索に足す言葉。そのまちの名産に近い品が出るようにする。品目が分かれる合計・畜産は足さない */
  keyword?: string;
  /** 文で数える地域の呼び方（農業の値は東京23区・政令指定都市の区にないので「市町村」） */
  areaWord: "市区町村" | "市町村";
}

/** 指標のページに箱を置く指標。返礼品と結びつくふるさと納税と農業産出額だけにする（関係のない指標には置かない） */
export const PICK_INDICATORS: Record<string, PickIndicator> = {
  furusato_amount: { heading: "受入額の多いまちの返礼品", areaWord: "市区町村" },
  furusato_count: { heading: "受入件数の多いまちの返礼品", areaWord: "市区町村" },
  furusato_amount_per_capita: { heading: "住民1人あたりの受入額が多いまちの返礼品", areaWord: "市区町村" },
  agri_output: { heading: "農業産出額の多いまちの返礼品", areaWord: "市町村" },
  agri_output_rice: { heading: "米の産出額が多いまちの返礼品", keyword: "米", areaWord: "市町村" },
  agri_output_vegetables: { heading: "野菜の産出額が多いまちの返礼品", keyword: "野菜", areaWord: "市町村" },
  agri_output_fruits: { heading: "果実の産出額が多いまちの返礼品", keyword: "果物", areaWord: "市町村" },
  agri_output_livestock: { heading: "畜産の産出額が多いまちの返礼品", areaWord: "市町村" },
};

/** 全国のランキングの箱に並べる数 */
export const PICK_COUNT = 10;
/** 都道府県のページ・県別のランキングの箱に並べる数（スマホの2列で3行） */
export const PREF_PICK_COUNT = 6;

export interface PickSource {
  label: string;
  name: string;
  /** 検索に使う都道府県名（同じ名前の市町村を見分ける） */
  pref: string;
  sub?: string;
}

/** 楽天の検索へのリンクを作る。ID がなければ空 */
export function furusatoPicks(items: PickSource[], keyword = ""): FurusatoPick[] {
  return items.flatMap((it) => {
    const href = rakutenAffiliateUrl(rakutenFurusatoSearchUrl(it.pref, it.name, keyword));
    return href ? [{ label: it.label, name: it.name, sub: it.sub, href }] : [];
  });
}

/** 箱の説明の1文（「果実の産出額の上位10の市町村で、果物の返礼品を楽天ふるさと納税で探せます。」） */
export function pickLead(indicatorName: string, conf: PickIndicator, n: number, scope = ""): string {
  const top = `${scope}${indicatorName}の上位${n}の${conf.areaWord}`;
  return conf.keyword ? `${top}で、${conf.keyword}の返礼品を楽天ふるさと納税で探せます。` : `${top}の返礼品を、楽天ふるさと納税で探せます。`;
}

/** 百万円の受入額を「約216億円」「約3.8億円」「約2,530万円」の形に。値がない・0以下なら null */
export function furusatoAmountText(millionYen: number | null | undefined): string | null {
  if (millionYen == null || !(millionYen > 0)) return null;
  if (millionYen >= 1000) return `約${formatNumber(Math.round(millionYen / 100), 0)}億円`;
  if (millionYen >= 100) {
    const oku = Math.round(millionYen / 10) / 10;
    return `約${formatNumber(oku, Number.isInteger(oku) ? 0 : 1)}億円`;
  }
  const man = Math.round(millionYen * 100);
  return man > 0 ? `約${formatNumber(man, 0)}万円` : null;
}

export interface Standing { rank: number; total: number }

/** 全国の順位を書くのは上位100位まで、都道府県の中の順位を書くのは3位まで（5市区町村以上の都道府県） */
export const AREA_NATIONAL_TOP = 100;
export const AREA_PREF_TOP = 3;
/** 都道府県のページで都道府県の順位を書くのは10位まで */
export const PREF_TOP = 10;

/** 地域ページの欄の最初の1文。「都城市のふるさと納税の受入額は約216億円で、全国1,720市区町村のうち3位です（2025年度）。」 */
export function furusatoAreaLead(o: {
  name: string; prefName: string; value: number | null | undefined; periodLabel: string;
  national: Standing | null; inPref: Standing | null;
}): string | null {
  const amount = furusatoAmountText(o.value);
  if (!amount) return null;
  const rank = o.national && o.national.rank <= AREA_NATIONAL_TOP
    ? `全国${formatNumber(o.national.total, 0)}市区町村のうち${formatNumber(o.national.rank, 0)}位`
    : o.inPref && o.inPref.rank <= AREA_PREF_TOP && o.inPref.total >= 5
      ? `${o.prefName}の${formatNumber(o.inPref.total, 0)}市区町村のうち${o.inPref.rank}位`
      : null;
  return `${o.name}のふるさと納税の受入額は${amount}${rank ? `で、${rank}` : ""}です（${o.periodLabel}）。`;
}

/** 都道府県のページの欄の最初の1文。都道府県の値は、県（都・道・府）自身と県内の市区町村の受入の合計 */
export function furusatoPrefLead(o: { prefName: string; value: number | null | undefined; periodLabel: string; standing: Standing | null }): string | null {
  const amount = furusatoAmountText(o.value);
  if (!amount) return null;
  const s = o.prefName.slice(-1);
  const rank = o.standing && o.standing.rank <= PREF_TOP ? `で、都道府県の${o.standing.rank}位` : "";
  return `${o.prefName}（${s}と${s}内の市区町村の合計）のふるさと納税の受入額は${amount}${rank}です（${o.periodLabel}）。`;
}
