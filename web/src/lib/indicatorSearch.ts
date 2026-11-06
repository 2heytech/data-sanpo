// 指標の検索（設計変更記録 #201）。トップページの指標の一覧と、地図の指標の選択画面で使う。
// 書き方の違い（全角・半角、ひらがな・カタカナ、送り仮名、「子供」と「子ども」など）、読み（ひらがなで入れた名前）、
// 近い意味の言葉（「人の多さ」→ 人口密度、「治安」→ 犯罪 など）でも見つかるようにする。
// 辞書はこのファイルに持つ（サーバーも、読み込むファイルも増やさない）。
// 指標を足したときに名前の言葉が辞書になくても、書いてあるとおりの文字では見つかる。読みや近い言葉で見つけたい言葉だけ足す

export interface SearchDoc {
  /** 指標の名前（いちばん重く見る） */
  name: string;
  /** まとめた項目の名前、種類の名前など */
  alt?: string[];
  /** 基準の名前（住民100人当たりなど）。ほかの言葉と組み合わせたときに絞り込むためのもので、軽く見る */
  keywords?: string[];
  category?: string;
  genre?: string;
  description?: string;
}
export interface SearchResult<T> { doc: T; score: number }

// --- 書き方をそろえる -------------------------------------------------------------------------
const kataToHira = (s: string) => s.replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
// 区切りの記号・空白は比べるときに除く（「通勤・通学」と「通勤通学」を同じにする）。長音の「ー」は残す
const PUNCT = /[\s・、。,.「」『』()[\]【】〈〉《》{}"'`!?:;/\\~〜_|※*+=<>#%&＆]/g;

/** 全角半角・大文字小文字・カタカナとひらがな・記号の違いをそろえる */
export function normalizeText(s: string): string {
  return kataToHira(s.normalize("NFKC").toLowerCase()).replace(PUNCT, "");
}

// --- 読み（漢字の言葉 → ひらがな） ---------------------------------------------------------------
// 指標名に出てくる言葉の読み。名前の側と入力の側の両方を読みに直して比べるので、
// 「じんこう」で人口、「子供」で「子ども」、「一人暮し」で「一人暮らし」が見つかる。長い言葉から先に当てる
const READINGS = `
人口:じんこう 世帯:せたい 人数:にんずう 密度:みつど 増加率:ぞうかりつ 増加:ぞうか 増減:ぞうげん 昼間:ひるま 昼夜間:ちゅうやかん
比率:ひりつ 推移:すいい 面積:めんせき 建物:たてもの 用地:ようち 森林:しんりん 高層:こうそう 低層:ていそう 住宅:じゅうたく
密集:みっしゅう 土地:とち 工場:こうじょう 公園:こうえん 緑地:りょくち 平均:へいきん 標高:ひょうこう 高低差:こうていさ
傾斜:けいしゃ 平ら:たいら 斜面:しゃめん 区画:くかく 農地:のうち 自然林:しぜんりん 二次林:にじりん 植林地:しょくりんち
竹林:ちくりん 割合:わりあい 年齢:ねんれい 以上:いじょう 未満:みまん 暮らし:くらし 一人暮らし:ひとりぐらし 一人暮し:ひとりぐらし
独り暮らし:ひとりぐらし ひとり暮らし:ひとりぐらし 子ども:こども 子供:こども 持ち家:もちいえ 持家:もちいえ 民営:みんえい
借家:しゃくや 共同住宅:きょうどうじゅうたく 階建:かいだて 場所:ばしょ 住み始め:すみはじめ 空き家:あきや 空家:あきや
寿命:じゅみょう 男性:だんせい 女性:じょせい 働く:はたらく 自営業:じえいぎょう 専門的:せんもんてき 技術的:ぎじゅつてき
職業:しょくぎょう 管理的:かんりてき 事業所:じぎょうしょ 従業者:じゅうぎょうしゃ 通勤:つうきん 通学:つうがく 交通手段:こうつうしゅだん
鉄道:てつどう 電車:でんしゃ 徒歩:とほ 自転車:じてんしゃ 乗合:のりあい 自家用車:じかようしゃ 大学院:だいがくいん 大学:だいがく
在学者:ざいがくしゃ 教育:きょういく 幼稚園:ようちえん 保育園:ほいくえん 保育所:ほいくしょ 保育:ほいく こども園:こどもえん
認定:にんてい 小学校:しょうがっこう 中学校:ちゅうがっこう 高校:こうこう 入学:にゅうがく 公立:こうりつ 私立:しりつ 国立:こくりつ
卒業者:そつぎょうしゃ 卒業:そつぎょう 進学先:しんがくさき 進学率:しんがくりつ 進学:しんがく 児童:じどう 生徒:せいと
学力:がくりょく 正答率:せいとうりつ 国語:こくご 算数:さんすう 数学:すうがく 学級:がっきゅう 特別支援:とくべつしえん
専門学校:せんもんがっこう 就職者:しゅうしょくしゃ 就職:しゅうしょく 学歴:がくれき 不詳:ふしょう
外国人:がいこくじん 国勢調査:こくせいちょうさ 住民:じゅうみん 在留:ざいりゅう 韓国:かんこく 朝鮮:ちょうせん 中国:ちゅうごく
台湾:たいわん 米国:べいこく
犯罪:はんざい 認知件数:にんちけんすう 件数:けんすう 凶悪犯:きょうあくはん 粗暴犯:そぼうはん 侵入:しんにゅう 窃盗:せっとう
刑法犯:けいほうはん 全国:ぜんこく 重要犯罪:じゅうようはんざい 手口:てぐち 自転車盗:じてんしゃとう 自動車盗:じどうしゃとう
自動車:じどうしゃ 車上:しゃじょう 狙い:ねらい 部品:ぶひん 自動販売機:じどうはんばいき 交通事故:こうつうじこ 事故:じこ
歩行者:ほこうしゃ 死亡:しぼう 交通:こうつう 駅:えき 乗降客数:じょうこうきゃくすう 乗降:じょうこう 空港:くうこう 港:みなと
船舶:せんぱく 幹線道路:かんせんどうろ 道路:どうろ 交通量:こうつうりょう 大型車:おおがたしゃ 混雑:こんざつ 速度:そくど
地価:ちか 地価公示:ちかこうじ 価格:かかく 住宅地:じゅうたくち 商業地:しょうぎょうち 中央値:ちゅうおうち
子育て:こそだて 定員:ていいん 待機児童:たいきじどう 利用:りよう 合計特殊出生率:ごうけいとくしゅしゅっしょうりつ 出生率:しゅっしょうりつ
出生:しゅっしょう 所得:しょとく 納税:のうぜい 受入:うけいれ 住民税:じゅうみんぜい 課税:かぜい 就学援助:しゅうがくえんじょ
年収:ねんしゅう 財政:ざいせい 財政力指数:ざいせいりょくしすう 経常収支比率:けいじょうしゅうしひりつ 公債費:こうさいひ
将来負担:しょうらいふたん 歳出:さいしゅつ 市区町村税:しくちょうそんぜい 収入:しゅうにゅう 地方債:ちほうさい 残高:ざんだか
積立金:つみたてきん 緑:みどり 都道:とどう 街路樹:がいろじゅ 本数:ほんすう 銀杏:いちょう 桜:さくら 欅:けやき 楓:かえで
樹種:じゅしゅ 選挙:せんきょ 投票率:とうひょうりつ 投票:とうひょう 比例代表:ひれいだいひょう 得票率:とくひょうりつ
自由民主党:じゆうみんしゅとう 立憲民主党:りっけんみんしゅとう 公明党:こうめいとう 日本維新の会:にっぽんいしんのかい
国民民主党:こくみんみんしゅとう 日本共産党:にほんきょうさんとう 新選組:しんせんぐみ 参政党:さんせいとう 社会民主党:しゃかいみんしゅとう
日本保守党:にほんほしゅとう 中道改革連合:ちゅうどうかいかくれんごう 観光:かんこう 延べ:のべ 宿泊者:しゅくはくしゃ
宿泊業:しゅくはくぎょう 宿泊:しゅくはく 日本人:にほんじん 県外:けんがい 旅館:りょかん 簡易宿所:かんいしゅくしょ
入湯税:にゅうとうぜい 道の駅:みちのえき 国宝:こくほう 文化財:ぶんかざい 有形:ゆうけい 建造物:けんぞうぶつ 史跡:しせき
名勝:めいしょう 天然記念物:てんねんきねんぶつ 伝統的:でんとうてき 保存地区:ほぞんちく 農業:のうぎょう 農林漁業:のうりんぎょぎょう
産出額:さんしゅつがく 米:こめ 野菜:やさい 果実:かじつ 畜産:ちくさん 工業:こうぎょう 製造業:せいぞうぎょう 製造品:せいぞうひん
出荷額:しゅっかがく 付加価値:ふかかち 商業:しょうぎょう 卸売業:おろしうりぎょう 小売業:こうりぎょう 販売額:はんばいがく
天気:てんき 日照時間:にっしょうじかん 日照:にっしょう 降水量:こうすいりょう 積雪:せきせつ 降雪量:こうせつりょう 降雪:こうせつ
年間:ねんかん 当たり:あたり 当り:あたり 一人当たり:1人あたり 一人あたり:1人あたり
転入:てんにゅう 転出:てんしゅつ 転出入:てんしゅつにゅう 子ども女性比:こどもじょせいひ
`;

// --- 近い意味の言葉 -----------------------------------------------------------------------------
// 「左の言葉 > 指標名・分類名に出てくる言葉」。左の言葉が入力に含まれていたら、右の言葉でも探す。
// 「=」の行は、どちらで探してもほかの言葉で見つかる組（米国とアメリカなど）。
// 指標の数字の意味を取り違えないよう、右には名前の言葉をそのまま書く。地域を悪く言う言葉は置かない
const RELATED = `
人の多さ 人が多い 人口の多さ 人混み 混み具合 過密 都会 都市化 > 人口密度 人口
人口減少 人口が減 過疎 人口が増 人口の伸び > 人口増加率
人口の歴史 昔の人口 > 1920年
ベッドタウン 昼の人口 都心 オフィス街 通勤者 > 昼間人口 昼夜間人口比率
広さ 大きさ > 面積
家族の人数 > 1世帯あたり人数
高齢者 お年寄り 年寄り 老人 シニア 高齢化 高齢 > 65歳以上
子ども 子供 こども 年少人口 > 15歳未満
少子化 > 15歳未満 合計特殊出生率
赤ちゃん 出産 生まれ 産む > 合計特殊出生率 子ども女性比
乳幼児 未就学児 出生力 > 子ども女性比
単身 独身 独居 一人住まい ひとり世帯 > 一人暮らし
家族 ファミリー 子育て世帯 > 子どものいる世帯
マイホーム > 持ち家
賃貸 家賃 アパート 借りる > 借家
マンション タワマン タワーマンション > 11階建以上 高層建物
引っ越し 引越し 転入 転居 住み替え 定住 移住 > 住み始めて 5年前と同じ場所 転入率 転出率 転出入人口比率
人の出入り 人の入れ替わり 社会増減 流入 流出 > 転入率 転出率 転出入人口比率
長生き 長寿 > 平均寿命
仕事 雇用 就業 職場 > 従業者 働く人
会社 企業 > 事業所
経営者 管理職 社長 役員 > 管理的職業
専門職 技術者 エンジニア > 専門的・技術的職業
個人事業 フリーランス > 自営業
地下鉄 > 電車
マイカー くるま 車通勤 > 自家用車
歩き 歩いて > 徒歩
チャリ > 自転車
託児所 保活 > 保育所 待機児童
保育園 = 保育所
成績 テスト 偏差値 学力調査 > 学力テスト
中学受験 受験 私学 > 私立
大卒 高学歴 大学卒 > 大学・大学院卒
クラス 学級規模 > 1学級あたり
大学進学 > 大学等進学率
小学生 > 小学校
中学生 > 中学校
高校生 > 高校
学生 > 大学生 在学者
治安 防犯 事件 > 犯罪 刑法犯
泥棒 どろぼう 盗難 盗み 空き巣 > 窃盗
空き巣 > 侵入窃盗
バイク 原付 > オートバイ
車上荒らし > 車上ねらい
渋滞 車の多さ > 交通量 混雑時の平均速度
トラック > 大型車
飛行機 > 空港
フェリー 船 > 港
乗客 利用者数 > 乗降客数 乗降人員
土地の値段 土地代 土地価格 不動産 坪単価 > 地価
給料 給与 稼ぎ お金持ち 裕福 収入 > 所得 世帯年収
税金 税収 > 税
寄付 寄附 返礼品 > ふるさと納税
予算 支出 > 歳出
借金 負債 > 地方債 公債費 将来負担比率
貯金 基金 貯蓄 > 積立金
田んぼ 水田 稲作 > 田 米
果物 フルーツ みかん りんご ぶどう > 果実
酪農 牛 豚 肉 > 畜産
農家 > 農業 農林漁業
ものづくり メーカー 工場 > 製造業 製造品出荷額
買い物 お店 商店 スーパー ショッピング > 小売業
問屋 > 卸売業
山林 樹木 > 森林 街路樹
竹やぶ たけのこ > 竹林
坂 坂道 起伏 山がち でこぼこ > 傾斜 高低差 斜面
平地 平野 > 平らな土地
高さ 海抜 > 標高
雪国 豪雪 > 積雪 降雪
雨 雨量 > 降水量
晴れ 日当たり 日差し 太陽 > 日照時間
気候 > 天気
温泉 > 入湯税
観光客 旅行者 旅行 インバウンド 訪日 > 宿泊者
インバウンド 訪日 外国人観光客 > 外国人延べ宿泊者 延べ宿泊者に占める外国人
宿 民宿 ゲストハウス ホテル > 宿泊 旅館 簡易宿所
お寺 寺 神社 城 > 重要文化財 登録有形文化財
町並み 街並み 宿場町 > 重要伝統的建造物群保存地区
遺跡 古墳 > 史跡
庭園 景勝地 > 名勝
政治 > 投票率 得票率
政党 支持 > 得票率
自民 > 自由民主党
社民 > 社会民主党
海外 国際 移民 > 外国人
アメリカ = 米国
イギリス = 英国
人口当たり 人口あたり 人口比 > 100人当たり
`;

// 入力の前後から外す言葉（「〇〇ランキング」「全国の〇〇」「〇〇が多い」など）。
// 外した形でも探すだけで、入力どおりの形でも探す（名前と同じ言葉なら、そちらが上に来る）
const PREFIXES = "全国の 全国 都道府県別の 都道府県別 市区町村別の 市区町村別 町丁目別の 町丁目別 地域別の 地域別 都道府県の 市区町村の";
const SUFFIXES = `ランキング ランク 順位 一覧 地図 マップ データ 統計 比較 が多い が少ない が高い が低い が良い がいい が悪い
  の多さ の少なさ の高さ の低さ の良さ の悪さ 多い 少ない 高い 低い 良い 悪い の割合 割合 比率 率 パーセント の件数 件数 の人数 の数 数 別`;
// ほかの言葉と一緒に入れたときは、それだけでは探さない言葉
const STOP_WORDS = "ランキング 順位 一覧 地図 マップ データ 統計 都道府県 都道府県別 市区町村 市区町村別 町丁目 全国 比較 別";
// 言葉の切れ目とみなす助詞（漢字・カタカナとの境にあるときだけ切る）
const PARTICLES = new Set([..."のがをにでとやへはも"]);
const RATIO_SUFFIXES = new Set(["の割合", "割合", "比率", "率", "パーセント"].map(normalizeText));

interface Term { plain: string; reading: string }
interface Needle { parts: Term[]; weight: number }
interface Field { plain: string; reading: string; weight: number }

const readingIndex = new Map<string, [string, string][]>();
for (const pair of READINGS.trim().split(/\s+/)) {
  const [word, reading] = pair.split(":");
  const key = normalizeText(word);
  const list = readingIndex.get(key[0]) ?? [];
  list.push([key, normalizeText(reading)]);
  readingIndex.set(key[0], list);
}
for (const list of readingIndex.values()) list.sort((a, b) => b[0].length - a[0].length);

/** そろえた文字列の中の、辞書にある言葉を読みに直す（長い言葉から先に当てる） */
export function toReading(s: string): string {
  let out = "";
  for (let i = 0; i < s.length;) {
    const hit = readingIndex.get(s[i])?.find(([k]) => s.startsWith(k, i));
    out += hit ? hit[1] : s[i];
    i += hit ? hit[0].length : 1;
  }
  return out;
}

const term = (text: string): Term => {
  const plain = normalizeText(text);
  return { plain, reading: toReading(plain) };
};
const words = (s: string) => s.trim().split(/\s+/).map(normalizeText).filter(Boolean);
const prefixes = words(PREFIXES);
const suffixes = words(SUFFIXES).sort((a, b) => b.length - a.length);
const stopWords = new Set(words(STOP_WORDS));

const related: { words: Term[]; targets: string[] }[] = RELATED.trim().split("\n").flatMap((line) => {
  if (line.includes("=")) {
    const group = line.split("=").map((s) => s.trim());
    return group.map((w) => ({ words: [term(w)], targets: group.filter((o) => o !== w) }));
  }
  const [left, right] = line.split(">");
  return [{ words: left.trim().split(/\s+/).map(term), targets: right.trim().split(/\s+/) }];
});

/**
 * 前後の決まった言葉（「全国の」「ランキング」「が多い」「率」など）を外す。率・割合を外したら ratio を立てる。
 * start は外した後の言葉が元の文字列のどこから始まるか
 */
function stripAffixes(s: string): { stem: string; ratio: boolean; start: number } {
  let stem = s;
  let ratio = false;
  let start = 0;
  for (let changed = true; changed && stem;) {
    changed = false;
    for (const p of prefixes) {
      if (stem.startsWith(p) && stem.length > p.length) {
        stem = stem.slice(p.length);
        start += p.length;
        changed = true;
      }
    }
    for (const x of suffixes) {
      if (stem.endsWith(x)) {
        stem = stem.slice(0, -x.length);
        if (RATIO_SUFFIXES.has(x)) ratio = true;
        changed = true;
        break;
      }
    }
    // 外した後に残った端の助詞（「子供が」の「が」など）
    while (stem.length > 1 && PARTICLES.has(stem[stem.length - 1])) { stem = stem.slice(0, -1); changed = true; }
  }
  return { stem, ratio, start };
}

/** 漢字・カタカナとの境にある助詞で、入力を言葉に分ける（「子供の数」→ 子供・数）。ひらがなだけの言葉は切らない */
function splitParticles(raw: string): string[] {
  const s = raw.normalize("NFKC").replace(PUNCT, "");
  const isHira = (c: string | undefined) => !!c && /[ぁ-ゖ]/.test(c);
  const parts: string[] = [];
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    if (PARTICLES.has(s[i]) && (!isHira(s[i - 1]) || !isHira(s[i + 1])) && i > 0 && i < s.length - 1) {
      parts.push(cur);
      cur = "";
    } else cur += s[i];
  }
  parts.push(cur);
  return parts.filter((p) => p && !(p.length === 1 && isHira(p)));
}

