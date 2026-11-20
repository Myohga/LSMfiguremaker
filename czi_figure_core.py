# -*- coding: utf-8 -*-
r"""
czi_figure_core.py
==================
.czi から「ラベル付き合成画像 PNG」（論文・発表用の 1 パネル）を作るエンジン。

  ┌──────────────────────────────┐
  │   Hoechst / MAP2 / TBR1      │ ← 上：タイトル枠（抗体名をその色で）
  └──────────────────────────────┘
  ┌──┐ ┌──────────────────────────┐
  │縦│ │                          │
  │書│ │      合成画像            │ ← 中央：色付けしたチャンネルの screen 合成
  │き│ │                 ▬▬ 50 µm │ ← 右下：スケールバー（µm/px から正確に換算）
  └──┘ └──────────────────────────┘

・これは作図ツールであり、定量解析はしない。
・.czi の読み込みは run_analysis_9th.py の関数をそのまま使う（エンジンは一切変更しない）。
・GUI に依存しない。設定は JSON にできる dict 1 つで、
      render_panel(config) -> PIL.Image
  が全て。GUI（czi_figure_gui.py）も CLI もこれを呼ぶだけ。

描画は Pillow で行う。出力のピクセル数を直接決められるので、
スケールバーを「µm ÷ µm/px」の整数ピクセルで正確に引ける。

CLI の例:
    python czi_figure_core.py "xxx.czi" --list
    python czi_figure_core.py "xxx.czi" --label "Glu DIV 30" ^
        --channels "DAPI:Hoechst:blue,AF488:MAP2:green,AF647:TBR1:red"
    python czi_figure_core.py "yyy.czi" --config 体裁.json
"""
from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo


# =====================================================================
# 0. 解析エンジン（.czi リーダ）の読み込み
# =====================================================================
ENGINE_CANDIDATES = ("run_analysis_9th", "run_analysis_10th", "run_analysis_8th")
_ENGINE = None


def load_engine(path: str | None = None):
    """
    run_analysis_9th.py を import して返す（中身は一切書き換えない）。

    path を渡せばそのファイル、無ければこのスクリプトと同じフォルダ →
    sys.path の順に探す。ファイル指定で読むときは exec の前に sys.modules へ
    登録しておかないと、エンジン内の @dataclass が落ちる。
    """
    global _ENGINE
    if _ENGINE is not None and path is None:
        return _ENGINE
    path = path or os.environ.get("CZI_FIGURE_ENGINE")
    if path:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"解析エンジンが見つかりません: {path}")
        name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _ENGINE = mod
        return mod

    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    for nm in ENGINE_CANDIDATES:
        try:
            _ENGINE = importlib.import_module(nm)
            return _ENGINE
        except ImportError:
            continue
    raise ImportError(
        "run_analysis_9th.py が見つかりません。\n"
        "czi_figure_core.py と同じフォルダに置くか、--engine でパスを指定してください。")


# =====================================================================
# 1. 色
# =====================================================================
# 画像に乗せる LUT の色（純色）
PALETTE: dict[str, tuple[int, int, int]] = {
    "blue":    (0, 0, 255),
    "green":   (0, 255, 0),
    "red":     (255, 0, 0),
    "orange":  (255, 128, 0),
    "magenta": (255, 0, 255),
    "cyan":    (0, 255, 255),
    "yellow":  (255, 255, 0),
    "gray":    (255, 255, 255),
}
# タイトル文字の色。白地の上で読めるよう、純色より少し濃く/落ち着かせる。
TEXT_COLORS: dict[str, tuple[int, int, int]] = {
    "blue":    (0, 112, 192),
    "green":   (60, 190, 60),
    "red":     (230, 0, 0),
    "orange":  (235, 120, 0),
    "magenta": (200, 0, 200),
    "cyan":    (0, 160, 190),
    "yellow":  (200, 160, 0),
    "gray":    (0, 0, 0),
}
# スロット既定の色と表示名
DEFAULT_SLOT_COLOR = {"DAPI": "blue", "AF488": "green", "AF555": "orange", "AF647": "red"}
SLOT_ORDER = ("DAPI", "AF488", "AF555", "AF647")


def parse_hex(color: str) -> tuple[int, int, int] | None:
    """'#RRGGBB'（ZEN の '#AARRGGBB' も可）→ (r, g, b)。色名なら None。"""
    m = re.fullmatch(r"#?(?:[0-9A-Fa-f]{2})?([0-9A-Fa-f]{6})", str(color or "").strip())
    if not m or str(color).strip().lower() in PALETTE:
        return None
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def is_color(color: str) -> bool:
    return color in PALETTE or parse_hex(color) is not None


def effective_color(name: str, colorblind_magenta: bool) -> str:
    """色覚対応トグル：赤（ZEN の赤系 #FF0014 なども含む）をマゼンタへ一括で置き換える。"""
    if colorblind_magenta:
        if name == "red":
            return "magenta"
        rgb = parse_hex(name)
        if rgb and rgb[0] >= 200 and rgb[1] < 80 and rgb[2] < 80:
            return "magenta"
    return name


def lut_rgb(color: str) -> tuple[int, int, int]:
    """画像に乗せる色（色名 または #RRGGBB）。"""
    return PALETTE.get(color) or parse_hex(color) or PALETTE["gray"]


def text_rgb(color: str) -> tuple[int, int, int]:
    """タイトル文字の色。#RRGGBB は白地で読めるよう、明るすぎる色だけ暗くする。"""
    if color in TEXT_COLORS:
        return TEXT_COLORS[color]
    r, g, b = lut_rgb(color)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b      # 0〜255
    k = min(1.0, 150.0 / lum) if lum > 0 else 1.0     # 例：#00FF33（明るい緑）は暗めの緑に
    return int(r * k), int(g * k), int(b * k)


# =====================================================================
# 2. .czi の読み込み
# =====================================================================
@dataclass
class CziData:
    path: str
    scene: int
    planes: np.ndarray                 # (C, Y, X)、Z は z_reduce 済み、元の dtype のまま
    chans: list[dict]                  # エンジンが返すチャンネル情報（name/emission_nm/contrast）
    slots: list[str | None]            # 各チャンネルの蛍光色素スロット（透過光は None）
    um_px: float | None
    n_scenes: int = 1
    _sorted: dict[int, np.ndarray] = field(default_factory=dict, repr=False)

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def index_of(self, ch: dict) -> int | None:
        """設定のチャンネル項目をこのファイルの C 番号へ解決する（スロット優先、無ければ番号）。"""
        slot = ch.get("slot")
        if slot and slot in self.slots:
            return self.slots.index(slot)
        idx = ch.get("index")
        if idx is not None and 0 <= int(idx) < self.planes.shape[0] and not slot:
            return int(idx)
        return None

    def percentile(self, c: int, q: float) -> float:
        """表示レンジ用のパーセンタイル。間引いて並べ替えた配列をキャッシュして高速に引く。"""
        if c not in self._sorted:
            sub = self.planes[c][::2, ::2].ravel()
            self._sorted[c] = np.sort(sub)
        s = self._sorted[c]
        q = min(max(float(q), 0.0), 100.0)
        return float(s[int(round(q / 100.0 * (s.size - 1)))])

    def percentile_of(self, c: int, value: float) -> float:
        """percentile() の逆：輝度値がそのチャンネルの何 % 点にあたるか（スライダー用）。"""
        self.percentile(c, 0)                     # 並べ替え配列を用意
        s = self._sorted[c]
        i = int(np.searchsorted(s, value, side="left"))
        return 100.0 * min(i, s.size - 1) / max(1, s.size - 1)

    def channel_max(self, c: int) -> float:
        self.percentile(c, 0)
        return float(self._sorted[c][-1])


