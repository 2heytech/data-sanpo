// 指標の利用回数を受け取る窓口（設計変更記録 #32）。
// 受け取るのは「open:指標ID」か「switch:指標ID」という短い文字列だけで、
// Workers Analytics Engine に1件として記録する。IP アドレス・端末情報・Cookie は記録しない。
export interface AnalyticsEngineDataset {
  writeDataPoint(point: { blobs?: string[]; doubles?: number[]; indexes?: string[] }): void;
}

const HOWS = new Set(["open", "switch"]);
const MAX_BODY = 100;

export async function handleUsage(
  request: Request,
  dataset: AnalyticsEngineDataset | undefined,
  indicatorIds: ReadonlySet<string>,
): Promise<Response> {
  if (request.method !== "POST") {
    return new Response(null, { status: 405, headers: { Allow: "POST" } });
  }
  // 他のサイトから送らせない（ブラウザは POST に Origin を付ける）
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) return new Response(null, { status: 403 });
  const body = (await request.text()).trim();
  const [how, id] = body.length <= MAX_BODY ? body.split(":", 2) : [];
  if (!how || !id || !HOWS.has(how) || !indicatorIds.has(id)) return new Response(null, { status: 400 });
  dataset?.writeDataPoint({ blobs: [id, how], doubles: [1], indexes: [id] });
  return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
}
