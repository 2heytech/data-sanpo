import { describe, expect, it } from "vitest";
import { jukiLines, signed, type JukiPopulation } from "../src/lib/jukiPopulation";

const base: JukiPopulation = {
  label: "2026年1月1日現在", population: 458008, households: 247147, change: 500,
  years: [{ year: "2025年", births: 3249, deaths: 6085, natural: -2836, social: 3336, movedIn: 21579, movedOut: 18088, populationAfter: 458008 }],
};

describe("jukiLines", () => {
  it("1月1日の人口・世帯数、前の1年間の出生・死亡・転入・転出と、1年前からの増減を書く", () => {
    expect(jukiLines("尼崎市", base)).toEqual([
      "住民基本台帳では、2026年1月1日現在の尼崎市の人口は458,008人、世帯数は247,147世帯です。",
      "2025年の1年間に生まれた人は3,249人、亡くなった人は6,085人でした（自然増減は-2,836人）。",
      "転入した人は21,579人、転出した人は18,088人で、住民票のそのほかの増減も合わせた社会増減は+3,336人でした。",
      "1年前の1月1日と比べて、人口は500人増えています。",
    ]);
  });
  it("値のないところは書かず、0 にしない。減ったときは「減って」と書く", () => {
    const lines = jukiLines("A町", { ...base, households: null, change: -12,
      years: [{ ...base.years[0], movedIn: null, movedOut: null, natural: null }] });
    expect(lines[0]).toBe("住民基本台帳では、2026年1月1日現在のA町の人口は458,008人です。");
    expect(lines[1]).toBe("2025年の1年間に生まれた人は3,249人、亡くなった人は6,085人でした。");
    expect(lines[2]).toBe("転入・転出などによる社会増減は+3,336人でした。");
    expect(lines[3]).toBe("1年前の1月1日と比べて、人口は12人減っています。");
    expect(jukiLines("B村", { ...base, change: null, years: [] })).toHaveLength(1);
  });
  it("増減の数に符号を付ける", () => {
    expect([signed(3336), signed(-2836), signed(0), signed(-5, "")]).toEqual(["+3,336人", "-2,836人", "±0人", "-5"]);
  });
});
