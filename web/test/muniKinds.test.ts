import { describe, expect, it } from "vitest";
import { KIND_SIZE, kindFacts, kindRankings, muniKind } from "../src/lib/muniKinds";
import type { CityValue, DesignatedCity } from "../src/lib/designatedCities";
import type { Municipality, ValueRow } from "../src/lib/types";

const muni = (code: string, name: string, region: string | null = null) =>
  ({ id: `muni-${code}`, name, prefecture: code.slice(0, 2), region }) as Municipality;
const row = (id: string, value: number | null): ValueRow => ({ entity_id: id, value, status: value === null ? "missing" : "observed" });

describe("muniKind", () => {
  it("名前の終わりで市・町・村に分け、東京の区部は東京23区、政令指定都市の区は入れない", () => {
    expect(muniKind({ name: "蕨市", region: null }, false)).toBe("市");
    expect(muniKind({ name: "町田市", region: null }, false)).toBe("市");
    expect(muniKind({ name: "森町", region: null }, false)).toBe("町");
    expect(muniKind({ name: "舟橋村", region: null }, false)).toBe("村");
    expect(muniKind({ name: "千代田区", region: "区部" }, false)).toBe("東京23区");
    expect(muniKind({ name: "横浜市鶴見区", region: "横浜市" }, true)).toBeNull();
  });
});

describe("kindRankings", () => {
  const munis = [
    muni("11203", "川口市"), muni("11208", "蕨市"), muni("21203", "高山市"), muni("16321", "舟橋村"), muni("07364", "檜枝岐村"),
    muni("01343", "森町"), muni("12322", "酒々井町"), muni("13101", "千代田区", "区部"), muni("13102", "中央区", "区部"),
    muni("14101", "横浜市鶴見区", "横浜市"), muni("14382", "箱根町"),
  ];
  const rows = [
    row("muni-11203", 61.95), row("muni-11208", 5.11), row("muni-21203", 2177.61), row("muni-16321", 3.47), row("muni-07364", 390.46),
    row("muni-01343", 368.79), row("muni-12322", 19.01), row("muni-13101", 11.66), row("muni-13102", 10.21), row("muni-14101", 33.23),
    row("muni-14382", null),
  ];
  const yokohama: CityValue = { city: { name: "横浜市", prefecture: "14", wards: ["muni-14101"] } as DesignatedCity, value: 437.71 };
  const kinds = kindRankings(munis, rows, new Set(["muni-14101"]), [yokohama]);

  it("種類ごとに大きい順に並べ、政令指定都市は市全体で市に入れ、区と値のない市区町村は入れない", () => {
    expect(kinds.map((k) => [k.kind, k.total])).toEqual([["市", 4], ["町", 2], ["村", 2], ["東京23区", 2]]);
    expect(kinds[0].top.map((e) => [e.name, e.rank, e.id])).toEqual([
      ["高山市", 1, "muni-21203"], ["横浜市", 2, null], ["川口市", 3, "muni-11203"], ["蕨市", 4, "muni-11208"],
    ]);
    expect(kinds[0].bottom).toEqual([]);
  });
  it(`${KIND_SIZE * 2}より多いときは、大きい順と小さい順の${KIND_SIZE}ずつにする`, () => {
    const many = Array.from({ length: 25 }, (_, i) => muni(`99${String(i).padStart(3, "0")}`, `市${i}市`));
    const k = kindRankings(many, many.map((m, i) => row(m.id, i + 1)), new Set(), [])[0];
    expect(k.top).toHaveLength(KIND_SIZE);
    expect(k.bottom.map((e) => e.row.value).slice(0, 3)).toEqual([1, 2, 3]);
    expect(k.bottom[0].rank).toBe(1);
  });
  it("冒頭の2文は、市・町・村それぞれの1位を大きい側と小さい側で書く（東京23区は入れない）", () => {
    const lines = kindFacts(kinds, { more: "広い", less: "狭い" }, (e) => e.name, (e) => `${e.row.value}km²`);
    expect(lines).toEqual([
      "市・町・村に分けると、いちばん広い市は高山市（2177.61km²）、町は森町（368.79km²）、村は檜枝岐村（390.46km²）です。",
      "いちばん狭い市は蕨市（5.11km²）、町は酒々井町（19.01km²）、村は舟橋村（3.47km²）です。",
    ]);
  });
});