_CACHE: dict[tuple, CziData] = {}


def load_czi(path: str, scene: int = 0, z_reduce: str = "max") -> CziData:
    """.czi の 1 シーンを読み、Z を 1 枚に潰して返す（同じ引数ならキャッシュを返す）。"""
    key = (os.path.abspath(path), int(scene), z_reduce)
    if key in _CACHE:
        return _CACHE[key]
    ra = load_engine()
    arr, chans, um_px, _um_z = ra._read_czi_raw(path, int(scene), quiet=True)
    planes = np.stack([ra._reduce_z(arr[c], "max" if z_reduce == "none" else z_reduce)
                       for c in range(arr.shape[0])])
    slots = [ra._slot_for_channel(chans[c]) if c < len(chans) else None
             for c in range(planes.shape[0])]
    data = CziData(path=path, scene=int(scene), planes=planes, chans=chans,
                   slots=slots, um_px=um_px, n_scenes=ra.count_czi_scenes(path))
    _CACHE.clear()          # 大きな配列を溜め込まない（直近 1 枚だけ持つ）
    _CACHE[key] = data
    return data


# =====================================================================
# 2b. ZEN の表示設定（.czi の DisplaySetting）
# =====================================================================
# ZEN は「最後に表示したときの」チャンネルごとの色・黒・白・ガンマを .czi の XML に保存している：
#   <DisplaySetting><Channels><Channel Id="Channel:2">
#       <Low>0.0</Low> <High>0.2747</High> <Gamma>..</Gamma>   ← 0〜1（BitCountRange の最大値に対する割合）
#       <BitCountRange>16</BitCountRange> <Color>#FF0076FF</Color>（#AARRGGBB）
# ZEN は既定値と同じ項目を書かない。手元の .czi では Low（黒）はほぼ常に省略＝0、
# 調整していないチャンネルは High（白）も省略されている＝最大値（ZEN の既定の全範囲）と解釈する。
def read_zen_display(path: str) -> list[dict]:
    """ZEN の表示設定をチャンネルごとに返す。読めなければ空リスト。"""
    try:
        import czifile
        czi = czifile.CziFile(path)
        try:
            xml = czi.metadata()
        finally:
            czi.close()
    except Exception:
        return []
    blocks = [b for b in re.findall(r"<DisplaySetting>.*?</DisplaySetting>", xml, re.S)
              if "<Channel " in b]
    if not blocks:
        return []
    out = []
    for i, chunk in enumerate(re.findall(r"<Channel\b.*?</Channel>", blocks[-1], re.S)):
        def tag(t):
            m = re.search(rf"<{t}>([^<]*)</{t}>", chunk)
            return m.group(1).strip() if m else None

        def num(t):
            v = tag(t)
            try:
                return float(v) if v not in (None, "") else None
            except ValueError:
                return None
        idm = re.search(r'\bId="Channel:(\d+)"', chunk)
        em = num("DyeMaxEmission")
        out.append({
            "index": int(idm.group(1)) if idm else i,
            "name": (re.search(r'\bName="([^"]*)"', chunk) or [None, ""])[1],
            "dye": tag("DyeName") or tag("ShortName") or "",
            "short": tag("ShortName") or "",
            "emission_nm": em,
            "illumination": tag("IlluminationType"),
            "color": tag("Color"),
            "low": num("Low"), "high": num("High"), "gamma": num("Gamma"),
            "bits": int(num("BitCountRange") or 16),
        })
    return out


def _zen_slot(z: dict) -> str | None:
    ra = load_engine()
    if (z.get("illumination") or "Fluorescence").lower() != "fluorescence":
        return None
    for nm in (z["short"], z["dye"], z["name"]):
        s = ra.resolve_fluorophore(nm or "", z.get("emission_nm"))
        if s:
            return s
    return None


def apply_zen_display(cfg: dict, data: CziData) -> tuple[dict, list[str]]:
    """
    ZEN の表示設定を cfg に当てた新しい cfg と、説明メッセージのリストを返す。
    変えるのは各チャンネルの 色・黒（下限）・白（上限）・ガンマ と合成方法（ZEN と同じ加算）だけ。
    抗体名・ON/OFF・ラベル・枠などはそのまま。
    """
    zen = read_zen_display(cfg["czi_path"])
    if not zen:
        return cfg, ["この .czi には ZEN の表示設定が保存されていません（今の表示のままです）。"]
    out = copy.deepcopy(cfg)
    notes: list[str] = []
    # ZEN のチャンネル番号（Channel:N）＝データの C 番号。念のため蛍光色素スロットでも照合する
    by_index: dict[int, dict] = {}
    for z in zen:
        slot = _zen_slot(z)
        i = z["index"]
        if 0 <= i < len(data.slots) and (slot is None or data.slots[i] in (None, slot)):
            by_index[i] = z
        elif slot in data.slots:
            by_index[data.slots.index(slot)] = z
    applied = 0
    for ch in out["channels"]:
        c = data.index_of(ch)
        z = by_index.get(c) if c is not None else None
        if z is None:
            continue
        maxv = float(2 ** z["bits"] - 1)
        lo = (z["low"] if z["low"] is not None else 0.0) * maxv
        hi = (z["high"] if z["high"] is not None else 1.0) * maxv
        ch.update(range_mode="absolute", low=round(lo), high=max(round(hi), round(lo) + 1),
                  gamma=round(z["gamma"], 2) if z["gamma"] is not None else 1.0)
        rgb = parse_hex(z["color"] or "")
        if rgb:
            ch["color"] = "#{:02X}{:02X}{:02X}".format(*rgb)
        applied += 1
        if z["high"] is None and ch.get("enabled"):
            notes.append(f"{ch['name']}: ZEN で白の位置が調整されていないため、全範囲"
                         f"（0〜{int(maxv)}）で表示しています。暗ければ上限を下げてください。")
    out["blend"] = "add"
    notes.insert(0, f"ZEN の表示設定を {applied} チャンネルに適用しました（色・黒・白・ガンマ、合成は加算）。")
    return out, notes