function fieldsOf(d: SearchDoc): Field[] {
  const f = (text: string | undefined, weight: number): Field[] => {
    if (!text) return [];
    const plain = normalizeText(text);
    return plain ? [{ plain, reading: toReading(plain), weight }] : [];
  };
  return [
    ...f(d.name, 10),
    ...(d.alt ?? []).flatMap((a) => f(a, 8)),
    ...(d.keywords ?? []).flatMap((a) => f(a, 2)),
    ...f(d.category, 4),
    ...f(d.genre, 2),
    ...f(d.description, 2),
  ];
}

function partScore(p: Term, f: Field): number {
  const quality = (text: string, q: string) => (text === q ? 2 : text.startsWith(q) ? 1.5 : text.includes(q) ? 1 : 0);
  const plain = quality(f.plain, p.plain);
  const score = plain || (p.reading ? quality(f.reading, p.reading) * 0.95 : 0);
  return score * f.weight;
}

function needleScore(n: Needle, fields: Field[]): number {
  let sum = 0;
  for (const p of n.parts) {
    let best = 0;
    for (const f of fields) best = Math.max(best, partScore(p, f));
    if (!best) return 0;
    sum += best;
  }
  return (sum / n.parts.length) * n.weight;
}

/** 文字の2つ組の重なり（Dice 係数）。打ち間違いを拾うのに使う */
function bigramSimilarity(a: string, b: string): number {
  if (a.length < 2 || b.length < 2) return 0;
  const grams = (s: string) => {
    const m = new Map<string, number>();
    for (let i = 0; i < s.length - 1; i++) m.set(s.slice(i, i + 2), (m.get(s.slice(i, i + 2)) ?? 0) + 1);
    return m;
  };
  const ga = grams(a);
  const gb = grams(b);
  let common = 0;
  for (const [g, n] of ga) common += Math.min(n, gb.get(g) ?? 0);
  return (2 * common) / (a.length - 1 + b.length - 1);
}

