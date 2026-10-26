// 市区町村・都道府県の「あらまし」（設計変更記録 #164）。自治体の公式サイトや資料で確かめた事実を、データさんぽの言葉で3〜5文にまとめたもの。
// 資料の文は写さず、推測は書かない（推測はデータから考えられることの方に書く）。出典と確かめた日を必ず添える
// データは都道府県ごとのファイル（web/src/data/aramashi/<都道府県コード>.json）に分ける（設計変更記録 #166）

export interface AramashiSource { publisher: string; title: string; url: string }
export interface Aramashi { text: string[]; sources: AramashiSource[]; checked: string }

const FILES = import.meta.glob<{ areas: Record<string, Aramashi> }>("../data/aramashi/*.json", { eager: true, import: "default" });
const BY_PREF: [string, Record<string, Aramashi>][] = Object.entries(FILES).map(([path, f]) => [path.replace(/^.*\/(\d{2})\.json$/, "$1"), f.areas]);
const AREAS: Record<string, Aramashi> = Object.assign({}, ...BY_PREF.map(([, areas]) => areas));

/** 地域（muni-XXXXX・pref-XX）のあらまし。まだ書いていない地域は null */
export function aramashiOf(id: string): Aramashi | null {
  return AREAS[id] ?? null;
}

/** すべてのあらまし（テストで中身を確かめるため） */
export function allAramashi(): [string, Aramashi][] {
  return Object.entries(AREAS);
}

/** ファイルごとの都道府県コードと、そこに書いた地域（テストで、ほかの県の地域が紛れていないか確かめるため） */
export function aramashiFiles(): [string, string[]][] {
  return BY_PREF.map(([code, areas]) => [code, Object.keys(areas)]);
}

/** 確かめた日（2026-10-24）を「2026年10月24日」と書く */
export function checkedLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return `${y}年${m}月${d}日`;
}