# =====================================================================
# 3. 設定（JSON にできる dict）
# =====================================================================
def _default_out_dir() -> str:
    """既定の保存先：OneDrive のドキュメント → 無ければ普通のドキュメント → ホーム。
    （OneDrive を使っていない PC で、存在しない OneDrive フォルダを作らないため）"""
    home = os.path.expanduser("~")
    for d in (os.path.join(home, "OneDrive", "Documents"), os.path.join(home, "Documents")):
        if os.path.isdir(d):
            return d
    return home


DEFAULT_OUT_DIR = _default_out_dir()

BASE_CONFIG: dict = {
    "version": 1,
    "czi_path": "",
    "scene": 0,
    "z_reduce": "max",
    "channels": [],               # 下の default_channel() の形の dict を並べた順にタイトルへ出る
    "label": "",                  # 左の縦書きラベル
    "title_sep": " / ",
    "show_title": True,
    "show_label": True,
    "scalebar": {"show": True, "um": 50.0, "text": ""},   # text 空なら "50 µm"
    "blend": "screen",            # screen / max / add
    "colorblind_magenta": False,
    "font_scale": 1.0,            # 文字と枠の大きさの倍率
    "upscale": 1,                 # 出力時の整数倍拡大（最近傍。画素値は変えない）
    "dpi": 300,
    "out_dir": DEFAULT_OUT_DIR,
}


def _guess_antibodies(filename: str) -> dict[str, str]:
    """
    ファイル名 "TBR1 rabbit647, MAP2 chicken488, CTIP2 rat555" のような書き方から
    {スロット: 抗体名} を推測する。外れても既定名に戻るだけ（ユーザーが直す前提の初期値）。
    """
    base = re.sub(r"^.*\]", "", os.path.splitext(os.path.basename(filename))[0])
    out: dict[str, str] = {}
    for name, nm in re.findall(r"([A-Za-z][A-Za-z0-9.\-]*)\s+[A-Za-z0-9]*?(488|555|647)\b", base):
        out.setdefault(f"AF{nm}", name)
    return out


def _guess_label(filename: str) -> str:
    """ファイル名先頭の [glu day30] のような括弧書きを左ラベルの初期値にする。"""
    m = re.search(r"\[([^\]]+)\]", os.path.basename(filename))
    return m.group(1).strip() if m else ""


def default_channel(data: CziData, c: int, guessed: dict[str, str]) -> dict:
    slot = data.slots[c]
    raw = (data.chans[c].get("name") if c < len(data.chans) else "") or f"ch{c}"
    if slot == "DAPI":
        name = "Hoechst" if "hoechst" in raw.lower() else "DAPI"
    elif slot:
        name = guessed.get(slot, slot)
    else:
        name = raw
    return {
        "index": c,
        "slot": slot,
        "name": name,
        "enabled": slot is not None,          # 透過光は既定で使わない
        "color": DEFAULT_SLOT_COLOR.get(slot, "gray"),
        "range_mode": "percentile",           # percentile / absolute
        "low": 0.1, "high": 99.8,             # percentile のとき [%]、absolute のとき輝度値
        "gamma": 1.0,                         # 中間調（ZEN と同じ向き。1 未満で明るく）
    }


def default_config(path: str, scene: int = 0) -> dict:
    """ファイルから既定設定を作る。チャンネル順は DAPI → 488 → 555 → 647 → その他。"""
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["czi_path"] = path
    cfg["scene"] = scene
    data = load_czi(path, scene, cfg["z_reduce"])
    guessed = _guess_antibodies(path)
    order = sorted(range(data.planes.shape[0]),
                   key=lambda c: (SLOT_ORDER.index(data.slots[c])
                                  if data.slots[c] in SLOT_ORDER else 99, c))
    cfg["channels"] = [default_channel(data, c, guessed) for c in order]
    cfg["label"] = _guess_label(path)
    return cfg


def merge_config(base: dict, override: dict) -> dict:
    """
    保存した体裁（override）を、ある .czi の既定設定（base）に重ねる。
    チャンネルは C 番号ではなくスロット（DAPI/AF488/…）で対応付ける。

    同じ .czi なら抗体名・左ラベルもそのまま使う。
    別の .czi に使い回すときは、色・ON/OFF・明るさ・並び順・体裁だけを移し、
    抗体名と左ラベルは「新しいファイル名から推測できたもの」を優先する
    （PAX6 のファイルに前の TBR1 という名前が残る事故を防ぐ）。推測できなければ保存側の名前を使う。
    """
    out = copy.deepcopy(base)
    same = (os.path.normcase(os.path.abspath(override.get("czi_path") or "")) ==
            os.path.normcase(os.path.abspath(base.get("czi_path") or "")))
    guessed = {} if same else _guess_antibodies(base.get("czi_path", ""))
    for k, v in override.items():
        if k in ("czi_path", "scene", "version"):
            continue
        if k == "label" and not same and base.get("label"):
            continue
        if k == "channels":
            by_slot = {c.get("slot"): c for c in v if c.get("slot")}
            for ch in out["channels"]:
                if ch.get("slot") in by_slot:
                    src = by_slot[ch["slot"]]
                    # Hoechst/DAPI の別はメタデータから決まるので、別ファイルでは新しい方を信じる
                    keep_name = ch["slot"] in guessed or (not same and ch["slot"] == "DAPI")
                    ch.update({kk: vv for kk, vv in src.items()
                               if kk != "index" and not (kk == "name" and keep_name)})
            # 並び順も保存側に合わせる
            rank = {c.get("slot"): i for i, c in enumerate(v)}
            out["channels"].sort(key=lambda c: rank.get(c.get("slot"), 99))
            # 保存側から来た名前が、新しいファイル名から推測した別チャンネルの名前と
            # かぶったら（例：前は AF555=CTIP2、今回は AF488=CTIP2）、スロット名に戻す
            taken = {n for s, n in guessed.items()}
            for ch in out["channels"]:
                if ch.get("slot") and ch["slot"] not in guessed and ch.get("name") in taken:
                    ch["name"] = ch["slot"]
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


