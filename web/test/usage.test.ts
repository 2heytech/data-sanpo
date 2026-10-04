import { describe, expect, it } from "vitest";
import { usageBody } from "../src/lib/usage";
import { handleUsage } from "../worker/usage";

const IDS = new Set(["population_total"]);
const URL_ = "https://example.test/api/usage";

function recorder() {
  const points: unknown[] = [];
  return { points, dataset: { writeDataPoint: (p: unknown) => void points.push(p) } };
}

describe("指標の利用回数の窓口", () => {
  it("指標 ID と開き方だけを1件記録する", async () => {
    const { points, dataset } = recorder();
    const res = await handleUsage(
      new Request(URL_, { method: "POST", body: usageBody("population_total", "switch"), headers: { Origin: "https://example.test" } }),
      dataset, IDS,
    );
    expect(res.status).toBe(204);
    expect(points).toEqual([{ blobs: ["population_total", "switch"], doubles: [1], indexes: ["population_total"] }]);
  });

  it("知らない指標・形式違い・他サイトからの送信・GET は記録しない", async () => {
    const { points, dataset } = recorder();
    const post = (body: string, origin = "https://example.test") =>
      handleUsage(new Request(URL_, { method: "POST", body, headers: { Origin: origin } }), dataset, IDS);
    expect((await post("switch:unknown")).status).toBe(400);
    expect((await post("click:population_total")).status).toBe(400);
    expect((await post("population_total")).status).toBe(400);
    expect((await post("open:population_total", "https://evil.test")).status).toBe(403);
    expect((await handleUsage(new Request(URL_), dataset, IDS)).status).toBe(405);
    expect(points).toEqual([]);
  });
});
