// 地域ページの「〇〇の町丁目別ランキング」の表の中身（設計変更記録 #142）。
// 表を書く components/SmallAreaRanking.astro と、表があるときだけ目次に入れる地域ページ（#193）の両方で使う
import { loadIndicators, loadSmallAreaRowsByMunicipality, loadSmallAreas } from "./data";
import { latestSmallAreaPeriod, SMALL_AREA_TABLES, topSmallAreas } from "./smallAreaRanking";
import type { Municipality } from "./types";

export function smallAreaTables(muni: Municipality) {
  const code = muni.id.slice(5);
  const names = new Map((loadSmallAreas(code) ?? []).map((a) => [a.id, a.name]));
  const indicators = new Map(loadIndicators().map((i) => [i.id, i]));
  const tables = SMALL_AREA_TABLES.flatMap((spec) => {
    const ind = indicators.get(spec.id);
    const period = ind && latestSmallAreaPeriod(ind);
    if (!ind || !period) return [];
    const rows = loadSmallAreaRowsByMunicipality(ind.id, period.period, muni.prefecture).get(code) ?? [];
    const top = topSmallAreas(rows, spec.positiveOnly).filter((r) => names.has(r.entity_id));
    return top.length ? [{ spec, ind, period, rows: top }] : [];
  });
  return { names, tables };
}
