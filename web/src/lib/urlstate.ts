// 共有URLに保存する状態。現在地や自宅の座標は含めない（設計書 第3章「共有」）。

export interface MapState {
  indicator?: string;
  period?: string;
  area?: string;
}

const KEYS = { indicator: "i", period: "p", area: "a" } as const;
const SAFE = /^[A-Za-z0-9_.-]{1,64}$/;

export function parseState(search: string): MapState {
  const params = new URLSearchParams(search);
  const state: MapState = {};
  for (const [field, key] of Object.entries(KEYS) as [keyof MapState, string][]) {
    const v = params.get(key);
    if (v && SAFE.test(v)) state[field] = v;
  }
  return state;
}

export function serializeState(state: MapState): string {
  const params = new URLSearchParams();
  for (const [field, key] of Object.entries(KEYS) as [keyof MapState, string][]) {
    const v = state[field];
    if (v) params.set(key, v);
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export function municipalityCodeOf(entityId: string): string | null {
  const m = /^(?:muni|area)-(\d{5})/.exec(entityId);
  return m ? m[1] : null;
}

/** 地域IDの都道府県コード2桁（町丁・字等の値は都道府県ごとのファイルにある） */
export function prefectureCodeOf(entityId: string): string | null {
  return /^pref-(\d{2})$/.exec(entityId)?.[1] ?? municipalityCodeOf(entityId)?.slice(0, 2) ?? null;
}
