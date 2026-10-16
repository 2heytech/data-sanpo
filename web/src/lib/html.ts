/** 文字列を HTML に埋め込めるようにする（地図の欄は innerHTML で組み立てるため、データの文字列は必ず通す）。 */
export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