export class IndicatorSearch<T extends SearchDoc> {
  private docs: { doc: T; fields: Field[]; index: number }[];

  constructor(docs: T[]) {
    this.docs = docs.map((doc, index) => ({ doc, fields: fieldsOf(doc), index }));
  }

  /** 1つの言葉から、探す形（入力どおり・前後を外した形・近い意味の言葉）を作る */
  private needlesOf(raw: string): Needle[] {
    const c = normalizeText(raw);
    const out: Needle[] = [];
    const add = (parts: string[], weight: number) => {
      const ts = parts.map(term).filter((t) => t.plain);
      if (ts.length) out.push({ parts: ts, weight });
    };
    add([c], 1);
    const { stem, ratio, start } = stripAffixes(c);
    // 近い意味の言葉: 前後を外した部分にかかる言葉だけ（「所得の高さ」の「高さ」で標高を出さない）。
    // 1文字の言葉（雨・坂など）は、それだけを入れたときだけ。ほかの言葉の一部になっている言葉（「小学生」の「学生」）は使わない
    const core = stem || c;
    const coreReading = toReading(core);
    const coreStart = stem ? start : 0;
    const hits: { rule: (typeof related)[number]; word: Term; rest: string }[] = [];
    for (const rule of related) {
      for (const w of rule.words) {
        if (w.plain.length === 1 && core !== w.plain) continue;
        let rest: string | null = null;
        for (let at = c.indexOf(w.plain); at >= 0; at = c.indexOf(w.plain, at + 1)) {
          if (at < coreStart + core.length && at + w.plain.length > coreStart) {
            rest = c.slice(0, at) + c.slice(at + w.plain.length);
            break;
          }
        }
        if (rest === null && w.reading && coreReading.includes(w.reading)) rest = coreReading.replace(w.reading, "");
        if (rest === null) continue;
        hits.push({ rule, word: w, rest: rest ? stripAffixes(rest).stem : "" });
        break;
      }
    }
    const used = hits.filter((h) => !hits.some((o) => o.word.plain.length > h.word.plain.length && o.word.plain.includes(h.word.plain)));
    // 近い意味の言葉で当たる指標は、入力どおりの言葉を含む名前より下にする
    for (const { rule, rest } of used) {
      for (const t of rule.targets) {
        if (rest) add([t, rest], 0.65);
        add([t], rest ? 0.45 : 0.65);
      }
    }
    if (stem && stem !== c && (stem.length >= 2 || !used.length)) {
      // 入力どおりの言葉を含む名前（「子どもの数」→ …子どもの数）を、外した形で始まる名前（子どものいる…）より上にする
      add([stem], 0.6);
      if (ratio) add([stem, "割合"], 0.9);
    }
    return out;
  }

