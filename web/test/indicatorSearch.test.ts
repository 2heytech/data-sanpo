import { describe, expect, it } from "vitest";
import { IndicatorSearch, normalizeText, toReading, type SearchDoc } from "../src/lib/indicatorSearch";

const doc = (name: string, category: string, description = "", alt: string[] = []): SearchDoc => ({ name, category, description, alt });
const DOCS: SearchDoc[] = [
  doc("人口", "人口・世帯", "常住人口（ふだん住んでいる人の数）。"),
  doc("世帯数", "人口・世帯"),
  doc("人口密度", "人口・世帯", "1km²あたりの常住人口。"),
  doc("人口増加率", "人口・世帯"),
  doc("昼間人口", "人口・世帯"),
  doc("65歳以上の割合", "年齢構成"),
  doc("15歳未満の割合", "年齢構成"),
  doc("一人暮らし世帯の割合", "暮らし方"),
  doc("子どものいる世帯の割合", "暮らし方"),
  doc("持ち家に住む世帯の割合", "暮らし方", "", ["住まいの種類別の世帯の割合"]),
  doc("民営の借家に住む世帯の割合", "暮らし方", "", ["住まいの種類別の世帯の割合"]),
  doc("平均傾斜", "土地"),
  doc("平均標高", "土地"),
  doc("保育所等を利用している子どもの数", "子育て"),
  doc("保育所等の待機児童数", "子育て"),
  doc("課税対象所得の納税者1人あたり額", "所得・税"),
  doc("犯罪の認知件数", "犯罪", "", ["住民100人当たり"]),
  doc("自転車盗の認知件数", "犯罪"),
  doc("入湯税の収入額", "観光", "温泉の入湯客にかかる税の収入。"),
  doc("リゾートホテルの延べ宿泊者数", "観光"),
  doc("大学生・大学院生の割合", "通勤・通学"),
  doc("小学校の1学級あたり児童数", "教育"),
  doc("国勢調査の外国人の数（ベトナム）", "外国人住民", "国籍がベトナムの人の数。"),
  doc("国勢調査の外国人の数（アメリカ）", "外国人住民"),
  doc("外国人住民の数（米国）", "外国人住民"),
  doc("外国人住民の数（中国）", "外国人住民"),
];
const search = new IndicatorSearch(DOCS);
const names = (q: string) => search.search(q).map((r) => r.doc.name);

describe("normalizeText・toReading", () => {
  it("全角半角・カタカナとひらがな・記号の違いをそろえる", () => {
    expect(normalizeText("ﾎﾃﾙ")).toBe(normalizeText("ホテル"));
    expect(normalizeText("ＡＢＣ１２３")).toBe("abc123");
    expect(normalizeText("通勤・通学（鉄道）")).toBe("通勤通学鉄道");
  });

  it("書き方の違う言葉と、ひらがなの読みを同じ読みにする", () => {
    expect(toReading(normalizeText("子供"))).toBe(toReading(normalizeText("子ども")));
    expect(toReading(normalizeText("一人暮し"))).toBe(toReading(normalizeText("一人暮らし")));
    expect(toReading(normalizeText("100人当たり"))).toBe(toReading(normalizeText("100人あたり")));
    expect(toReading(normalizeText("人口密度"))).toBe("じんこうみつど");
  });
});

