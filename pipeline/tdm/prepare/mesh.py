"""地域メッシュ（100m の土地利用細分メッシュ）の位置と、国土数値情報のメッシュの DBF の読み取り。

メッシュコード（10桁）は 1次メッシュ（4桁、緯度40分×経度1度）・2次（2桁、8×8）・3次（2桁、10×10）・
100m細分（2桁、10×10）。1次メッシュの中は800行×800列のマスで、1マスは緯度3秒×経度4.5秒
（東京あたりで南北約93m・東西約113m）。全国の行の番号は緯度×1200、列の番号は（経度−100）×800 で、
マスの南西の角の位置を表す。
昭和51年度〜平成9年度の土地利用細分メッシュは日本測地系（旧測地系）のメッシュで、マスの中心を世界測地系に
直してから使う（tokyo_to_jgd。換算の誤差は数m程度で、100mのマスに比べて小さい）。
"""
from __future__ import annotations

import struct

import numpy as np

ROWS_PER_DEG = 1200   # 南北のマスの数（1度あたり、3秒間隔）
COLS_PER_DEG = 800    # 東西のマスの数（1度あたり、4.5秒間隔）
CELLS = 800           # 1次メッシュの中の行・列の数


def first_mesh_origin(code4: str) -> tuple[int, int]:
    """1次メッシュの南西の角の、全国のマスの行・列の番号。"""
    return int(code4[:2]) * CELLS, int(code4[2:4]) * CELLS


def first_mesh_of(row: int, col: int) -> str:
    return f"{row // CELLS:02d}{col // CELLS:02d}"


def cell_centers(rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """全国のマスの行・列の番号 → マスの中心の経度・緯度（メッシュと同じ測地系）。"""
    return 100 + (cols + 0.5) / COLS_PER_DEG, (rows + 0.5) / ROWS_PER_DEG


# 日本測地系 → 世界測地系の簡易な換算（国土地理院「世界測地系と日本測地系の換算」で示されている近似式。
# 日本の陸域で誤差は数m程度）
def tokyo_to_jgd(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat_w = lat - 0.00010695 * lat + 0.000017464 * lon + 0.0046017
    lon_w = lon - 0.000046038 * lat - 0.000083043 * lon + 0.010040
    return lon_w, lat_w


def jgd_to_tokyo(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat_t = lat + 0.00010696 * lat - 0.000017467 * lon - 0.0046020
    lon_t = lon + 0.000046047 * lat + 0.000083049 * lon - 0.010041
    return lon_t, lat_t


def dbf_fields(data: bytes) -> dict[str, tuple[int, int]]:
    """DBF の列名 → (行の中の位置, 長さ)。"""
    header_len = struct.unpack("<H", data[8:10])[0]
    fields: dict[str, tuple[int, int]] = {}
    offset = 1   # 各行の先頭1バイトは削除の印
    for i in range(32, header_len - 1, 32):
        desc = data[i:i + 32]
        if desc[0] == 0x0D:
            break
        name = desc[:11].split(b"\0", 1)[0].decode("ascii")
        size = desc[16]
        fields[name] = (offset, size)
        offset += size
    return fields


def read_dbf_columns(data: bytes, names: list[str]) -> list[np.ndarray]:
    """DBF の文字の列を、行ごとの bytes の配列（numpy の S 型）として読む。1次メッシュ1つで約64万行あるため、
    pyshp で1行ずつ読むより速く、まとめて読む。"""
    n, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields = dbf_fields(data)
    records = np.frombuffer(data, dtype=np.uint8, count=n * record_len, offset=header_len).reshape(n, record_len)
    live = records[:, 0] != ord("*")
    out = []
    for name in names:
        start, size = fields[name]
        col = np.ascontiguousarray(records[live, start:start + size])
        out.append(col.view(f"S{size}").ravel())
    return out


def mesh_rows_cols(codes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """10桁のメッシュコード（S10 の配列）→ 1次メッシュの中の行・列（0〜799）。"""
    d = codes.view(np.uint8).reshape(-1, 10).astype(np.int32) - ord("0")
    if (d < 0).any() or (d > 9).any():
        raise ValueError("メッシュコードに数字以外があります")
    rows = d[:, 4] * 100 + d[:, 6] * 10 + d[:, 8]
    cols = d[:, 5] * 100 + d[:, 7] * 10 + d[:, 9]
    return rows, cols


def mesh_grid(data: bytes, name: str, codes: dict[bytes, int], mesh: str) -> np.ndarray:
    """メッシュの DBF（最初の列がメッシュコード、次の列が土地利用の区分。列名は L03b_001・L03b_u_001 など年度で違う）
    → 1次メッシュの800×800の配列（行0が南端）。値は codes で区分の番号にし、レコードのないマスは0。
    codes にない区分があれば止める（年度によって区分が違うので、取り違えに気づくように）。"""
    code_field, value_field = list(dbf_fields(data))[:2]
    code_col, value_col = read_dbf_columns(data, [code_field, value_field])
    if len(code_col) and not (code_col.astype("S4") == mesh.encode()).all():
        raise ValueError(f"{name}: 1次メッシュ {mesh} 以外のメッシュがあります")
    rows, cols = mesh_rows_cols(code_col)
    uniq, inverse = np.unique(np.char.strip(value_col), return_inverse=True)
    unknown = sorted(u.decode() for u in uniq if u not in codes)
    if unknown:
        raise ValueError(f"{name}: 知らない土地利用の区分 {unknown}")
    grid = np.zeros((CELLS, CELLS), dtype=np.uint8)
    if len(uniq):
        grid[rows, cols] = np.array([codes[u] for u in uniq], dtype=np.uint8)[inverse.ravel()]
    return grid