  private scores(needles: Needle[]): Map<number, number> {
    const m = new Map<number, number>();
    for (const d of this.docs) {
      let best = 0;
      for (const n of needles) best = Math.max(best, needleScore(n, d.fields));
      if (best > 0) m.set(d.index, best);
    }
    return m;
  }

  /** 1つの言葉の当たり。どれにも当たらなければ、助詞で分けた言葉それぞれの当たりにする */
  private chunkScores(raw: string, split = true): Map<number, number>[] {
    const m = this.scores(this.needlesOf(raw));
    if (m.size || !split) return m.size ? [m] : [];
    const parts = splitParticles(raw);
    if (parts.length < 2) return [];
    return parts.flatMap((p) => (stripAffixes(normalizeText(p)).stem ? this.chunkScores(p, false) : []));
  }

  search(query: string): SearchResult<T>[] {
    const chunks = query.normalize("NFKC").split(/[\s、,・/]+/).filter((c) => normalizeText(c));
    if (!chunks.length) return [];
    const meaningful = chunks.filter((c) => !stopWords.has(normalizeText(c)));
    const groups = (meaningful.length ? meaningful : chunks).flatMap((c) => this.chunkScores(c));
    let results: { index: number; score: number; matched: number }[] = [];
    if (groups.length) {
      const total = new Map<number, { score: number; matched: number }>();
      for (const g of groups) {
        for (const [i, s] of g) {
          const t = total.get(i) ?? { score: 0, matched: 0 };
          t.score += s;
          t.matched += 1;
          total.set(i, t);
        }
      }
      // すべての言葉に当たるものだけ。ないときは、いちばん多くの言葉に当たるもの
      const most = Math.max(...[...total.values()].map((t) => t.matched));
      results = [...total].filter(([, t]) => t.matched === most).map(([index, t]) => ({ index, ...t }));
      // 名前に当たるものがあるときは、説明の文だけに当たるものは出さない
      const top = Math.max(...results.map((r) => r.score));
      results = results.filter((r) => r.score >= top * 0.25);
    } else {
      // どの言葉にも当たらないときは、打ち間違いとみて似た名前を探す
      const q = normalizeText(query);
      const qr = toReading(q);
      for (const d of this.docs) {
        const names = d.fields.filter((f) => f.weight >= 8);
        const sim = Math.max(0, ...names.map((f) => Math.max(bigramSimilarity(q, f.plain), bigramSimilarity(qr, f.reading))));
        if (sim >= 0.45) results.push({ index: d.index, score: sim, matched: 1 });
      }
    }
    results.sort((a, b) => b.score - a.score || a.index - b.index);
    return results.map((r) => ({ doc: this.docs[r.index].doc, score: r.score }));
  }
}