# =====================================================================
# 4. 合成画像
# =====================================================================
def display_range(data: CziData, c: int, ch: dict) -> tuple[float, float]:
    """そのチャンネルの表示レンジ (下限, 上限) を輝度値で返す。"""
    if ch.get("range_mode", "percentile") == "absolute":
        lo, hi = float(ch["low"]), float(ch["high"])
    else:
        lo, hi = data.percentile(c, ch["low"]), data.percentile(c, ch["high"])
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def to_unit(plane: np.ndarray, lo: float, hi: float, gamma: float = 1.0) -> np.ndarray:
    """
    表示レンジで 0..1 に変換（8bit 化と等価、量子化は最後に 1 回だけ）。
    gamma は ZEN / ImageJ と同じ向きの「出力 = 入力 ^ gamma」：
    1.0 で直線、1 未満で中間調が明るく（暗い構造が見える）、1 より大きいと中間調が暗くなる。
    下限（黒）と上限（白）の位置は gamma を変えても動かない。
    """
    u = np.clip((plane.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)
    g = float(gamma or 1.0)
    return u if abs(g - 1.0) < 1e-6 else np.power(u, g, dtype=np.float32)


def channel_unit(data: CziData, c: int, ch: dict) -> np.ndarray:
    lo, hi = display_range(data, c, ch)
    return to_unit(data.planes[c], lo, hi, ch.get("gamma", 1.0))


def composite_rgb(data: CziData, cfg: dict) -> np.ndarray:
    """有効なチャンネルを色付けして合成し、(H, W, 3) uint8 を返す。"""
    h, w = data.planes.shape[1:]
    out = np.zeros((h, w, 3), np.float32)
    blend = cfg.get("blend", "screen")
    for ch in cfg["channels"]:
        if not ch.get("enabled"):
            continue
        c = data.index_of(ch)
        if c is None:
            continue
        u = channel_unit(data, c, ch)
        rgb = np.array(lut_rgb(effective_color(ch["color"], cfg.get("colorblind_magenta"))),
                       np.float32) / 255.0
        layer = u[..., None] * rgb
        if blend == "max":
            out = np.maximum(out, layer)
        elif blend == "add":
            out = np.minimum(out + layer, 1.0)
        else:  # screen
            out = 1.0 - (1.0 - out) * (1.0 - layer)
    return (out * 255.0 + 0.5).astype(np.uint8)


def gray_u8(data: CziData, c: int, ch: dict) -> np.ndarray:
    return (channel_unit(data, c, ch) * 255.0 + 0.5).astype(np.uint8)


# =====================================================================
# 5. 注釈（タイトル枠・縦書きラベル枠・スケールバー）
# =====================================================================
_FONT_LATIN = [r"C:\Windows\Fonts\arialbd.ttf", "DejaVuSans-Bold.ttf",
               "/Library/Fonts/Arial Bold.ttf"]
_FONT_CJK = [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
             r"C:\Windows\Fonts\msgothic.ttc"]


def get_font(size: int, text: str = "") -> ImageFont.FreeTypeFont:
    """太字サンセリフ。日本語を含むときは游ゴシック Bold などへ切り替える。"""
    size = max(6, int(size))
    cands = _FONT_CJK + _FONT_LATIN if re.search(r"[^\x00-\x7f°µ±×–—]", text) else _FONT_LATIN + _FONT_CJK
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _fit_font(text: str, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    font = get_font(size, text)
    while size > 6 and font.getlength(text) > max_w:
        size = int(size * 0.92)
        font = get_font(size, text)
    return font


def scalebar_px(um: float, um_px: float, upscale: int = 1) -> int:
    """スケールバーの長さ[px]。メタデータの µm/px から正確に換算する。"""
    return int(round(float(um) / float(um_px) * upscale))


def _fmt_um(um: float) -> str:
    return f"{um:g} µm"


def scalebar_geometry(W: int, H: int, cfg: dict, um_px: float | None) -> dict | None:
    """
    スケールバーと長さ表記の位置（画像本体の左上が原点、px）。PNG の描画と PPTX の図形が共有する。
    バーは x0..x1-1, y0..y1-1 の矩形、文字は (text_x, text_y) を「中央・ベースライン」に置く。
    """
    sb = cfg.get("scalebar", {})
    if not sb.get("show", True):
        return None
    if not um_px:
        print("[警告] µm/px が不明なのでスケールバーを描けません。")
        return None
    u = W / 1000.0
    up = int(cfg.get("upscale", 1))
    length = scalebar_px(sb.get("um", 50), um_px, up)
    fs = cfg.get("font_scale", 1.0)
    bar_h = max(2, round(14 * u * fs))
    margin = round(35 * u)
    x1 = W - margin
    x0 = x1 - length
    y1 = H - margin
    y0 = y1 - bar_h
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "length_px": length,
            "um": float(sb.get("um", 50)), "um_px": um_px / up,
            "text": sb.get("text") or _fmt_um(float(sb.get("um", 50))),
            "font_px": round(42 * u * fs),
            "text_x": (x0 + x1) / 2, "text_y": y0 - round(8 * u)}


def draw_scalebar(img: Image.Image, cfg: dict, um_px: float | None, u: float | None = None
                  ) -> dict | None:
    """画像内右下に白いバーと長さ表記を描く。描いた位置を返す（検算用）。"""
    g = scalebar_geometry(img.width, img.height, cfg, um_px)
    if g is None:
        return None
    d = ImageDraw.Draw(img)
    d.rectangle([g["x0"], g["y0"], g["x1"] - 1, g["y1"] - 1], fill=(255, 255, 255))
    d.text((g["text_x"], g["text_y"]), g["text"], font=get_font(g["font_px"], g["text"]),
           fill=(255, 255, 255), anchor="ms")
    return g


def _title_segments(cfg: dict) -> list[tuple[str, tuple[int, int, int]]]:
    segs: list[tuple[str, tuple[int, int, int]]] = []
    for ch in cfg["channels"]:
        if not ch.get("enabled") or not ch.get("name"):
            continue
        if segs:
            segs.append((cfg.get("title_sep", " / "), (0, 0, 0)))
        col = effective_color(ch["color"], cfg.get("colorblind_magenta"))
        segs.append((ch["name"], text_rgb(col)))
    return segs


def panel_layout(W: int, H: int, cfg: dict) -> dict:
    """
    図セルの配置（すべて px）。PNG の描画と PPTX の図形配置が同じ数字を使うための共通計算。
    W, H は（拡大後の）画像本体の大きさ。
    """
    u = W / 1000.0                             # 長さの単位：画像幅の 1/1000
    fs = float(cfg.get("font_scale", 1.0))
    lw = max(2, round(4 * u * fs))
    gap = round(14 * u)
    m = round(6 * u)
    show_t, show_l = cfg.get("show_title", True), cfg.get("show_label", True)
    th = round(80 * u * fs) if show_t else 0
    lwid = round(100 * u * fs) if show_l else 0
    ox = m + (lwid + gap if show_l else 0)     # 画像の左上位置
    oy = m + (th + gap if show_t else 0)
    L = {"u": u, "lw": lw, "ox": ox, "oy": oy, "W": W, "H": H,
         "canvas": (ox + W + m, oy + H + m),
         "title_box": (ox, m, ox + W - 1, m + th) if show_t else None,
         "label_box": (m, oy, m + lwid, oy + H - 1) if show_l else None,
         "title_segments": _title_segments(cfg), "label": cfg.get("label", "")}
    # 枠に収まるよう縮めた後の文字サイズ（px）
    full = "".join(t for t, _ in L["title_segments"])
    L["title_px"] = (_fit_font(full, round(48 * u * fs), int(W * 0.94)).size
                     if show_t and full else round(48 * u * fs))
    L["label_px"] = (_fit_font(L["label"], round(62 * u * fs), int(H * 0.92)).size
                     if show_l and L["label"] else round(62 * u * fs))
    return L


def _draw_title(canvas: Image.Image, L: dict) -> None:
    d = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = L["title_box"]
    d.rectangle(L["title_box"], outline=(0, 0, 0), width=L["lw"])
    segs = L["title_segments"]
    if not segs:
        return
    full = "".join(s for s, _ in segs)
    font = get_font(L["title_px"], full)
    total = font.getlength(full)
    x = (x0 + x1) / 2 - total / 2
    cy = (y0 + y1) / 2
    for s, col in segs:
        f = get_font(font.size, s)
        d.text((x, cy), s, font=f, fill=col, anchor="lm")
        x += f.getlength(s)


def _draw_vertical_label(canvas: Image.Image, L: dict) -> None:
    d = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = L["label_box"]
    d.rectangle(L["label_box"], outline=(0, 0, 0), width=L["lw"])
    text = L["label"]
    if not text:
        return
    font = get_font(L["label_px"], text)
    l, t, r, b = font.getbbox(text, anchor="lm")
    tw, th = int(r - l) + 4, int(font.size * 1.4)
    tmp = Image.new("RGBA", (tw, th), (255, 255, 255, 0))
    ImageDraw.Draw(tmp).text((2 - l, th / 2), text, font=font, fill=(0, 0, 0, 255), anchor="lm")
    rot = tmp.rotate(90, expand=True)          # 下から上へ読む向き（見本と同じ）
    px = round((x0 + x1) / 2 - rot.width / 2)
    py = round((y0 + y1) / 2 - rot.height / 2)
    canvas.paste(rot, (px, py), rot)


def image_with_scalebar(img: Image.Image, cfg: dict, um_px: float | None
                        ) -> tuple[Image.Image, dict | None]:
    """画像本体にスケールバーだけを焼き込んだもの（PPTX ではこれが「画像」オブジェクトになる）。"""
    img = img.copy()
    return img, draw_scalebar(img, cfg, um_px, img.width / 1000.0)


def annotate(img: Image.Image, cfg: dict, um_px: float | None) -> tuple[Image.Image, dict]:
    """合成画像に 上タイトル枠・左ラベル枠・スケールバー を付けた図セルを作る。"""
    img, sb = image_with_scalebar(img, cfg, um_px)
    L = panel_layout(img.width, img.height, cfg)
    ox, oy = L["ox"], L["oy"]
    canvas = Image.new("RGB", L["canvas"], (255, 255, 255))
    canvas.paste(img, (ox, oy))
    if L["title_box"]:
        _draw_title(canvas, L)
    if L["label_box"]:
        _draw_vertical_label(canvas, L)
    info = {"scalebar": sb, "image_box": (ox, oy, ox + img.width, oy + img.height)}
    if sb:
        sb.update(x0=sb["x0"] + ox, x1=sb["x1"] + ox, y0=sb["y0"] + oy, y1=sb["y1"] + oy)
    return canvas, info


# =====================================================================
# 6. 公開 API
# =====================================================================
def _upscaled(img: Image.Image, cfg: dict) -> Image.Image:
    up = int(cfg.get("upscale", 1))
    return img.resize((img.width * up, img.height * up), Image.NEAREST) if up > 1 else img


def composite_image(cfg: dict, data: CziData) -> Image.Image:
    """注釈なしの合成画像（拡大済み）。"""
    return _upscaled(Image.fromarray(composite_rgb(data, cfg), "RGB"), cfg)


def single_images(cfg: dict, data: CziData) -> list[tuple[dict, dict, Image.Image]]:
    """注釈なしの単色画像 [(元のチャンネル dict, その単色パネル用の設定, 画像)]。"""
    out = []
    for ch in cfg["channels"]:
        if not ch.get("enabled"):
            continue
        c = data.index_of(ch)
        if c is None:
            continue
        g = _upscaled(Image.fromarray(gray_u8(data, c, ch), "L").convert("RGB"), cfg)
        sub = copy.deepcopy(cfg)
        sub["channels"] = [{**ch, "color": "gray"}]
        out.append((ch, sub, g))
    return out


def render_panel(cfg: dict, data: CziData | None = None, with_info: bool = False):
    """
    設定 dict から図セル（PIL.Image, RGB）を作る純関数。
    data を渡せば読み込みを省く（GUI のライブプレビュー用）。
    """
    data = data or load_czi(cfg["czi_path"], cfg.get("scene", 0), cfg.get("z_reduce", "max"))
    canvas, info = annotate(composite_image(cfg, data), cfg, data.um_px)
    return (canvas, info) if with_info else canvas


def render_single_channels(cfg: dict, data: CziData | None = None) -> list[tuple[dict, Image.Image]]:
    """有効な各チャンネルのグレースケール単色パネル（タイトルはその抗体名を黒で）。"""
    data = data or load_czi(cfg["czi_path"], cfg.get("scene", 0), cfg.get("z_reduce", "max"))
    return [(ch, annotate(g, sub, data.um_px)[0]) for ch, sub, g in single_images(cfg, data)]


def safe_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]+', "_", s).strip()
    return re.sub(r"\s+", "_", s)