describe("IndicatorSearch", () => {
  it("名前と同じ指標をいちばん上に、名前で始まる指標をその次に出す", () => {
    const r = names("人口");
    expect(r[0]).toBe("人口");
    expect(r.slice(1, 3)).toEqual(["人口密度", "人口増加率"]);
    expect(names("")).toEqual([]);
    expect(names("　")).toEqual([]);
  });

  it("ひらがなの読み・カタカナ・半角でも見つかる", () => {
    expect(names("じんこう")[0]).toBe("人口");
    expect(names("じんこうみつど")[0]).toBe("人口密度");
    expect(names("ﾘｿﾞｰﾄ")[0]).toBe("リゾートホテルの延べ宿泊者数");
    expect(names("べとなむ")).toEqual(["国勢調査の外国人の数（ベトナム）"]);
  });

  it("送り仮名や漢字の違う書き方でも見つかる", () => {
    expect(names("子供")).toEqual(expect.arrayContaining(["子どものいる世帯の割合", "保育所等を利用している子どもの数"]));
    expect(names("一人暮し")[0]).toBe("一人暮らし世帯の割合");
    expect(names("ひとり暮らし")[0]).toBe("一人暮らし世帯の割合");
  });

  it("近い意味の言葉でも見つかる", () => {
    expect(names("人の多さ").slice(0, 2)).toContain("人口密度");
    expect(names("お年寄りが多い")[0]).toBe("65歳以上の割合");
    expect(names("高齢化率")[0]).toBe("65歳以上の割合");
    expect(names("子どもの割合")).toContain("15歳未満の割合");
    expect(names("治安")[0]).toBe("犯罪の認知件数");
    expect(names("家賃")[0]).toBe("民営の借家に住む世帯の割合");
    expect(names("坂")[0]).toBe("平均傾斜");
    expect(names("温泉")[0]).toBe("入湯税の収入額");
    expect(names("単身")).toEqual(["一人暮らし世帯の割合"]);
  });

  it("米国とアメリカのように、言い方の違う国名はどちらでも見つかる", () => {
    expect(names("アメリカ")).toEqual(["国勢調査の外国人の数（アメリカ）", "外国人住民の数（米国）"]);
    expect(names("米国")).toEqual(["外国人住民の数（米国）", "国勢調査の外国人の数（アメリカ）"]);
  });

  it("「〇〇率」「〇〇ランキング」「全国の〇〇」の形でも見つかる", () => {
    expect(names("持ち家率")[0]).toBe("持ち家に住む世帯の割合");
    expect(names("人口ランキング")[0]).toBe("人口");
    expect(names("全国の人口")[0]).toBe("人口");
    expect(names("人口 ランキング")[0]).toBe("人口");
  });

  it("空白で区切った言葉は、すべてに当たる指標だけにする", () => {
    expect(names("外国人 ベトナム")).toEqual(["国勢調査の外国人の数（ベトナム）"]);
    expect(names("犯罪 100人あたり")).toEqual(["犯罪の認知件数"]);
  });

  it("助詞でつないだ言葉は、分けて探す", () => {
    expect(names("子どもの数")[0]).toBe("保育所等を利用している子どもの数");
    expect(names("中国の人")).toContain("外国人住民の数（中国）");
  });

  it("名前に当たる指標があるときは、説明の文だけに当たる指標を出さない", () => {
    expect(names("ベトナム")).toEqual(["国勢調査の外国人の数（ベトナム）"]);
  });

  it("近い意味の言葉を、ほかの言葉の一部や前後の決まった言葉の中では使わない", () => {
    // 「新宿」の「宿」で宿泊、「小学生」の「学生」で大学生、「所得の高さ」の「高さ」で標高を出さない
    expect(names("新宿")).toEqual([]);
    expect(names("小学生")).not.toContain("大学生・大学院生の割合");
    expect(names("所得の高さ")).toEqual(["課税対象所得の納税者1人あたり額"]);
  });

  it("どの言葉にも当たらないときは、打ち間違いとみて似た名前を出す", () => {
    expect(names("人口密土")).toContain("人口密度");
    expect(names("まったく関係のない言葉")).toEqual([]);
  });
});

describe("医療・介護・上下水道などの指標", () => {
  const more = new IndicatorSearch([
    doc("病院・一般診療所の病床数（人口10万人あたり）", "医療・介護"),
    doc("介護保険施設の定員（65歳以上1,000人あたり）", "医療・介護", "特別養護老人ホーム・介護老人保健施設・介護医療院の定員の合計。"),
    doc("子どもの医療費の助成の対象年齢（通院）", "子育て"),
    doc("水道料金（家庭用・1か月20m³）", "上下水道"),
    doc("汚水処理人口普及率", "上下水道"),
    doc("都市公園の面積（都市計画区域の住民1人あたり）", "緑"),
    doc("飲食店の数（住民1,000人あたり）", "商業"),
    doc("1人あたりの住宅の延べ面積", "暮らし方"),
  ]);
  const found = (q: string) => more.search(q).map((r) => r.doc.name)[0];

  it("読みや近い意味の言葉で見つかる", () => {
    expect(found("老人ホーム")).toBe("介護保険施設の定員（65歳以上1,000人あたり）");
    expect(found("特養")).toBe("介護保険施設の定員（65歳以上1,000人あたり）");
    expect(found("かいご")).toBe("介護保険施設の定員（65歳以上1,000人あたり）");
    expect(found("ベッド")).toBe("病院・一般診療所の病床数（人口10万人あたり）");
    expect(found("子ども医療費")).toBe("子どもの医療費の助成の対象年齢（通院）");
    expect(found("水道代")).toBe("水道料金（家庭用・1か月20m³）");
    expect(found("すいどう")).toBe("水道料金（家庭用・1か月20m³）");
    expect(found("下水")).toBe("汚水処理人口普及率");
    expect(found("浄化槽")).toBe("汚水処理人口普及率");
    expect(found("公園")).toBe("都市公園の面積（都市計画区域の住民1人あたり）");
    expect(found("レストラン")).toBe("飲食店の数（住民1,000人あたり）");
    expect(found("家の広さ")).toBe("1人あたりの住宅の延べ面積");
  });
});
