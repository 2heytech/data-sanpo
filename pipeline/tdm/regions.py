"""都道府県・市区町村のコードと地域区分。"""
from __future__ import annotations

import os

# 全国地方公共団体コードの都道府県（2桁）。国勢調査の小地域は都道府県ごとに取得・取り込む
PREFECTURES = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県", "05": "秋田県", "06": "山形県",
    "07": "福島県", "08": "茨城県", "09": "栃木県", "10": "群馬県", "11": "埼玉県", "12": "千葉県",
    "13": "東京都", "14": "神奈川県", "15": "新潟県", "16": "富山県", "17": "石川県", "18": "福井県",
    "19": "山梨県", "20": "長野県", "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県",
    "25": "滋賀県", "26": "京都府", "27": "大阪府", "28": "兵庫県", "29": "奈良県", "30": "和歌山県",
    "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県", "36": "徳島県",
    "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県", "41": "佐賀県", "42": "長崎県",
    "43": "熊本県", "44": "大分県", "45": "宮崎県", "46": "鹿児島県", "47": "沖縄県",
}
TOKYO = "13"
# 旧来の名前（東京都だけを扱っていたころの定数）。都の機関のデータの取込で使う
PREF_CODE = TOKYO
PREF_ENTITY = "pref-13"


def selected_prefectures(value: str | None = None) -> list[str]:
    """取り込む都道府県。環境変数 TDM_PREFS（例: "13,14"）で絞れる。空か "all" なら全国。"""
    value = (value if value is not None else os.environ.get("TDM_PREFS", "")).strip()
    if not value or value == "all":
        return list(PREFECTURES)
    codes = [c.strip().zfill(2) for c in value.split(",") if c.strip()]
    unknown = [c for c in codes if c not in PREFECTURES]
    if unknown:
        raise ValueError(f"都道府県コードが不正です: {unknown}")
    return sorted(set(codes))


def prefecture_entity_id(pref_code: str) -> str:
    return f"pref-{pref_code}"


def municipality_entity_id(city_code5: str) -> str:
    return f"muni-{city_code5}"


def small_area_entity_id(key_code: str) -> str:
    return f"area-{key_code}"


def prefecture_of(entity_id: str) -> str:
    """地域ID（muni-13101・area-13101001001 など）から都道府県コード2桁を返す。"""
    return entity_id.split("-", 1)[1][:2]


def region_of(city_code5: str, designated_city: str | None = None) -> str | None:
    """地域区分。東京都は 区部 / 多摩 / 島しょ、政令指定都市の区は市の名前、それ以外はなし。"""
    if city_code5[:2] == TOKYO:
        city = int(city_code5[2:])
        if 100 <= city < 200:
            return "区部"
        if 200 <= city < 360:  # 市部と西多摩郡（303〜308）
            return "多摩"
        return "島しょ"
    return designated_city or None