def _n_scenes_quiet(path: str) -> int:
    try:
        return count_scenes(path)
    except Exception:
        return 1


def default_out_path(cfg: dict, suffix: str = "") -> str:
    stem = os.path.splitext(os.path.basename(cfg["czi_path"]))[0]
    parts = [stem]
    if cfg.get("scene", 0) or _n_scenes_quiet(cfg["czi_path"]) > 1:
        parts.append(f"S{cfg.get('scene', 0)}")
    if cfg.get("label"):
        parts.append(cfg["label"])
    if suffix:
        parts.append(suffix)
    return os.path.join(cfg.get("out_dir") or DEFAULT_OUT_DIR,
                        safe_filename("_".join(parts)) + ".png")


def save_png(img: Image.Image, path: str, cfg: dict) -> str:
    """PNG で保存。dpi と、再利用できるよう設定 JSON を PNG のテキスト欄に埋め込む。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    meta = PngInfo()
    meta.add_text("czi_figure_config", json.dumps(cfg, ensure_ascii=False))
    dpi = int(cfg.get("dpi", 300))
    img.save(path, dpi=(dpi, dpi), pnginfo=meta)
    return path


def save_config(cfg: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_config(path: str) -> dict:
    """設定 JSON、またはこのツールで保存した PNG（設定が埋め込まれている）から設定を読む。"""
    if path.lower().endswith(".png"):
        with Image.open(path) as im:
            txt = im.info.get("czi_figure_config")
        if not txt:
            raise ValueError("この PNG には設定が埋め込まれていません（このツールで保存した PNG ではない）。")
        return json.loads(txt)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# =====================================================================
# 6b. 書き出し（1 枚・全シーン・複数ファイル共通）
# =====================================================================
def plan_outputs(cfg: dict, composite: bool = True, single: bool = False,
                 out_path: str | None = None) -> list[tuple[str, dict | None]]:
    """
    書き出すファイルの一覧 [(パス, None=合成 / チャンネル dict=単色)] を作る（まだ書かない）。
    out_path を与えると合成パネルはそのパスに、単色は「<その名前>_<抗体名>.png」にする。
    """
    base = out_path or default_out_path(cfg)
    stem = os.path.splitext(base)[0]
    out: list[tuple[str, dict | None]] = []
    if composite:
        out.append((base, None))
    if single:
        for ch in cfg["channels"]:
            if ch.get("enabled"):
                out.append((stem + "_" + safe_filename(ch.get("name") or ch.get("slot") or "ch")
                            + ".png", ch))
    return out


def write_outputs(cfg: dict, plan: list[tuple[str, dict | None]], data: CziData | None = None,
                  skip: set[str] | None = None) -> list[str]:
    """plan_outputs の一覧どおりに描いて保存する。skip に入ったパスは飛ばす。"""
    data = data or load_czi(cfg["czi_path"], cfg.get("scene", 0), cfg.get("z_reduce", "max"))
    skip = skip or set()
    saved: list[str] = []
    singles = None
    for path, ch in plan:
        if path in skip:
            continue
        if ch is None:
            img = render_panel(cfg, data)
        else:
            if singles is None:
                singles = {id(c): g for c, g in render_single_channels(cfg, data)}
            img = singles.get(id(ch))
            if img is None:
                continue
        save_png(img, path, cfg)
        saved.append(path)
    return saved


def configs_for_scenes(cfg: dict, scenes: list[int] | None = None) -> list[dict]:
    """同じ .czi の各シーンに、今の体裁（ラベル含む）をそのまま当てた設定のリスト。"""
    n = count_scenes(cfg["czi_path"])
    scenes = list(range(n)) if scenes is None else scenes
    out = []
    for s in scenes:
        c = copy.deepcopy(cfg)
        c["scene"] = s
        out.append(c)
    return out


def config_for_file(path: str, style: dict, scene: int = 0) -> dict:
    """別の .czi に、保存した体裁を当てた設定（抗体名・ラベルはファイル名の推測を優先）。"""
    return merge_config(default_config(path, scene), style)


def count_scenes(path: str) -> int:
    return load_engine().count_czi_scenes(path)


# =====================================================================
# 6c. PowerPoint（.pptx）書き出し
# =====================================================================
# 1 パネル＝1 スライド。PNG と同じ配置（panel_layout / scalebar_geometry）を、独立した 7 つのオブジェクトで再現する：
#   画像（スケールバーは焼き込まない）／タイトル枠（四角形）／ラベル枠（四角形）／
#   タイトル文字（テキストボックス・抗体名ごとに色付き）／ラベル文字（縦書きテキストボックス）／
#   スケールバー（白い四角形・長さは µm ÷ µm/px そのもの）／スケールバー文字（「50 µm」テキストボックス）
# 文字はテキストボックスなので、PowerPoint 上でそのまま打ち直せる。
PPTX_SLIDE_W, PPTX_SLIDE_H = 12192000, 6858000      # 16:9 ワイド（13.33 × 7.5 inch）を EMU で
PPTX_MARGIN = 365760                                 # 0.4 inch
PPTX_FONT_LATIN, PPTX_FONT_EA = "Arial", "Yu Gothic"


def _pptx_run_font(run, size_pt: float, rgb: tuple[int, int, int]) -> None:
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    from pptx.util import Pt
    f = run.font
    f.size = Pt(round(size_pt * 2) / 2)
    f.bold = True
    f.color.rgb = RGBColor(*rgb)
    f.name = PPTX_FONT_LATIN
    rPr = run._r.get_or_add_rPr()                # 日本語部分は游ゴシック（latin の直後に ea を置く）
    latin = rPr.find(qn("a:latin"))
    ea = rPr.makeelement(qn("a:ea"), {"typeface": PPTX_FONT_EA})
    latin.addnext(ea)


def _pptx_textbox(slide, name: str, box_emu: tuple[int, int, int, int], vertical: bool = False):
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    x, y, w, h = box_emu
    tb = slide.shapes.add_textbox(x, y, w, h)
    tb.name = name
    tf = tb.text_frame
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    if vertical:                                 # 下から上へ読む縦書き（PNG・見本と同じ向き）
        tf._txBody.bodyPr.set("vert", "vert270")
    return tb


def _pptx_frame(slide, name: str, box_emu: tuple[int, int, int, int], lw_emu: int):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    x, y, w, h = box_emu
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    sh.name = name
    sh.fill.background()                         # 塗りなし（枠線だけ）
    sh.line.color.rgb = RGBColor(0, 0, 0)
    sh.line.width = lw_emu
    sh.shadow.inherit = False
    return sh


def add_pptx_panel(prs, cfg: dict, img: Image.Image, um_px: float | None, note: str = ""):
    """
    スライドを 1 枚足し、図セルを独立したオブジェクトで置く。置いた図形の dict を返す。
      画像 / タイトル枠 / ラベル枠 / タイトル文字 / ラベル文字 / スケールバー / スケールバー文字
    PPTX の画像にはスケールバーを焼き込まない（バーと「50 µm」は別の図形・テキストボックス）。
    """
    import io
    pic_img = img
    L = panel_layout(pic_img.width, pic_img.height, cfg)
    sb = scalebar_geometry(pic_img.width, pic_img.height, cfg, um_px)
    cw, ch_ = L["canvas"]
    # px → EMU：スライドに余白を残して収まる倍率で、中央に置く
    s = min((PPTX_SLIDE_W - 2 * PPTX_MARGIN) / cw, (PPTX_SLIDE_H - 2 * PPTX_MARGIN) / ch_)
    x_off = (PPTX_SLIDE_W - cw * s) / 2
    y_off = (PPTX_SLIDE_H - ch_ * s) / 2

    def E(v: float, off: float = 0.0) -> int:
        return int(round(off + v * s))

    def box(b, inset: float = 0.0):           # PIL の (x0,y0,x1,y1)（x1,y1 含む）→ (x, y, w, h)
        x0, y0, x1, y1 = b
        return (E(x0 + inset, x_off), E(y0 + inset, y_off),
                E(x1 + 1 - x0 - 2 * inset), E(y1 + 1 - y0 - 2 * inset))

    slide = prs.slides.add_slide(prs.slide_layouts[6])      # 白紙
    shapes = {}

    buf = io.BytesIO()
    pic_img.save(buf, format="PNG")
    buf.seek(0)
    pic = slide.shapes.add_picture(buf, E(L["ox"], x_off), E(L["oy"], y_off),
                                   E(pic_img.width), E(pic_img.height))
    pic.name = "画像"
    shapes["画像"] = pic

    lw = L["lw"]
    # PIL の枠線は内側に描かれ、PowerPoint の線は辺の中央に乗るので、線幅の半分だけ内側へ
    if L["title_box"]:
        shapes["タイトル枠"] = _pptx_frame(slide, "タイトル枠", box(L["title_box"], lw / 2), E(lw))
    if L["label_box"]:
        shapes["ラベル枠"] = _pptx_frame(slide, "ラベル枠", box(L["label_box"], lw / 2), E(lw))

    pt = lambda px: px * s / 12700.0            # noqa: E731  文字サイズ px → pt
    if L["title_box"]:
        tb = _pptx_textbox(slide, "タイトル文字", box(L["title_box"]))
        p = tb.text_frame.paragraphs[0]
        for text, rgb in L["title_segments"]:
            r = p.add_run()
            r.text = text
            _pptx_run_font(r, pt(L["title_px"]), rgb)
        shapes["タイトル文字"] = tb
    if L["label_box"]:
        tb = _pptx_textbox(slide, "ラベル文字", box(L["label_box"]), vertical=True)
        r = tb.text_frame.paragraphs[0].add_run()
        r.text = L["label"]
        _pptx_run_font(r, pt(L["label_px"]), (0, 0, 0))
        shapes["ラベル文字"] = tb

    if sb:
        ox, oy = L["ox"], L["oy"]               # スケールバーの座標は画像本体が原点
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import MSO_ANCHOR
        # PNG は画素単位なので 160 px（=49.91 µm）に丸めるが、PowerPoint は画素に縛られないので
        # µm ÷ µm/px の割り切れない長さ（160.28 px = 50.00 µm）をそのまま使う。右端は PNG と同じ位置。
        exact = sb["um"] / sb["um_px"]
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(ox + sb["x1"] - exact, x_off),
                                     E(oy + sb["y0"], y_off), E(exact), E(sb["y1"] - sb["y0"]))
        bar.name = "スケールバー"
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(255, 255, 255)
        bar.line.fill.background()               # 枠線なし（線を付けると長さが線幅ぶん伸びる）
        bar.shadow.inherit = False
        shapes["スケールバー"] = bar

        # 文字：PNG と同じく「バーの中央・ベースラインがバーの少し上」。下揃えの箱の底＝ベースライン＋ディセント
        f = get_font(sb["font_px"], sb["text"])
        ascent, descent = f.getmetrics()
        tw = f.getlength(sb["text"])
        w = max(tw * 1.3, sb["length_px"])
        h = (ascent + descent) * 1.25
        bottom = sb["text_y"] + descent
        tb = _pptx_textbox(slide, "スケールバー文字",
                           (E(ox + sb["text_x"] - w / 2, x_off), E(oy + bottom - h, y_off), E(w), E(h)))
        tb.text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
        r = tb.text_frame.paragraphs[0].add_run()
        r.text = sb["text"]
        _pptx_run_font(r, pt(sb["font_px"]), (255, 255, 255))
        shapes["スケールバー文字"] = tb

    if note:
        slide.notes_slide.notes_text_frame.text = note
    return shapes


def _pptx_note(cfg: dict, data: CziData, what: str, sb: dict | None) -> str:
    lines = [f"{what}", f"元ファイル: {os.path.basename(cfg['czi_path'])}"
             + (f"  シーン {cfg.get('scene', 0)}" if data.n_scenes > 1 else "")]
    if data.um_px:
        lines.append(f"画素: {data.um_px:.5f} µm/px（拡大 {int(cfg.get('upscale', 1))} 倍）")
    if sb:
        lines.append(f"スケールバー: {sb['um']:g} µm = {sb['length_px']} px")
    for ch in cfg["channels"]:
        if ch.get("enabled"):
            unit = "%" if ch.get("range_mode", "percentile") == "percentile" else ""
            lines.append(f"{ch['name']} ({ch.get('slot')}): {ch['color']}, "
                         f"表示レンジ {ch['low']:g}{unit}–{ch['high']:g}{unit}, "
                         f"ガンマ {float(ch.get('gamma', 1.0)):g}")
    return "\n".join(lines)


def write_pptx(path: str, jobs: list[dict], composite: bool = True, single: bool = False,
               data: CziData | None = None, progress=None) -> int:
    """
    jobs（設定のリスト）を 1 つの .pptx にまとめる。1 パネル＝1 スライド。
    data は jobs[0] 用に読み込み済みのものがあれば渡す（GUI のプレビュー中のデータ）。
    progress(i, n, cfg) を渡すと各ジョブの前に呼ぶ（False を返すと中止）。書いたスライド数を返す。
    """
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ImportError("PowerPoint 書き出しには python-pptx が必要です:\n"
                          "    pip install python-pptx") from exc
    prs = Presentation()
    prs.slide_width, prs.slide_height = PPTX_SLIDE_W, PPTX_SLIDE_H
    n = 0
    for i, cfg in enumerate(jobs):
        if progress is not None and progress(i, len(jobs), cfg) is False:
            break
        d = data if (i == 0 and data is not None) else load_czi(
            cfg["czi_path"], cfg.get("scene", 0), cfg.get("z_reduce", "max"))
        if composite:
            img = composite_image(cfg, d)
            sb = image_with_scalebar(img, cfg, d.um_px)[1]
            add_pptx_panel(prs, cfg, img, d.um_px, _pptx_note(cfg, d, "合成パネル", sb))
            n += 1
        if single:
            for ch, sub, g in single_images(cfg, d):
                sb = image_with_scalebar(g, sub, d.um_px)[1]
                add_pptx_panel(prs, sub, g, d.um_px, _pptx_note(sub, d, f"単色パネル: {ch['name']}", sb))
                n += 1
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    prs.save(path)
    return n


def default_pptx_path(jobs: list[dict]) -> str:
    """1 件なら PNG と同じ名前で .pptx、複数なら日時入りのまとめファイル名。"""
    if len(jobs) == 1:
        return os.path.splitext(default_out_path(jobs[0]))[0] + ".pptx"
    import datetime as _dt
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    return os.path.join(jobs[0].get("out_dir") or DEFAULT_OUT_DIR, f"czi_figures_{stamp}.pptx")


# =====================================================================
# 7. CLI
# =====================================================================
def _parse_channels_arg(spec: str, cfg: dict) -> None:
    """--channels "DAPI:Hoechst:blue,AF488:MAP2:green" ：並び順・名前・色を指定、列挙外は OFF。"""
    by_slot = {c.get("slot"): c for c in cfg["channels"]}
    chosen = []
    for item in spec.split(","):
        parts = [p.strip() for p in item.split(":")]
        slot = parts[0]
        if slot not in by_slot:
            raise SystemExit(f"--channels: スロット {slot} はこのファイルにありません "
                             f"（あるもの: {[s for s in by_slot if s]}）")
        ch = by_slot[slot]
        if len(parts) > 1 and parts[1]:
            ch["name"] = parts[1]
        if len(parts) > 2 and parts[2]:
            if not is_color(parts[2]):
                raise SystemExit(f"--channels: 色 {parts[2]} は使えません（{list(PALETTE)} か #RRGGBB）")
            ch["color"] = parts[2]
        ch["enabled"] = True
        chosen.append(ch)
    for ch in cfg["channels"]:
        if ch not in chosen:
            ch["enabled"] = False
    cfg["channels"] = chosen + [c for c in cfg["channels"] if c not in chosen]


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=".czi からラベル付き合成 PNG を作る")
    ap.add_argument("czi", nargs="+", help=".czi ファイル（複数可。2 つ目以降には 1 つ目の体裁を当てる）")
    ap.add_argument("--engine", help="run_analysis_9th.py のパス（既定は同じフォルダ）")
    ap.add_argument("--scene", type=int, default=0)
    ap.add_argument("--all-scenes", action="store_true", help="全シーン（Position）を書き出す")
    ap.add_argument("--list", action="store_true", help="チャンネル一覧と既定設定を表示するだけ")
    ap.add_argument("--config", help="体裁の設定 JSON、またはこのツールで保存した PNG")
    ap.add_argument("--channels", help='例 "DAPI:Hoechst:blue,AF488:MAP2:green,AF647:TBR1:red"')
    ap.add_argument("--label", help="左の縦書きラベル")
    ap.add_argument("--scalebar-um", type=float)
    ap.add_argument("--magenta", action="store_true", help="赤をマゼンタにする（色覚対応）")
    ap.add_argument("--zen", action="store_true",
                    help=".czi に保存された ZEN の表示設定（色・黒・白・ガンマ）で描く（ファイルごと）")
    ap.add_argument("--upscale", type=int)
    ap.add_argument("--single", action="store_true", help="各チャンネルの単色パネルも書き出す")
    ap.add_argument("--no-composite", action="store_true", help="合成パネルを書き出さない（単色だけ）")
    ap.add_argument("--format", choices=("png", "pptx", "both"), default="png",
                    help="png / pptx（1 パネル＝1 スライド、全部を 1 ファイルに）/ both")
    ap.add_argument("--pptx", help="PowerPoint の保存先（既定は自動命名）")
    ap.add_argument("--out-dir", help="出力フォルダ（既定はドキュメント）")
    ap.add_argument("--out", help="出力 PNG のパス（ファイル 1 つ・シーン 1 つのときだけ）")
    ap.add_argument("--save-config", help="使った設定を JSON に保存")
    ap.add_argument("--force", action="store_true", help="既存ファイルを上書きする")
    a = ap.parse_args(argv)

    if a.engine:
        load_engine(a.engine)
    first = a.czi[0]
    cfg = default_config(first, a.scene)
    if a.config:
        cfg = merge_config(cfg, load_config(a.config))
    if a.channels:
        _parse_channels_arg(a.channels, cfg)
    if a.label is not None:
        cfg["label"] = a.label
    if a.scalebar_um:
        cfg["scalebar"]["um"] = a.scalebar_um
    if a.magenta:
        cfg["colorblind_magenta"] = True
    if a.upscale:
        cfg["upscale"] = a.upscale
    if a.out_dir:
        cfg["out_dir"] = a.out_dir

    if a.list:
        for path in a.czi:
            c = cfg if path == first else config_for_file(path, cfg, a.scene)
            data = load_czi(path, c["scene"], c["z_reduce"])
            print(f"ファイル: {data.stem}  シーン {c['scene']}/{data.n_scenes - 1}  "
                  f"{data.planes.shape[2]}x{data.planes.shape[1]} px  µm/px={data.um_px}  "
                  f"ラベル={c['label']!r}")
            for ch in c["channels"]:
                i = data.index_of(ch)
                raw = data.chans[i].get("name", "") if i is not None else "(無し)"
                print(f"  ch{i}: {raw:18s} slot={ch['slot']!s:6s} "
                      f"→ 表示名 {ch['name']!r} 色 {ch['color']} {'ON' if ch['enabled'] else 'OFF'}")
        return 0

    jobs: list[dict] = []
    for path in a.czi:
        c = cfg if path == first else config_for_file(path, cfg, a.scene)
        jobs += configs_for_scenes(c) if a.all_scenes else [c]
    if a.zen:
        zjobs = []
        for c in jobs:
            z, notes = apply_zen_display(c, load_czi(c["czi_path"], c["scene"], c["z_reduce"]))
            print(f"[ZEN] {os.path.basename(c['czi_path'])}: " + " / ".join(notes))
            zjobs.append(z)
        jobs = zjobs
    if a.out and len(jobs) > 1:
        raise SystemExit("--out は 1 ファイル・1 シーンのときだけ使えます（複数なら --out-dir）。")

    png, pptx = a.format in ("png", "both"), a.format in ("pptx", "both")
    plans = [(c, plan_outputs(c, not a.no_composite, a.single, a.out)) for c in jobs] if png else []
    pptx_path = (a.pptx or default_pptx_path(jobs)) if pptx else None
    exists = [p for _, pl in plans for p, _ in pl if os.path.exists(p)]
    if pptx_path and os.path.exists(pptx_path):
        exists.append(pptx_path)
    if exists and not a.force:
        print("次のファイルが既にあります（上書きするなら --force）:")
        for p in exists:
            print("   " + p)
        return 1

    for c, pl in plans:
        data = load_czi(c["czi_path"], c["scene"], c["z_reduce"])
        for p in write_outputs(c, pl, data):
            print(f"保存: {p}")
        if data.um_px and c["scalebar"].get("show", True):
            up = int(c.get("upscale", 1))
            n = scalebar_px(c["scalebar"]["um"], data.um_px, up)
            print(f"   スケールバー: {c['scalebar']['um']:g} µm = {n} px "
                  f"(µm/px={data.um_px / up:.5f} → 真値 {c['scalebar']['um'] * up / data.um_px:.2f} px)")
    if pptx_path:
        n = write_pptx(pptx_path, jobs, not a.no_composite, a.single)
        print(f"保存: {pptx_path}（{n} スライド）")
    if a.save_config:
        save_config(cfg, a.save_config)
        print(f"設定を保存: {a.save_config}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
