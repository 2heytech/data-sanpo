// 点レイヤー（駅・学校・地価・保育所）の共通の形。クリックは app.ts でまとめて受け、
// 直前にクリックした1地点だけを地図の上のポップアップに出す（重なっている地点は一覧から選ぶ。#139）。
import type { Map as MapLibreMap } from "maplibre-gl";
import { esc } from "../lib/html";
import type { PlacePrefecture, Source } from "../lib/types";

export interface PointLayer {
  /** クリック判定に使う円のレイヤー */
  layer: string;
  /** 一覧で見せる種類名（駅・学校・地価・保育所） */
  kind: string;
  visible(): boolean;
  /** 地点を選ぶ（null で閉じる） */
  show(id: string | null): void;
  /** 地点の情報を出しているか */
  isOpen(): boolean;
  /** 情報を出している地点の位置（ポップアップを出す所）。位置が分からない地点や、閉じているときは null */
  coord(): [number, number] | null;
  /** 読み込んだ地点の出典（保存する画像に書く。#153） */
  sourceIds(): string[];
  /** 共有URLに入れる状態（#175）: 表示がオンなら ?show= の名前、地点を選んでいればその引数（?s=<駅ID> など） */
  urlState(): PointUrlState;
}

export interface PointUrlState {
  show: string | null;
  params: Record<string, string>;
}

/** 点レイヤーの共有URLの状態。表示がオフなら何も入れず、地点の情報を閉じていれば地点は入れない */
export function pointUrlState(on: boolean, show: string, key: string, id: string | null | undefined, open: boolean): PointUrlState {
  return { show: on ? show : null, params: on && open && id ? { [key]: id } : {} };
}

/** 共有URLの地点を開いたときに、地図をその地点へ動かす（URL に地図の位置が入っているときは動かさない。#175） */
export type FocusPoint = (center: [number, number], minZoom: number) => void;

/** 地点の情報の出典の行（出典表記を重複なく「／」で並べる） */
export function sourcesHtml(ids: string[], sources: Map<string, Source>): string {
  const names = [...new Set(ids.map((id) => sources.get(id)?.attribution ?? id))];
  return `<p class="muted small">${names.map(esc).join("／")}</p>`;
}

/** 点の一覧を読み込み始める縮尺。全国を見ているときは読まない（1都道府県が収まるくらいから） */
export const PLACES_MIN_ZOOM = 8;

interface PrefLoaderOptions<T> {
  map: MapLibreMap;
  fetchJSON: <U>(rel: string) => Promise<U>;
  /** places/<id>/<都道府県>.json */
  id: string;
  /** 都道府県のファイルで点の一覧が入っているキー */
  key: "stations" | "schools" | "points";
  /** 読み込んだ点が増えたとき（全都道府県分をまとめて渡す） */
  onChange: (items: T[]) => void;
  /** 表示がオンか（オフのあいだは地図を動かしても読まない） */
  active: () => boolean;
}

/**
 * 点の一覧を都道府県ごとのファイルから、地図に映っている都道府県の分だけ読む（docs/design-changes.md #71）。
 * 全国では1ファイルが数MBになるため。一度読んだ都道府県は手放さない。
 */
export function createPrefLoader<T>(o: PrefLoaderOptions<T>) {
  let prefs: Record<string, PlacePrefecture> = {};
  const loaded = new Map<string, T[]>();
  const pending = new Map<string, Promise<void>>();

  const all = () => [...loaded.values()].flat();

  function loadPref(pref: string): Promise<void> {
    if (loaded.has(pref)) return Promise.resolve();
    const p = pending.get(pref);
    if (p) return p;
    const req = o.fetchJSON<Record<string, unknown>>(`places/${o.id}/${pref}.json`)
      .then((f) => { loaded.set(pref, (f[o.key] as T[]) ?? []); })
      .catch(() => { loaded.set(pref, []); })
      .finally(() => pending.delete(pref));
    pending.set(pref, req);
    return req;
  }

  /** 地図に映っている都道府県（範囲が重なるもの） */
  function inView(): string[] {
    const b = o.map.getBounds();
    return Object.entries(prefs).filter(([, p]) => p.bbox && !(p.bbox[0] > b.getEast() || p.bbox[2] < b.getWest()
      || p.bbox[1] > b.getNorth() || p.bbox[3] < b.getSouth())).map(([pref]) => pref);
  }

  async function refresh(): Promise<void> {
    if (!o.active() || o.map.getZoom() < PLACES_MIN_ZOOM) return;
    const need = inView().filter((p) => !loaded.has(p));
    if (!need.length) return;
    await Promise.all(need.map(loadPref));
    o.onChange(all());
  }

  o.map.on("moveend", () => void refresh());

  return {
    /** places/<指標>.json を読んだあとに呼ぶ */
    init(meta: { prefectures?: Record<string, PlacePrefecture> }) {
      prefs = meta.prefectures ?? {};
    },
    refresh,
    /** 地点の都道府県が分かっているとき（リンクから開いたとき）。分からなければ順に探す */
    async find(match: (item: T) => boolean, hint?: string | null): Promise<T | undefined> {
      const order = [...new Set([...(hint ? [hint] : []), ...inView(), "13", ...Object.keys(prefs)])]
        .filter((p) => p in prefs);
      for (const pref of order) {
        const had = loaded.has(pref);
        await loadPref(pref);
        if (!had) o.onChange(all());
        const hit = loaded.get(pref)!.find(match);
        if (hit) return hit;
      }
      return undefined;
    },
    /** 1つの都道府県の分を読む（共通地点の相手を探すときなど、地図に映っていなくても読む） */
    async loadPrefecture(pref: string): Promise<void> {
      if (!(pref in prefs) || loaded.has(pref)) return;
      await loadPref(pref);
      o.onChange(all());
    },
    items: all,
    /** 地図に映っている都道府県のうち、値がなく位置だけの点がある都道府県 */
    locationOnlyInView: () => inView().filter((p) => prefs[p]?.location_only),
    /** 全国を見ているなど、まだ縮尺が小さくて読んでいないか */
    tooFar: () => o.map.getZoom() < PLACES_MIN_ZOOM,
  };
}
