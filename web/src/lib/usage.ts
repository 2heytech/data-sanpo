// どの指標が使われているかだけを数える（設計変更記録 #32）。
// 送るのは指標の ID と、ページを開いたときか切り替えたときかの区別だけ。Cookie は使わない。
// 送れなくても画面の動作には影響させない。
export type UsageHow = "open" | "switch";

export const USAGE_ENDPOINT = "/api/usage";

export function usageBody(indicatorId: string, how: UsageHow): string {
  return `${how}:${indicatorId}`;
}

export function countIndicatorUse(indicatorId: string, how: UsageHow): void {
  try {
    navigator.sendBeacon?.(USAGE_ENDPOINT, usageBody(indicatorId, how));
  } catch {
    /* 集計に失敗しても何もしない */
  }
}
