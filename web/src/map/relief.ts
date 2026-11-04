// 標高の色の見本（地理院タイル「色別標高図」の平らな所の色を、標高ごとに読み取ったもの）。帯は等間隔で、目盛りは一部だけ書く。
// 地図の上のパネルと、保存する画像の凡例（#175）で同じものを使う
export const RELIEF_STOPS: { m: number; color: string; tick?: string }[] = [
  { m: 0, color: "#2db5ae", tick: "0m" }, { m: 10, color: "#2db579" }, { m: 50, color: "#52b52d" },
  { m: 100, color: "#71b52d", tick: "100" }, { m: 200, color: "#99b52d" }, { m: 300, color: "#b5a92d", tick: "300" },
  { m: 500, color: "#b5902d" }, { m: 1000, color: "#b5562d", tick: "1000" }, { m: 2000, color: "#b5491b" },
  { m: 3000, color: "#b54212", tick: "3000m" },
];

/** 帯の上の位置（0〜1） */
export const reliefAt = (i: number) => i / (RELIEF_STOPS.length - 1);

export const RELIEF_GRADIENT = `linear-gradient(to right, ${RELIEF_STOPS.map((s, i) => `${s.color} ${reliefAt(i) * 100}%`).join(", ")})`;
