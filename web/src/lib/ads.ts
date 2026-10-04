// 広告枠（Google AdSense、docs/design-changes.md #51）。
// 発行者ID（ca-pub-数字16桁）はビルド時の環境変数 ADSENSE_CLIENT で渡す。未設定・形式違いなら広告を一切出さない。
// 広告ユニットのIDは枠の名前ごとに ADSENSE_SLOT_<名前>（例: ADSENSE_SLOT_TOP）で渡す。
const raw = (process.env.ADSENSE_CLIENT ?? "").trim();
export const ADSENSE_CLIENT = /^ca-pub-\d{16}$/.test(raw) ? raw : "";
if (raw && !ADSENSE_CLIENT) console.warn("ADSENSE_CLIENT の形式が違うため広告を出しません（ca-pub- に続く16桁の数字）");

/** 枠の名前（top・page・map）に対応する広告ユニットID。なければ空 */
export function adSlotId(name: string): string {
  const v = (process.env[`ADSENSE_SLOT_${name.toUpperCase()}`] ?? "").trim();
  return /^\d{6,}$/.test(v) ? v : "";
}
