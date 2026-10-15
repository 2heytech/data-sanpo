// 境界の GeoJSON から、ページに直接埋め込む小さな SVG の形（市区町村のマーク・位置図）を作る。
// 画像ファイルを増やさないよう、ビルド時に path の文字列にしてページに書く（無償枠のファイル数のため）。

type Ring = number[][];
export interface Geometry {
  type: "Polygon" | "MultiPolygon";
  coordinates: Ring[] | Ring[][];
}

const polygonsOf = (g: Geometry): Ring[][] =>
  g.type === "Polygon" ? [g.coordinates as Ring[]] : (g.coordinates as Ring[][]);

/** 外周の面積（経緯度のまま。大きさを比べるのにだけ使う） */
function ringArea(r: Ring): number {
  let a = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] + r[i][0]) * (r[j][1] - r[i][1]);
  return Math.abs(a / 2);
}

/** Douglas-Peucker で点を間引く（始点と終点は残す） */
function simplify(pts: number[][], tol: number): number[][] {
  if (pts.length <= 3) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack: [number, number][] = [[0, pts.length - 1]];
  while (stack.length) {
    const [s, e] = stack.pop()!;
    const [x1, y1] = pts[s], [x2, y2] = pts[e];
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
    let max = 0, idx = -1;
    for (let i = s + 1; i < e; i++) {
      const d = len === 0 ? Math.hypot(pts[i][0] - x1, pts[i][1] - y1)
        : Math.abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / len;
      if (d > max) { max = d; idx = i; }
    }
    if (max > tol && idx > 0) { keep[idx] = 1; stack.push([s, idx], [idx, e]); }
  }
  return pts.filter((_, i) => keep[i]);
}

export interface Frame {
  minX: number; minY: number; scale: number; width: number; height: number; cos: number;
  /** いちばん大きな島の、枠の中での大きさ（縦横の長い方、0〜1） */
  mainShare: number;
}

/**
 * 形を収める枠。小さな島を除いた（いちばん大きな島の minShare 未満の島は見ない）範囲を、size の正方形の中に収める。
 * 東西は緯度に合わせて縮める（日本付近ならこれで十分）
 */
export function frameFor(geoms: Geometry[], size: number, minShare = 0): Frame {
  const polys = geoms.flatMap(polygonsOf);
  const areas = polys.map((p) => ringArea(p[0]));
  const biggest = Math.max(...areas);
  const used = polys.filter((_, i) => areas[i] >= biggest * minShare);
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const p of used) for (const [lon, lat] of p[0]) {
    if (lon < minLon) minLon = lon; if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat; if (lat > maxLat) maxLat = lat;
  }
  const cos = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const w = (maxLon - minLon) * cos, h = maxLat - minLat;
  const scale = size / Math.max(w, h, 1e-9);
  const main = polys[areas.indexOf(biggest)][0];
  const lons = main.map((p) => p[0]), lats = main.map((p) => p[1]);
  const mainSize = Math.max((Math.max(...lons) - Math.min(...lons)) * cos, Math.max(...lats) - Math.min(...lats));
  return { minX: minLon * cos, minY: -maxLat, scale, width: w * scale, height: h * scale, cos, mainShare: mainSize / Math.max(w, h, 1e-9) };
}

/** 経緯度の点の、枠の中の位置 */
export const project = (f: Frame, lon: number, lat: number): [number, number] =>
  [(lon * f.cos - f.minX) * f.scale, (-lat - f.minY) * f.scale];

/**
 * 枠に合わせた SVG の path（d 属性）。tol は間引きの許容（枠の単位）。
 * 枠の中で minSize より小さくなる島は描かない（点にしかならず、ファイルが大きくなるだけのため）
 */
export function pathFor(g: Geometry, f: Frame, tol: number, minSize = 0): string {
  const out: string[] = [];
  for (const poly of polygonsOf(g)) {
    for (const ring of poly) {
      const pts = ring.map(([lon, lat]) => [(lon * f.cos - f.minX) * f.scale, (-lat - f.minY) * f.scale]);
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      if (Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) < minSize) continue;
      const s = simplify(pts, tol);
      if (s.length < 3) continue;
      out.push("M" + s.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L") + "Z");
    }
  }
  return out.join("");
}
