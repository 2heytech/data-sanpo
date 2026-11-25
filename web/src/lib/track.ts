// 画面の操作を Google アナリティクスのイベントとして送る（設計変更記録 #255）。
// 測定 ID のない版・公開サイトのドメイン以外では gtag.js を読み込まないので、何も送られない。
// 送れなくても画面の動作には影響させない。

export type TrackParams = Record<string, string | number | undefined>;

/** GA4 の値の長さの上限（100文字）に収める */
export function clip(s: string, max = 100): string {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > max ? t.slice(0, max) : t;
}

export function track(name: string, params: TrackParams = {}): void {
  try {
    (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag?.("event", name, params);
  } catch {
    /* 送れなくても何もしない */
  }
}
