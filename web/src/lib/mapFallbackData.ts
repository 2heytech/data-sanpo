// 地図を表示できないときの案内（設計変更記録 #196）に使うデータを、ビルドのときに公開版のデータから作る。
// pages/map/fallback.json.ts が書き出し、地図のページは既定の指標の分をページに書いておく（ファイルを読めなくても案内が出るように）
import { loadAreas, loadIndicators } from "./data";
import type { MapFallbackData } from "./mapFallback";
import { indicatorPageImage } from "./shareImages";

let cached: MapFallbackData | null = null;

export function mapFallbackData(): MapFallbackData {
  if (cached) return cached;
  const indicators = loadIndicators();
  const areas = loadAreas();
  cached = {
    default: indicators[0]?.id ?? "",
    indicators: Object.fromEntries(indicators.map((ind) => {
      const image = indicatorPageImage(ind);
      return [ind.id, { name: ind.name, ...(image ? { image: { path: image.path, alt: image.alt } } : {}) }];
    })),
    prefectures: Object.fromEntries(areas.prefectures.map((p) => [p.code, p.name])),
    municipalities: Object.fromEntries(areas.municipalities.map((m) => [m.id, m.name])),
  };
  return cached;
}
