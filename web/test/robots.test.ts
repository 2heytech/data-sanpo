import { describe, expect, it } from "vitest";
import { robotsBody } from "../src/lib/indexing";

const SITEMAP = "https://data-sanpo.com/sitemap-index.xml";

// robots.txt の読み方（Google の仕様）: 名前の合うグループだけを使い（なければ *）、URL に合う規則のうち一番長いものに従う
function allowed(body: string, agent: string, path: string): boolean {
  const groups: { agents: string[]; rules: { allow: boolean; path: string }[] }[] = [];
  let open = false;
  for (const line of body.split("\n")) {
    const m = /^([A-Za-z-]+):\s*(.*)$/.exec(line.trim());
    if (!m) continue;
    const [key, value] = [m[1].toLowerCase(), m[2]];
    if (key === "user-agent") {
      if (!open) groups.push({ agents: [], rules: [] });
      groups[groups.length - 1].agents.push(value.toLowerCase());
      open = true;
    } else if (key === "allow" || key === "disallow") {
      groups[groups.length - 1].rules.push({ allow: key === "allow", path: value });
      open = false;
    }
  }
  const group = groups.find((g) => g.agents.includes(agent.toLowerCase())) ?? groups.find((g) => g.agents.includes("*"));
  const hits = (group?.rules ?? []).filter((r) => r.path && path.startsWith(r.path));
  if (!hits.length) return true;
  const longest = Math.max(...hits.map((r) => r.path.length));
  return hits.some((r) => r.path.length === longest && r.allow);
}

describe("robots.txt", () => {
  const body = robotsBody(true, SITEMAP, "");

  it("サイトマップの場所を書く", () => {
    expect(body).toContain(`Sitemap: ${SITEMAP}`);
  });

  it("Google・Bing は地図の状態付き URL を巡回しない（#151）", () => {
    for (const bot of ["Googlebot", "bingbot"]) {
      expect(allowed(body, bot, "/map/?i=population_total&p=2020-10-01&a=area-17201001001"), bot).toBe(false);
      expect(allowed(body, bot, "/map/?a=muni-17201"), bot).toBe(false);
    }
  });

  it("地図そのものと、ほかのページは読める", () => {
    for (const path of ["/", "/map/", "/areas/muni-17201/", "/indicators/population_total/", "/data/x/areas.json"]) {
      expect(allowed(body, "Googlebot", path), path).toBe(true);
    }
  });

  it("SNS のリンクの読み取りは止めない", () => {
    expect(allowed(body, "Twitterbot", "/map/?i=population_total&a=muni-17201")).toBe(true);
  });

  it("掲載前は全部止め、広告のクローラだけ通す（#62）", () => {
    expect(robotsBody(false, SITEMAP, "")).toBe("User-agent: *\nDisallow: /\n");
    const ads = robotsBody(false, SITEMAP, "ca-pub-0000000000000000");
    expect(allowed(ads, "Mediapartners-Google", "/areas/muni-17201/")).toBe(true);
    expect(allowed(ads, "Googlebot", "/")).toBe(false);
  });
});
