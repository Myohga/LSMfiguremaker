# -*- coding: utf-8 -*-
r"""
run_analysis_9th.py
===================
蛍光免疫染色の細胞数・陽性率解析（第9版）— 手元で確実に走らせるための版

run_analysis_8th.py からの変更点（解析アルゴリズムは一切変更なし）
------------------------------------------------------------------
第8版は解析の中身としては完成しているが、実際に別の PC で走らせようとすると
「動かない」「動いても場所を探し回る」という素朴な壁に当たった。
本版はその壁だけを取り除く。数値結果は第8版と完全に一致する（検証済み）。

[A] .czi リーダの依存を起動時に確認する
    第8版のリーダ層（czifile を第一候補、無ければ bioio-czi）は設計としては
    正しかったが、依存が無いことに気づくのが解析の途中だった。
    本版は起動直後に確認し、入れ方をその場で表示する。
      pip install czifile

[B] .czi のパスを探しに行く
    第8版は既定パスを直書きしていたため、ファイルを別のフォルダへ移しただけで
    FileNotFoundError で止まった（実際に起きた）。
    本版は既定パスが無ければ、よくある置き場所を順に探し、
    見つかった .czi を一覧で示す。1 つだけ見つかればそれを使う。
    探す場所: CONFIG のパス → スクリプトと同じフォルダ → カレント →
              ~/Downloads → ~/Desktop → C:\

[C] --nucleus-diameter-um を追加した
    「検出核の等価直径が 4.27 µm で想定の 7 µm より小さい」という積み残しの
    検証が、CONFIG を直接書き換えないと試せなかった。
    第6版から3版にわたって未実施のまま持ち越されていたので、
    コマンドラインから 1 回で試せるようにする。
        python run_analysis_9th.py --nucleus-diameter-um 7.0

[D] 出力先の版番号を _results_9th に更新

--------------------------------------------------------------------
以下は第8版（run_analysis_7th.py からの変更点）の記録。内容は現行のまま。
--------------------------------------------------------------------
第7版は「2D / 3D 両対応」と称していたが、実際に 3D データを通すと壊れる欠陥が
3 つ残っていた。手元の試料が約16µm のクライオ切片で 2D 経路しか通らなかったため
表面化していなかったもので、本版はその 3 つを潰すのが主題である。

[1] ★ROI 拡張がボクセル等方だった（影響が最も大きく、最も気づきにくい）
    第7版は expand_labels(labels, distance=10) と呼んでいた。
    この distance は【ボクセル数】であって実寸ではない。
    本データは xy 0.312 µm / z 2.0 µm、つまり 6.4 倍の異方性があるので、
    「10」は実寸で xy 3.1 µm・z 20 µm を意味していた。
    核の上下に 10 µm ずつ、隣の細胞どころか別の層まで飲み込むリングになる。

    喩えるなら、地図上で「半径 1cm 以内」と言ったつもりが、
    縮尺の違う 2 枚の地図に同じ 1cm を当てているようなもの。
    紙の上では同じ長さでも、実際の距離は 6 倍違う。

    本版は skimage 0.26 の expand_labels(..., spacing=(z,y,x)) を使い、
    距離を常に【µm】で指定する。
    2D では従来と数値的に完全一致することを確認済み（10 px × 0.312 = 3.12 µm）。

[2] ★puncta の密度が 2D 決め打ちだった
    第7版の measure_puncta は px_area = um_per_px ** 2 を固定で使っていた。
    3D で走らせると「ボクセル数 × µm²」という意味のない量になり、
    密度の桁が狂う（しかもエラーにならないので黙って間違った数字が出る）。
    本版はボクセル体積（µm³）で数え、単位も出力に明記する。
      2D: 個数 / 1000 µm²    3D: 個数 / 1000 µm³
    サイズ閾値も 2D 用（µm²）と 3D 用（µm³）を別々に持つ。

[3] ★マルチシーン／タイルの .czi が黙って 1 つ目だけ読まれていた
    第7版は scenes[0] を使い、CZYX 以外の軸は先頭インデックスを取っていた。
    複数 Position を撮ったファイルは警告なく 1 視野だけ解析される。
    「黙って落ちる」のが一番たちの悪い挙動なので、本版は
      - シーン数・余分な軸を必ず表示して警告する
      - czi_scene / --scene で明示的に選べる
      - --all-scenes で全シーンを順に処理し、最後にプールして集計する
        （巨大な結合画像を作るより、1 視野ずつ回す方が実装も座標管理も素直）
    さらに、新しい czifile では czi.asarray() ではなく scene.asarray() を使う。
    こちらはシーンの axes と必ず一致するので、軸の取り違えが原理的に起きない。

[4] 3D 固有の副次的な修正・追加
    - touches_border を xy 面と z 面に分離した。
      z スタックでは上端・下端の面に掛かる核は「切れている」が、
      xy の画像端に掛かるのとは意味が違う。
      qc_exclude_border（xy）と qc_exclude_z_border を別々に設定できる。
    - 3D 入力のとき z_profile.csv を出力する。
      厚い標本では深いほど暗くなる（散乱・吸収）ため、陽性判定が z にバイアスする。
      ただし補正は本物の生物学的な勾配まで消しうるので、
      本版は【補正はせず、見えるようにするだけ】にとどめる。
      減衰が明らかなら、まず撮像側（z 補正・ゲイン傾斜）で対処すること。

第7版から温存した部分
---------------------
[A] 特定の抗体に依存しないパネル構造
    二次抗体は常に AF488 / AF555 / AF647 の 3 本＋核染色である。
    つまり .czi の中身（＝チャンネルの正体）は毎回同じで、
    実験ごとに変わるのは「どの色素にどの一次抗体が乗っているか」だけ。
    この 1 対応だけを PANELS に切り出してある。

        PANELS["motor-neuron"] = [
            MarkerSpec("MAP2",     "AF488"),
            MarkerSpec("Islet-1",  "AF555"),
            MarkerSpec("ChAT",     "AF647"),
        ]

    新しい染色をするときは、この 3 行を書いて ACTIVE_PANEL を切り替えるだけでよい。
    ROI も閾値の決め方も、後述のマーカーライブラリから自動で決まる。

[B] 染色パターンという概念（これが無いと点状マーカーで必ず破綻する）
    第6版の陽性判定は「ROI 内の 75 パーセンタイル」かつ
    「ROI 内の 30% 以上の画素が閾値を超える」という条件だった。
    これは MAP2 や ChAT のように【面で広がる】シグナルには正しいが、
    Synapsin 1 や VGLUT1 のような【点状（puncta）】シグナルには壊滅的である。
    シナプスは突起上に散らばる小さな輝点なので、ROI 内で明るい画素は数 % しかない。
    30% を要求すれば、本当は陽性の細胞まで全部陰性と判定される。

    喩えるなら、「夜景の明るさ」を測るのに
    「画面の 3 割以上が明るいこと」を条件にするようなもの。
    街の灯りは点で散らばっているので、その基準ではどんな夜景も「暗い」になる。

    そこで各マーカーに染色パターンを持たせ、測り方を変える：

        nuclear     核内に一様       ROI=nucleus  p75   面積条件 30%
        cytoplasmic 細胞質に一様     ROI=cell     p75   面積条件 30%
        membrane    細胞膜           ROI=ring     p75   面積条件 25%
        fibrillar   突起・線維       ROI=ring     p90   面積条件 10%
        punctate    点状（シナプス） ROI=ring     p97   面積条件  2%  ＋トップハット強調

    パターンは MARKER_LIBRARY から名前で自動判定される（PAX6→nuclear,
    Synapsin 1→punctate など）。未知のマーカーは cytoplasmic を仮定した上で
    「明示指定してください」と警告を出す（黙って誤った既定値を使わない）。

[3] 点状マーカーには視野レベルの puncta 定量を追加した
    そもそも Synapsin 1 や VGLUT1 で「陽性細胞率」を出すこと自体に無理がある。
    シナプスは細胞ではなく突起の上にあり、どの細胞のものか帰属できないため。
    標準的な readout は【puncta の密度】（面積あたりの輝点数）である。
    本版は点状マーカーについて puncta を検出し、
    個数・密度・平均サイズを puncta_summary.csv に出力する。
    陽性細胞率も従来どおり出すが、参考値として扱うこと。

[C] チャンネルの同定は「色素名＋発光波長」の二段構え
    ZEN の表記は AF647 / Alexa Fluor 647 / AF647-T1 などと揺れる。
    名前で照合し、外れたら発光波長（AF488≈519, AF555≈565, AF647≈668, Hoechst≈461）
    で最も近いスロットに割り当てる。
    透過光（ContrastMethod が Fluorescence でない、DyeName が "Dye5" など）は自動除外。

[D] その他
    - 生 .czi を直接読む（拡大済み擬似カラー PNG を経由しない）
    - ダイナミックレンジ診断（8bit・低ゲインだと陽性率が暫定値になる件）
    - Cellpose-SAM に前処理をかけずに生輝度を渡す
    - 多基準デブリ除外フィルタと除外理由の全記録
    - 局所背景（オープニング）の減算
    - 「細胞の集合」の分布に対して閾値を決める陽性判定
    - 疎な 2D 単層培養プリセット

3D を撮るときの注意（コードでは直せない、撮像側の話）
----------------------------------------------------
    - z ステップ 2 µm は真の 3D には粗い。核 7 µm が z 方向に 3〜4 枚しか乗らず、
      do_3D は形が破綻しやすい。20x/0.8 なら z ステップ ≤1 µm（Nyquist なら 0.5 µm 前後）
      を推奨。粗いままなら do_3D より stitch_threshold の方が現実的。
    - 8bit・低ゲインのままだと 3D にしても陽性率の信頼性は上がらない。16bit で撮ること。
    - GPU 無しの環境では 3D セグメンテーションは現実的でない可能性が高い
      （8 枚の 2D 投影で CPU 数分だったので、50〜100 枚なら桁が変わる）。

使い方
------
    python run_analysis_9th.py
    python run_analysis_9th.py --list-channels "path\to\file.czi"
    python run_analysis_9th.py --czi "path\to\file.czi" --panel synapse
    python run_analysis_9th.py --nucleus-diameter-um 7.0              # 核径の検証
    python run_analysis_9th.py --czi "path\to\stack.czi" --3d        # 真の 3D 解析
    python run_analysis_9th.py --czi "path\to\multi.czi" --all-scenes  # 全 Position

必要なパッケージ
----------------
    pip install czifile          # .czi リーダ（これが無いと .czi を読めない）
      もしくは
    pip install bioio bioio-czi  # 後継の本格リーダ（AICSImageIO はメンテ終了）

    起動時に自動で確認し、足りなければ入れ方を表示する。
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import warnings
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage import filters, measure, segmentation

warnings.filterwarnings("ignore")
try:  # 日本語出力が化ける環境への保険
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# =====================================================================
# 0. 蛍光色素スロット
# =====================================================================
# 二次抗体は常に AF488 / AF555 / AF647 の 3 本＋核染色（Hoechst/DAPI）。
# つまり .czi の中身は毎回同じで、変わるのは一次抗体の割り当てだけ。
# ここではスロットの「呼び名の揺れ」と「発光波長」を定義する。

def _norm(s: str) -> str:
    """表記揺れを吸収するための正規化（英数字だけを残して小文字化）。"""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


FLUOROPHORE_SLOTS: dict[str, dict] = {
    # スロット名 : {aliases: 名前照合用, emission_nm: 波長照合用}
    "DAPI":  {"aliases": ["hoechst33342", "hoechst", "h3342", "h33342", "dapi",
                          "bisbenzimide", "nucblue"], "emission_nm": 461.0},
    "AF488": {"aliases": ["alexafluor488", "alexa488", "af488", "fitc",
                          "gfp", "488"], "emission_nm": 519.0},
    "AF555": {"aliases": ["alexafluor555", "alexa555", "af555", "cy3",
                          "tritc", "rhodamine", "555"], "emission_nm": 565.0},
    "AF647": {"aliases": ["alexafluor647", "alexa647", "af647", "cy5",
                          "apc", "647"], "emission_nm": 668.0},
}

# 発光波長で照合するときの許容幅[nm]。これを超えて離れていたら割り当てない。
EMISSION_TOLERANCE_NM = 45.0


def resolve_fluorophore(name: str, emission_nm: float | None = None) -> str | None:
    """
    チャンネル名（と発光波長）から蛍光色素スロットを決める。

    ZEN の表記は "AF647" / "Alexa Fluor 647" / "AF647-T1" と揺れるうえ、
    透過光チャンネルには "Dye5" のような意味のない名前が付く。
    まず名前で照合し、外れたら発光波長で最も近いスロットに落とす。
    どちらでも決まらなければ None を返す（＝そのチャンネルは使わない）。
    """
    n = _norm(name)

    # ZEN が未定義チャンネルに付ける "Dye1"〜"Dye9" は名前として無意味
    if not re.fullmatch(r"dye\d+", n):
        # 長い別名から順に見る（"488" が "alexafluor488" より先に当たらないように）
        for slot, spec in FLUOROPHORE_SLOTS.items():
            for alias in sorted(spec["aliases"], key=len, reverse=True):
                if alias in n:
                    return slot

    if emission_nm:
        best, best_d = None, 1e9
        for slot, spec in FLUOROPHORE_SLOTS.items():
            d = abs(float(emission_nm) - spec["emission_nm"])
            if d < best_d:
                best, best_d = slot, d
        if best_d <= EMISSION_TOLERANCE_NM:
            return best
    return None


# =====================================================================
# 0b. 染色パターンとマーカーライブラリ
# =====================================================================
# 「どう染まるか」で測り方を変える。これが本版の核心。
#
# signal_percentile      : ROI 内のどの分位をその細胞の代表値にするか
# min_positive_fraction  : ROI 内で閾値を超える画素の割合の下限
#                          （＝シグナルが点ではなく面で広がっていることの要求）
# enhance                : 'tophat' なら小さな輝点だけを残す前処理を掛ける
#
# 点状マーカーで min_positive_fraction を下げるのが決定的に重要。
# シナプス輝点は ROI の数 % しか占めないので、30% を要求すると全部陰性になる。

PATTERN_DEFAULTS: dict[str, dict] = {
    "nuclear":     dict(roi="nucleus", signal_percentile=75.0,
                        min_positive_fraction=0.30, enhance=None),
    "cytoplasmic": dict(roi="cell",    signal_percentile=75.0,
                        min_positive_fraction=0.30, enhance=None),
    "membrane":    dict(roi="ring",    signal_percentile=75.0,
                        min_positive_fraction=0.25, enhance=None),
    "fibrillar":   dict(roi="ring",    signal_percentile=90.0,
                        min_positive_fraction=0.10, enhance=None),
    "punctate":    dict(roi="ring",    signal_percentile=97.0,
                        min_positive_fraction=0.02, enhance="tophat"),
}

# マーカー名（正規化して部分一致）→ 染色パターン。
# ここに無いマーカーは cytoplasmic を仮定し、警告を出す。
# 新しい抗体を使うときはここに 1 行足すか、MarkerSpec で pattern を明示する。
MARKER_LIBRARY: dict[str, str] = {
    # ---- 核内（転写因子・核タンパク） ----
    "pax6": "nuclear", "pax7": "nuclear", "sox1": "nuclear", "sox2": "nuclear",
    "sox9": "nuclear", "sox10": "nuclear", "nkx61": "nuclear", "nkx22": "nuclear",
    "olig2": "nuclear", "olig1": "nuclear", "foxg1": "nuclear", "foxa2": "nuclear",
    "otx2": "nuclear", "lhx3": "nuclear", "isl1": "nuclear", "islet1": "nuclear",
    "islet": "nuclear", "mnx1": "nuclear", "hb9": "nuclear", "phox2b": "nuclear",
    "brn3a": "nuclear", "pou4f1": "nuclear", "tbr1": "nuclear", "tbr2": "nuclear",
    "eomes": "nuclear", "ctip2": "nuclear", "bcl11b": "nuclear", "satb2": "nuclear",
    "cux1": "nuclear", "neun": "nuclear", "rbfox3": "nuclear", "ki67": "nuclear",
    "mki67": "nuclear", "ph3": "nuclear", "phosphohistoneh3": "nuclear",
    "oct4": "nuclear", "pou5f1": "nuclear", "nanog": "nuclear", "gata3": "nuclear",
    "chx10": "nuclear", "vsx2": "nuclear", "tfap2a": "nuclear", "mef2c": "nuclear",
    "myt1l": "nuclear", "hoxb4": "nuclear", "hoxc9": "nuclear", "en1": "nuclear",
    "nurr1": "nuclear", "nr4a2": "nuclear", "pitx3": "nuclear", "ascl1": "nuclear",
    "neurod1": "nuclear", "ngn2": "nuclear", "neurog2": "nuclear",

    # ---- 細胞質に一様 ----
    "chat": "cytoplasmic", "th": "cytoplasmic", "tyrosinehydroxylase": "cytoplasmic",
    "gfap": "cytoplasmic", "s100b": "cytoplasmic", "s100": "cytoplasmic",
    "iba1": "cytoplasmic", "aif1": "cytoplasmic", "gad67": "cytoplasmic",
    "gad65": "cytoplasmic", "calbindin": "cytoplasmic", "calretinin": "cytoplasmic",
    "parvalbumin": "cytoplasmic", "somatostatin": "cytoplasmic", "sst": "cytoplasmic",
    "pgp95": "cytoplasmic", "uchl1": "cytoplasmic", "serotonin": "cytoplasmic",
    "5ht": "cytoplasmic", "dbh": "cytoplasmic", "vip": "cytoplasmic",
    "nestin": "cytoplasmic", "vimentin": "cytoplasmic", "cleavedcaspase3": "cytoplasmic",
    "caspase3": "cytoplasmic", "aqp4": "cytoplasmic", "cnpase": "cytoplasmic",

    # ---- 突起・線維（細胞骨格・軸索） ----
    "map2": "fibrillar", "tuj1": "fibrillar", "betaiiitubulin": "fibrillar",
    "biiitubulin": "fibrillar", "tubb3": "fibrillar", "tau": "fibrillar",
    "ptau": "fibrillar", "at8": "fibrillar", "nfh": "fibrillar", "nfm": "fibrillar",
    "nfl": "fibrillar", "neurofilament": "fibrillar", "smi32": "fibrillar",
    "smi31": "fibrillar", "dcx": "fibrillar", "doublecortin": "fibrillar",
    "gap43": "fibrillar", "mbp": "fibrillar", "peripherin": "fibrillar",
    "phalloidin": "fibrillar", "factin": "fibrillar",

    # ---- 点状（シナプス） ----
    "synapsin": "punctate", "syn1": "punctate", "synapsin1": "punctate",
    "synaptophysin": "punctate", "syp": "punctate", "vglut1": "punctate",
    "vglut2": "punctate", "slc17a7": "punctate", "slc17a6": "punctate",
    "vgat": "punctate", "vachat": "punctate", "vacht": "punctate",
    "psd95": "punctate", "dlg4": "punctate", "bassoon": "punctate",
    "piccolo": "punctate", "homer1": "punctate", "gephyrin": "punctate",
    "sv2": "punctate", "snap25": "punctate", "syntaxin": "punctate",
    "synaptotagmin": "punctate",

    # ---- 細胞膜 ----
    "ncam": "membrane", "l1cam": "membrane", "pdgfra": "membrane",
    "p75": "membrane", "ngfr": "membrane", "cd44": "membrane",
    "ecadherin": "membrane", "ncadherin": "membrane", "integrin": "membrane",
}

DEFAULT_PATTERN = "cytoplasmic"


def lookup_pattern(marker_name: str) -> tuple[str, bool]:
    """
    マーカー名から染色パターンを引く。(パターン, 自信があるか) を返す。

    完全一致を先に見て、次に長い登録名から順に部分一致を見る
    （"synapsin1" が "syn1" より先に当たるように）。
    """
    n = _norm(marker_name)
    if n in MARKER_LIBRARY:
        return MARKER_LIBRARY[n], True
    for key in sorted(MARKER_LIBRARY, key=len, reverse=True):
        if key in n or n in key:
            return MARKER_LIBRARY[key], True
    return DEFAULT_PATTERN, False


def safe_name(s: str) -> str:
    """CSV の列名やファイル名に使える形にする（'Synapsin 1' → 'Synapsin_1'）。"""
    return re.sub(r"_+", "_", re.sub(r"[^0-9A-Za-z]+", "_", str(s))).strip("_") or "marker"


# =====================================================================
# 1. パネル定義
# =====================================================================

@dataclass
class MarkerSpec:
    """
    一次抗体 1 本分の設定。

    最低限 name と fluorophore だけ書けばよい。
    残りは MARKER_LIBRARY と PATTERN_DEFAULTS から自動で埋まる。
    自動判定を上書きしたいときだけ、該当する項目を明示する。
    """
    name: str                              # "PAX6" / "Synapsin 1" など表示名
    fluorophore: str                       # "AF488" | "AF555" | "AF647"（表記揺れ可）
    pattern: str | None = None             # None → MARKER_LIBRARY から自動判定
    roi: str | None = None                 # None → pattern の既定（nucleus|ring|cell）
    signal_percentile: float | None = None # None → pattern の既定
    min_positive_fraction: float | None = None  # None → pattern の既定
    enhance: str | None = None             # None → pattern の既定（'tophat' など）
    threshold_method: str = "otsu"         # 'otsu' | 'mad' | 'fixed'
    fixed_threshold: float | None = None
    mad_k: float = 3.0
    path: str = ""                         # input_mode='images' のときの PNG パス

    # ---- 自動解決の結果（実行時に埋まる。手で書く必要はない） ----
    resolved_pattern: str = ""
    pattern_confident: bool = True

    @property
    def key(self) -> str:
        """CSV の列名・ファイル名に使う安全な識別子。"""
        return safe_name(self.name)

    def resolve(self) -> None:
        """未指定の項目を MARKER_LIBRARY / PATTERN_DEFAULTS から埋める。"""
        slot = resolve_fluorophore(self.fluorophore)
        if slot is None:
            raise ValueError(
                f"マーカー '{self.name}' の蛍光色素 '{self.fluorophore}' を解釈できません。"
                f" 使えるのは {list(FLUOROPHORE_SLOTS)} （表記揺れ可）です。")
        self.fluorophore = slot

        if self.pattern:
            self.resolved_pattern, self.pattern_confident = self.pattern, True
        else:
            self.resolved_pattern, self.pattern_confident = lookup_pattern(self.name)

        if self.resolved_pattern not in PATTERN_DEFAULTS:
            raise ValueError(f"'{self.name}' の pattern が不正です: {self.resolved_pattern}"
                             f" （{list(PATTERN_DEFAULTS)} のいずれか）")
        d = PATTERN_DEFAULTS[self.resolved_pattern]
        if self.roi is None:
            self.roi = d["roi"]
        if self.signal_percentile is None:
            self.signal_percentile = d["signal_percentile"]
        if self.min_positive_fraction is None:
            self.min_positive_fraction = d["min_positive_fraction"]
        if self.enhance is None:
            self.enhance = d["enhance"]


# 実験ごとのパネル。新しい染色をするときはここに 3 行足して ACTIVE_PANEL を変える。
# 二次抗体が AF488/555/647 に固定なので、書くのは「どの色にどの一次抗体か」だけでよい。
PANELS: dict[str, list[MarkerSpec]] = {
    "motor-neuron": [
        MarkerSpec("MAP2",      "AF488"),   # → fibrillar（突起）
        MarkerSpec("Islet-1",   "AF555"),   # → nuclear（転写因子）
        MarkerSpec("ChAT",      "AF647"),   # → cytoplasmic（細胞質）
    ],
    "progenitor": [
        MarkerSpec("PAX6",      "AF488"),   # → nuclear
        MarkerSpec("SOX2",      "AF555"),   # → nuclear
        MarkerSpec("Ki67",      "AF647"),   # → nuclear
    ],
    "synapse": [
        MarkerSpec("MAP2",       "AF488"),  # → fibrillar
        MarkerSpec("Synapsin 1", "AF555"),  # → punctate（点状。測り方が変わる）
        MarkerSpec("VGLUT1",     "AF647"),  # → punctate
    ],
}

ACTIVE_PANEL = "motor-neuron"


# =====================================================================
# 2. 設定
# =====================================================================

@dataclass
class Config:
    # ---- パネル ----
    active_panel: str = ACTIVE_PANEL
    # ここに MarkerSpec のリストを直接入れると active_panel より優先される
    panel: list[MarkerSpec] | None = None

    # ---- 入力 ----
    # 'czi'    : 生の .czi を直接読む（推奨。拡大・LUT・投影を経由しない）
    # 'images' : 書き出し済み PNG を読む（比較・退避用。MarkerSpec.path が必要）
    input_mode: str = "czi"
    # 既定パス。存在しなければ resolve_czi_path() がよくある置き場所を探す。
    czi_path: str = r"C:\ChAT rabbit647 MAP2 chicken488 Islet-1 mouse555 z2 1.czi"

    # 自動判定に失敗したときの手動割り当て（例 {"DAPI": 2, "AF488": 1}）。
    # --list-channels で実際のチャンネル一覧を見てから埋めること。
    czi_index_map: dict[str, int] = field(default_factory=dict)

    # 複数 Position / タイルを含む .czi のとき、どのシーンを解析するか。
    # 第7版は黙って 0 番だけを読んでいた。本版は必ず警告を出し、ここで選べる。
    # --all-scenes なら analyze_all_scenes() が全シーンを順に回してプールする。
    czi_scene: int = 0

    # Z スタックの潰し方 'max' | 'mean' | 'best' | 'none'(3D)
    z_reduce: str = "max"

    # ---- PNG 入力のとき ----
    dapi_path: str = ""
    intensity_mode: str = "auto"      # 'auto' | 'max' | 'luminance'

    output_dir: str | None = None     # None なら入力の隣に <名前>_results_9th/ を作る

    # ---- チャンネル間の位置合わせ ----
    # .czi は同一撮像なので不要（analyze 内で強制 False）。
    register_channels: bool = False
    max_shift_px: int = 30
    min_registration_response: float = 0.30

    # ---- Cellpose セグメンテーション ----
    use_gpu: bool = True
    diameter: float | None = None          # None = Cellpose-SAM の自動推定（推奨）
    nucleus_diameter_um: float | None = None  # 設定すると px に換算して diameter を上書き
    cellprob_threshold: float = 0.0
    flow_threshold: float = 0.4
    min_size: int = 15

    # ---- 3D ----
    use_3d: bool = False
    anisotropy: float | None = None
    stitch_threshold: float = 0.4
    # 3D 入力のとき z 方向の輝度プロファイルを z_profile.csv に出力する。
    # 深いほど暗くなる（散乱・吸収）と陽性判定が z にバイアスするため。
    # 【補正はしない】。本物の生物学的な勾配まで消しうるので、見えるようにするだけ。
    z_profile_diagnostics: bool = True

    # ---- ROI ----
    # 拡張距離は常に実寸[µm]で扱う。ボクセル数で指定すると異方性のある 3D で
    # z 方向だけ極端に広がる（第7版の欠陥）。
    # expansion_um が None のときは expansion_pixels × 画素サイズ を µm として使う
    # （既定の 10 px × 0.312 µm = 3.12 µm。第7版の 2D 結果と数値的に一致する）。
    expansion_pixels: int = 10
    expansion_um: float | None = None

    # ---- デブリ（ゴミ）除外フィルタ ----
    qc_enabled: bool = True
    qc_min_area_ratio: float = 0.30
    qc_max_area_ratio: float = 3.50
    qc_min_solidity: float = 0.85
    qc_max_eccentricity: float = 0.96     # 3D では無効
    qc_min_cellprob_pct: float = 2.0
    qc_min_dapi_rel: float = 0.15
    qc_max_saturated_frac: float = 0.90
    # 画像端（xy 面）に掛かる核を除外するか。
    qc_exclude_border: bool = False
    # z スタックの上端・下端の面に掛かる核を除外するか（3D のときだけ意味がある）。
    # xy の画像端とは意味が違うので別の設定にしている。
    # 薄い切片では「ほぼ全部の核が z 端に掛かる」ことがあるため既定は False。
    qc_exclude_z_border: bool = False

    # 汎チャンネル自家蛍光：全チャンネルで同時に明るいものにフラグを立てる。
    # ただし多重陽性の本物の細胞も同じ挙動をするので既定では除外しない。
    qc_pan_channel: bool = True
    qc_pan_channel_reject: bool = False
    qc_pan_channel_pct: float = 99.0

    # ---- 陽性判定（パターン既定を使わないマーカーのフォールバック）----
    bg_mode: str = "opening"          # 'opening'（密な組織向け） | 'annulus'（疎な培養向け）
    bg_radius_factor: float = 3.0
    bg_gap: int = 4
    bg_width: int = 12

    # ---- 点状（puncta）解析 ----
    puncta_analysis: bool = True      # punctate マーカーについて視野レベルの密度を出す
    puncta_tophat_um: float = 1.0     # トップハットのカーネル半径[µm]（輝点の大きさの目安）
    # サイズ閾値は次元ごとに別々に持つ。2D と 3D で単位が違う（µm² と µm³）ので、
    # 同じ数字を使い回すと 3D で桁が狂う（第7版の欠陥）。
    puncta_min_area_um2: float = 0.05   # 2D: これより小さい輝点はノイズとして捨てる
    puncta_max_area_um2: float = 3.00   # 2D: これより大きいものは輝点ではない（塊・自家蛍光）
    puncta_min_vol_um3: float = 0.02    # 3D: 同上（直径 0.35 µm 相当の球）
    puncta_max_vol_um3: float = 4.00    # 3D: 同上（直径 2.0 µm 相当の球）

    # ---- ダイナミックレンジ診断 ----
    diagnose_dynamic_range: bool = True
    dynamic_range_warn_frac: float = 0.25

    # ---- 疎な 2D 単層培養プリセット ----
    sparse_culture_preset: bool = False

    # ---- 出力 ----
    save_qc_images: bool = True
    save_per_cell_csv: bool = True

    def markers(self) -> list[MarkerSpec]:
        """使用するマーカー一覧を返し、未指定項目を自動解決する。"""
        ms = self.panel if self.panel is not None else PANELS.get(self.active_panel)
        if not ms:
            raise ValueError(
                f"パネル '{self.active_panel}' が見つかりません。"
                f" 使えるのは {list(PANELS)} です。")
        for m in ms:
            m.resolve()
        slots = [m.fluorophore for m in ms]
        dup = {s for s in slots if slots.count(s) > 1}
        if dup:
            raise ValueError(f"同じ蛍光色素に複数のマーカーが割り当てられています: {dup}")
        return ms


CONFIG = Config()


def apply_sparse_culture_preset(cfg: Config) -> None:
    """
    疎な 2D 単層培養向けに設定を切り替える。

    密な組織切片と違って「何も無い背景画素」が本当に存在するので、
    局所背景はオープニングではなく細胞周囲のリングから測るのが素直。
    また核が分離しているので面積のばらつきが小さく、QC は緩めてよい
    （ここでの目的は、コードの問題と試料の難しさを切り分けることだから）。
    """
    cfg.bg_mode = "annulus"
    cfg.qc_min_area_ratio = 0.20
    cfg.qc_max_area_ratio = 5.00
    cfg.qc_min_solidity = 0.80
    cfg.qc_min_cellprob_pct = 0.0
    cfg.qc_exclude_border = True
    print("-> 疎な 2D 単層培養プリセットを適用しました "
          "(bg_mode=annulus / QC 緩和 / 画像端を除外)")


# =====================================================================
# 3. 生 .czi の読み込み
# =====================================================================

# 余分な軸の意味（警告メッセージ用）。CZYX 以外はこのスクリプトでは 1 つしか扱えない。
EXTRA_AXIS_MEANING = {
    "S": "シーン（Position）", "M": "モザイクタイル", "T": "時間",
    "V": "ビュー", "B": "ブロック", "H": "位相", "I": "照明", "R": "回転",
    "0": "sample（RGB 成分）",
}


def _czi_axes_to_czyx(arr: np.ndarray, axes: str, pick: dict[str, int] | None = None,
                      quiet: bool = False) -> np.ndarray:
    """
    czifile が返す多次元配列を (C, Z, Y, X) に正規化する。

    czifile の axes は 'BVCTZYX0' のような文字列で、
    ファイルごとに軸の並びも有無も違う。np.squeeze で潰すと
    「Z が 1 枚のとき C と Z の区別が付かない」といった事故が起きるため、
    軸名を見て明示的に組み立てる。

    CZYX 以外の軸（シーン・タイル・時間など）は 1 つを選んで落とす。
    第7版はこれを黙ってやっていたが、複数 Position のファイルで
    「気づかないうちに 1 視野だけ解析していた」という最悪の事故になる。
    本版は落とした軸を必ず報告する（quiet=True のときだけ抑制）。
    """
    keep = ("C", "Z", "Y", "X")
    pick = pick or {}
    slicer, kept, dropped = [], [], []
    for ax, size in zip(axes, arr.shape):
        if ax in keep:
            slicer.append(slice(None))
            kept.append(ax)
        else:
            idx = int(pick.get(ax, 0))
            if size > 1:
                dropped.append((ax, size, idx))
            slicer.append(min(idx, size - 1))
    a = arr[tuple(slicer)]

    if dropped and not quiet:
        for ax, size, idx in dropped:
            meaning = EXTRA_AXIS_MEANING.get(ax, "不明な軸")
            print(f"   [警告] {ax} 軸（{meaning}）のサイズが {size} あります。"
                  f" その {idx} 番だけを解析します。")
        print("          全部を解析したい場合は --all-scenes を使うか、"
              "czi_scene で番号を指定してください。")

    order = [kept.index(ax) for ax in keep if ax in kept]
    a = np.transpose(a, order)
    present = [ax for ax in keep if ax in kept]
    for i, ax in enumerate(keep):
        if ax not in present:
            a = np.expand_dims(a, i)
    return a


def _parse_czi_metadata(xml: str) -> tuple[list[dict], float | None, float | None]:
    """
    .czi の XML から (チャンネル情報リスト, µm/px, z 間隔 µm) を取り出す。

    チャンネル情報は {'name':…, 'emission_nm':…, 'contrast':…} の辞書。
    並び順は XML の記載順＝取得順＝配列の C 軸順。
    """
    chans: list[dict] = []
    block = re.search(r"<Channels>(.*?)</Channels>", xml, re.S)
    if block:
        for chunk in re.findall(r"<Channel\b.*?</Channel>", block.group(1), re.S):
            dye = re.search(r"<DyeName>([^<]+)</DyeName>", chunk)
            flu = re.search(r"<Fluor>([^<]+)</Fluor>", chunk)
            nm = re.search(r'\bName="([^"]+)"', chunk)
            idm = re.search(r'\bId="([^"]+)"', chunk)
            em = re.search(r"<EmissionWavelength>([^<]+)</EmissionWavelength>", chunk)
            cm = re.search(r"<ContrastMethod>([^<]+)</ContrastMethod>", chunk)
            src = dye or flu or nm or idm
            chans.append({
                "name": src.group(1).strip() if src else "",
                "emission_nm": float(em.group(1)) if em else None,
                "contrast": cm.group(1).strip() if cm else None,
            })
    if not chans:
        chans = [{"name": d.strip(), "emission_nm": None, "contrast": None}
                 for d in re.findall(r"<DyeName>([^<]+)</DyeName>", xml)]

    def _distance(axis: str) -> float | None:
        m = re.search(rf'<Distance Id="{axis}">\s*<Value>([^<]+)</Value>', xml)
        return float(m.group(1)) * 1e6 if m else None   # m → µm

    return chans, _distance("X"), _distance("Z")


def count_czi_scenes(path: str) -> int:
    """.czi に含まれるシーン（Position）の数を返す。分からなければ 1。"""
    try:
        import czifile
    except ImportError:
        return 1
    try:
        with_czi = czifile.CziFile(path)
        try:
            return max(1, len(with_czi.scenes))
        finally:
            with_czi.close()
    except Exception:
        return 1


def _read_czi_with_czifile(path: str, scene_index: int = 0, quiet: bool = False
                           ) -> tuple[np.ndarray, list[dict], float | None, float | None]:
    """
    czifile で .czi の 1 シーンを (C, Z, Y, X) として読む。

    czifile は 2026 年版で API が変わり、
      - 旧 (〜2019): CziFile.axes が 'BVCTZYX0' のような文字列、メタデータは XML のみ
      - 新 (2026〜): CziFile.scenes[i] が .axes / .channels / .coord_scales を構造化して持つ
    という違いがある。どちらでも動くよう両対応にする。

    新 API では czi.asarray()（ファイル全体）ではなく scene.asarray() を使う。
    こちらは返る配列の軸が必ず scene.axes と一致するので、
    複数シーンのファイルで「軸を取り違えて別のシーンを読む」事故が原理的に起きない。
    第7版はファイル全体を読んで scenes[0].axes を当てていたので、
    マルチシーンでは軸がずれる危険があった。
    """
    import czifile

    czi = czifile.CziFile(path)
    try:
        scenes = None
        try:  # 新 API
            scenes = czi.scenes
        except Exception:
            scenes = None

        if scenes is not None and len(scenes) and getattr(scenes[0], "axes", None):
            n_scenes = len(scenes)
            if scene_index >= n_scenes:
                raise IndexError(
                    f"シーン {scene_index} は存在しません（このファイルは {n_scenes} シーン）。")
            if n_scenes > 1 and not quiet:
                print(f"   [警告] このファイルには {n_scenes} シーン（Position）があります。"
                      f" シーン {scene_index} を解析します。")
                print("          全部を解析するには --all-scenes を使ってください。")
            scene = scenes[scene_index]

            arr = _czi_axes_to_czyx(np.asarray(scene.asarray()), str(scene.axes), quiet=quiet)
            chans: list[dict] = []
            for key, info in (getattr(scene, "channels", None) or {}).items():
                if isinstance(info, dict):
                    chans.append({
                        "name": str(info.get("DyeName") or info.get("Fluor") or key),
                        "emission_nm": info.get("EmissionWavelength"),
                        "contrast": info.get("ContrastMethod"),
                    })
                else:
                    chans.append({"name": str(key), "emission_nm": None, "contrast": None})
            scales = getattr(scene, "coord_scales", None) or {}
            um_px = float(scales["X"]) * 1e6 if "X" in scales else None
            um_z = float(scales["Z"]) * 1e6 if "Z" in scales else None
            if um_px is None and getattr(scene, "mpp", None):
                um_px = float(scene.mpp[0])
            if chans and um_px:
                return arr, chans, um_px, um_z
            x_chans, x_px, x_z = _parse_czi_metadata(czi.metadata())
            return arr, chans or x_chans, um_px or x_px, um_z or x_z

        # 旧 API：ファイル全体を読み、余分な軸から 1 つを選ぶ
        chans, um_px, um_z = _parse_czi_metadata(czi.metadata())
        pick = {ax: scene_index for ax in ("S", "M", "V", "B")}
        arr = _czi_axes_to_czyx(czi.asarray(), str(czi.axes), pick=pick, quiet=quiet)
        return arr, chans, um_px, um_z
    finally:
        try:
            czi.close()
        except Exception:
            pass


def _read_czi_raw(path: str, scene_index: int = 0, quiet: bool = False
                  ) -> tuple[np.ndarray, list[dict], float | None, float | None]:
    """
    .czi を (C, Z, Y, X) の生配列として読む。

    czifile を第一候補にする（軽量で依存が少ない）。
    無ければ bioio + bioio-czi を試す。
    AICSImageIO は 2025 年末にアーカイブ済みなので新規には使わない。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f".czi が見つかりません: {path}")

    try:
        import czifile  # noqa: F401
    except ImportError:
        pass
    else:
        return _read_czi_with_czifile(path, scene_index, quiet)

    try:
        from bioio import BioImage
    except ImportError as exc:
        raise ImportError(
            ".czi を読むためのライブラリがありません。次のどちらかを入れてください:\n"
            "    pip install czifile\n"
            "    pip install bioio bioio-czi\n"
            "（どうしても入れられない場合は CONFIG.input_mode='images' で "
            "従来の PNG 解析に退避できます）"
        ) from exc

    img = BioImage(path)
    scene_ids = list(getattr(img, "scenes", []) or [])
    if len(scene_ids) > 1:
        if not quiet:
            print(f"   [警告] このファイルには {len(scene_ids)} シーンがあります。"
                  f" シーン {scene_index} を解析します（全部なら --all-scenes）。")
        img.set_scene(scene_ids[scene_index])
    arr = np.asarray(img.get_image_data("CZYX", T=0))
    chans = [{"name": str(n), "emission_nm": None, "contrast": None}
             for n in (img.channel_names or [])]
    pps = img.physical_pixel_sizes
    return arr, chans, getattr(pps, "X", None), getattr(pps, "Z", None)


def describe_czi(path: str) -> None:
    """--list-channels 用。ファイルの中身とスロット判定結果を表示するだけ。"""
    arr, chans, um_px, um_z = _read_czi_raw(path)
    n_c, n_z, h, w = arr.shape
    n_scenes = count_czi_scenes(path)
    print(f"ファイル : {os.path.basename(path)}")
    print(f"次元     : C={n_c}, Z={n_z}, Y={h}, X={w} / dtype={arr.dtype}")
    print(f"シーン数 : {n_scenes}" + ("" if n_scenes == 1 else "  ← --all-scenes で全部処理できます"))
    if um_px:
        print(f"画素     : {um_px:.4f} µm/px" + (f", z 間隔 {um_z:.2f} µm" if um_z else ""))
        if n_z > 1 and um_z:
            print(f"z 厚     : {n_z * um_z:.1f} µm （核 7 µm あたり {7.0 / um_z:.1f} 枚）"
                  + ("" if um_z <= 1.0 else
                     "  ← 真の 3D 解析には粗い。z ステップ ≤1 µm を推奨"))
    print("チャンネル:")
    for c, info in enumerate(chans):
        slot = _slot_for_channel(info)
        em = f"{info['emission_nm']:.0f} nm" if info.get("emission_nm") else "波長不明"
        print(f"   ch{c}: {info['name']:20s} {em:>10s}  → "
              + (f"{slot} として使用" if slot else "使用しない（透過光など）"))
    print("\nこの構成に対するパネルの書き方の例:")
    print('    PANELS["my-panel"] = [')
    for slot in ("AF488", "AF555", "AF647"):
        if any(_slot_for_channel(i) == slot for i in chans):
            print(f'        MarkerSpec("<抗体名>", "{slot}"),')
    print("    ]")


def _slot_for_channel(info: dict) -> str | None:
    """1 チャンネル分のメタ情報から蛍光色素スロットを決める（透過光は None）。"""
    contrast = (info.get("contrast") or "").strip().lower()
    if contrast and contrast != "fluorescence":
        return None   # 透過光（T-PMT）・DIC など
    return resolve_fluorophore(info.get("name", ""), info.get("emission_nm"))


def _reduce_z(stack: np.ndarray, mode: str) -> np.ndarray:
    """(Z, Y, X) を 1 枚に潰す。mode='none' ならそのまま返す。"""
    if stack.shape[0] == 1:
        return stack[0]
    if mode == "none":
        return stack
    if mode == "max":
        return stack.max(axis=0)
    if mode == "mean":
        return stack.mean(axis=0).astype(stack.dtype)
    if mode == "best":
        return stack[int(stack.mean(axis=(1, 2)).argmax())]
    raise ValueError(f"z_reduce の値が不正です: {mode}")


def load_czi_images(cfg: Config, markers: list[MarkerSpec]) -> tuple[dict[str, np.ndarray], dict]:
    """
    .czi を生輝度のまま読み、{スロット名: 画像} と撮像メタ情報を返す。

    返す辞書のキーは蛍光色素スロット（'DAPI' / 'AF488' / 'AF555' / 'AF647'）。
    マーカー名ではなくスロット名で持つのが要点で、
    これによりパネルを差し替えても読み込み層は一切変わらない。
    """
    n_scenes = count_czi_scenes(cfg.czi_path)
    tag = f"（シーン {cfg.czi_scene}/{n_scenes - 1}）" if n_scenes > 1 else ""
    print(f"-> 生の .czi を読み込み中: {os.path.basename(cfg.czi_path)} {tag}")
    arr, chans, um_px, um_z = _read_czi_raw(cfg.czi_path, cfg.czi_scene)
    n_c, n_z, h, w = arr.shape

    print(f"   次元: C={n_c}, Z={n_z}, Y={h}, X={w} / dtype={arr.dtype}")
    if um_px:
        print(f"   画素サイズ: {um_px:.4f} µm/px" + (f", z 間隔 {um_z:.2f} µm" if um_z else ""))
        # 真の 3D を狙うなら z のサンプリングが足りているかを最初に知らせる
        if cfg.use_3d and cfg.z_reduce == "none" and n_z > 1:
            if not um_z:
                print("   [警告] z 間隔が不明です。anisotropy を手で設定してください。")
            elif um_z > 1.0:
                print(f"   [警告] z ステップ {um_z:.2f} µm は真の 3D 解析には粗めです"
                      f"（核 7 µm が約 {7.0 / um_z:.1f} 枚にしか乗りません）。")
                print("          do_3D は形が破綻しやすいので stitch_threshold を推奨します。")
                print("          次回の撮像では z ステップ ≤1 µm を検討してください。")
    else:
        print("   画素サイズ: メタデータから取得できませんでした")

    # --- 蛍光色素スロットへの割り当て（名前 → 発光波長の順で照合） ---
    assign: dict[str, int] = {}
    if cfg.czi_index_map:
        assign = {k: int(v) for k, v in cfg.czi_index_map.items()}
        print(f"   czi_index_map による手動割り当てを使用: {assign}")
        for c, info in enumerate(chans):
            print(f"     ch{c}: {info['name']}")
    else:
        for c, info in enumerate(chans):
            slot = _slot_for_channel(info)
            note = f"→ {slot}" if slot else "→ 使用しない（透過光など）"
            print(f"     ch{c}: {info['name']:20s} {note}")
            if slot and slot not in assign:
                assign[slot] = c

    needed = ["DAPI"] + [m.fluorophore for m in markers]
    missing = [s for s in needed if s not in assign]
    if missing:
        raise RuntimeError(
            f"次の蛍光色素スロットを .czi の中に見つけられませんでした: {missing}\n"
            f"  検出したチャンネル: {[i['name'] for i in chans]}\n"
            f"  --list-channels で中身を確認し、パネルを直すか "
            f"CONFIG.czi_index_map で手動指定してください（例 {{'DAPI': 2}}）。")

    zr = cfg.z_reduce
    if zr == "none" and not cfg.use_3d:
        print("   注意: z_reduce='none' ですが use_3d=False です。max 投影に切り替えます。")
        zr = "max"
    if cfg.use_3d and zr != "none" and n_z > 1:
        print("   注意: use_3d=True ですが z_reduce で潰す設定です。z_reduce='none' が必要です。")

    # z プロファイルは【潰す前】の生スタックから取る（潰した後では意味がない）
    z_profile = None
    if cfg.z_profile_diagnostics and n_z > 1:
        z_profile = pd.DataFrame({
            "z_index": np.arange(n_z),
            **({"z_um": np.arange(n_z) * um_z} if um_z else {}),
            **{slot: arr[assign[slot]].reshape(n_z, -1).mean(axis=1) for slot in needed},
        })

    imgs = {slot: _reduce_z(arr[assign[slot]], zr) for slot in needed}
    shown = "そのまま (Z,Y,X)" if imgs["DAPI"].ndim == 3 else f"{zr} 投影"
    print(f"   Z {n_z} 枚 → {shown}")

    meta = {
        "source": "czi",
        "czi_path": cfg.czi_path,
        "scene": int(cfg.czi_scene),
        "n_scenes": int(n_scenes),
        "channels_in_file": [i["name"] for i in chans],
        "assignment": assign,
        "um_per_px": um_px,
        "um_per_z": um_z,
        "shape_czyx": [int(n_c), int(n_z), int(h), int(w)],
        "dtype": str(arr.dtype),
        "z_reduce": zr,
        "_z_profile": z_profile,
    }
    return imgs, meta


def report_z_profile(z_profile: pd.DataFrame | None, out_dir: str) -> None:
    """
    z 方向の輝度プロファイルを保存し、減衰が大きければ警告する。

    厚い標本では、光が深部まで届かず（散乱・吸収）、また戻ってくる蛍光も減るため、
    下の層ほど暗く写る。すると「深いところの細胞は陰性になりやすい」という
    z 依存のバイアスが陽性率に乗る。

    【補正はしない】。深さによる明るさの違いには、本物の生物学的な勾配
    （表層に分化細胞が多い等）も混ざっているため、機械的に平坦化すると
    見たかった構造ごと消してしまう。まず見えるようにして、
    減衰が大きければ撮像側（z 補正・ゲイン傾斜）で対処するのが筋。
    """
    if z_profile is None or z_profile.empty:
        return
    z_profile.to_csv(os.path.join(out_dir, "z_profile.csv"),
                     index=False, encoding="utf-8-sig")

    cols = [c for c in z_profile.columns if c not in ("z_index", "z_um")]
    print("-> z 方向の輝度プロファイル（平均輝度。z_profile.csv に保存）:")
    for c in cols:
        v = z_profile[c].to_numpy(dtype=float)
        if v.max() <= 0:
            continue
        ratio = v[-1] / max(v[0], 1e-9)
        bar = "".join("█▇▆▅▄▃▂▁"[min(7, int((1 - x / v.max()) * 8))] for x in v)
        note = ""
        if ratio < 0.5:
            note = f"  ← 最深部が表層の {ratio * 100:.0f}%。減衰が大きい"
        elif ratio > 2.0:
            note = f"  ← 最深部が表層の {ratio * 100:.0f}%。逆勾配"
        print(f"     {c:6s} {bar}{note}")
    print("     ※ 補正はしていません（本物の生物学的勾配を消さないため）。")
    print("       減衰が大きい場合は撮像側の z 補正／ゲイン傾斜で対処してください。")


# =====================================================================
# 4. 書き出し済み PNG の読み込み（比較・退避用）
# =====================================================================

def load_intensity(path: str, mode: str = "auto", label: str = "") -> np.ndarray:
    """
    顕微鏡ソフトが書き出した擬似カラー PNG/TIFF から実際の輝度画像を取り出す。

    LUT で着色した RGB を IMREAD_GRAYSCALE で読むと
    0.299R+0.587G+0.114B の重み付けが掛かり、青い DAPI は 0.114 倍まで圧縮される。
    LUT は「1 つの強度を色に写像したもの」なので、
    各画素で RGB の最大値を取れば元の強度が（8bit の範囲で）復元できる。

    第6版以降は .czi を直接読むのが既定なので、この関数は
    比較・退避用（input_mode='images'）の経路でしか使われない。
    """
    data = np.fromfile(path, dtype=np.uint8) if os.path.exists(path) else None
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data is not None else None
    if img is None:
        raise FileNotFoundError(f"{label} の画像を読み込めません: {path}")

    if img.ndim == 2:
        return img

    if img.shape[2] == 4:
        img = img[:, :, :3]

    b, g, r = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    is_gray = np.array_equal(b, g) and np.array_equal(g, r)

    if mode == "luminance":
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if is_gray and mode == "auto":
        return b

    lut_used = [n for n, c in zip("BGR", (b, g, r)) if int(c.max()) > 0]
    inten = img.max(axis=2)
    lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print(f"   {label:14s} 擬似カラー({'+'.join(lut_used)}) を検出 → 最大値投影で復元 "
          f"[最大輝度 {lum.max():3d}(旧) → {inten.max():3d}(新)]")
    return inten


def register_to_reference(ref: np.ndarray, mov: np.ndarray, cfg: Config,
                          label: str = "") -> tuple[np.ndarray, tuple[int, int]]:
    """
    位相相関で並進ずれを推定し、整数画素でシフトして返す。

    注意：異なる抗原を写した画像同士は写っている構造そのものが違うため、
    位相相関は本質的に信頼できない。相関値とずれ幅の両方で門番をかけ、
    怪しい推定は必ず棄却する（誤った補正は無補正より有害）。
    """
    h = min(ref.shape[0], mov.shape[0])
    w = min(ref.shape[1], mov.shape[1])
    a = ref[:h, :w].astype(np.float32)
    b = mov[:h, :w].astype(np.float32)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, win)

    if response < cfg.min_registration_response:
        print(f"   {label:14s} 位相相関の信頼度が低い ({response:.3f}) ため補正を見送り")
        return mov, (0, 0)
    if abs(dx) > cfg.max_shift_px or abs(dy) > cfg.max_shift_px:
        print(f"   {label:14s} 推定ずれ ({dx:+.1f}, {dy:+.1f}) px が大きすぎるため補正を見送り")
        return mov, (0, 0)

    sx, sy = int(round(-dx)), int(round(-dy))
    if sx == 0 and sy == 0:
        print(f"   {label:14s} 位置ずれなし (相関 {response:.3f})")
        return mov, (0, 0)

    M = np.float32([[1, 0, sx], [0, 1, sy]])
    shifted = cv2.warpAffine(mov, M, (mov.shape[1], mov.shape[0]),
                             flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    print(f"   {label:14s} 位置ずれ ({sx:+d}, {sy:+d}) px を補正 (相関 {response:.3f})")
    return shifted, (sx, sy)


def load_png_images(cfg: Config, markers: list[MarkerSpec]) -> tuple[dict[str, np.ndarray], dict]:
    """PNG を読み込み、{スロット名: 画像} を返す（.czi 経路と同じ形にそろえる）。"""
    print("-> 書き出し済み画像を読み込み中（擬似カラーからの輝度復元を含む）...")
    if not cfg.dapi_path:
        raise ValueError("input_mode='images' では CONFIG.dapi_path が必要です。")
    raw = {"DAPI": load_intensity(cfg.dapi_path, cfg.intensity_mode, "DAPI")}
    for m in markers:
        if not m.path:
            raise ValueError(f"input_mode='images' では MarkerSpec('{m.name}') に path が必要です。")
        raw[m.fluorophore] = load_intensity(m.path, cfg.intensity_mode, m.name)

    h = min(im.shape[0] for im in raw.values())
    w = min(im.shape[1] for im in raw.values())
    sizes = {k: im.shape for k, im in raw.items()}
    if len(set(sizes.values())) > 1:
        print(f"   画素サイズが不揃いのため共通領域 {w}x{h} で切り揃えます")
    imgs = {k: im[:h, :w] for k, im in raw.items()}

    if cfg.register_channels:
        print("-> チャンネル間の位置ずれを補正中（位相相関）...")
        for m in markers:
            imgs[m.fluorophore], _ = register_to_reference(
                imgs["DAPI"], imgs[m.fluorophore], cfg, m.name)

    return imgs, {"source": "images", "dapi_path": cfg.dapi_path,
                  "um_per_px": None, "um_per_z": None}


def load_all_images(cfg: Config, markers: list[MarkerSpec]) -> tuple[dict[str, np.ndarray], dict]:
    if cfg.input_mode == "czi":
        return load_czi_images(cfg, markers)
    if cfg.input_mode == "images":
        return load_png_images(cfg, markers)
    raise ValueError(f"input_mode が不正です: {cfg.input_mode}")


# =====================================================================
# 5. ダイナミックレンジ診断
# =====================================================================

def diagnose_dynamic_range(imgs: dict[str, np.ndarray], labels_for: dict[str, str],
                           cfg: Config) -> pd.DataFrame:
    """
    各チャンネルが階調をどれだけ使えているかを診断する。

    実測（本データ）では 8bit 取得で p99 が DAPI 59 / AF555 33 / AF488 26 / AF647 30
    しかなく、信号が下位 1〜2 割にしか乗っていなかった。

    - 検出（カウント）への影響：Cellpose-SAM は内部で正規化するので軽微。
    - 陽性判定への影響：深刻。陽性/陰性の線引きを 30 階調の幅で行うことになり、
      閾値がノイズに対して極めて敏感になる。

    これは解析側では回復できない（失われた階調は戻らない）。
    根本対策は撮像側：16bit 取得 ＋ ゲイン/露光を上げて階調を使い切ること。
    """
    rows = []
    for slot, im in imgs.items():
        full = float(np.iinfo(im.dtype).max) if np.issubdtype(im.dtype, np.integer) else float(im.max())
        p99 = float(np.percentile(im, 99))
        rows.append({
            "slot": slot,
            "marker": labels_for.get(slot, slot),
            "dtype": str(im.dtype),
            "full_scale": full,
            "min": float(im.min()),
            "max": float(im.max()),
            "median": float(np.median(im)),
            "p99": p99,
            "p99_frac_of_full_scale": round(p99 / max(full, 1e-9), 4),
            "zero_pixel_frac": round(float((im == 0).mean()), 4),
        })
    diag = pd.DataFrame(rows)

    if not cfg.diagnose_dynamic_range:
        return diag

    print("-> ダイナミックレンジ診断:")
    weak = []
    for r in rows:
        frac = r["p99_frac_of_full_scale"]
        mark = " ←狭い" if frac < cfg.dynamic_range_warn_frac else ""
        print(f"     {r['marker']:16s}({r['slot']:5s}) max {r['max']:6.0f} / p99 {r['p99']:6.0f} "
              f"（全階調 {r['full_scale']:.0f} の {frac * 100:4.1f}%）"
              f" 0 の画素 {r['zero_pixel_frac'] * 100:4.1f}%{mark}")
        if frac < cfg.dynamic_range_warn_frac:
            weak.append(r["marker"])

    if weak:
        print("   [警告] 次のチャンネルは階調の大半を使えていません: " + ", ".join(weak))
        print("          核の検出は Cellpose の内部正規化が吸収しますが、")
        print("          陽性/陰性の線引きが狭い階調幅で行われるため閾値がノイズに敏感になります。")
        print("          → 解析側では回復できません。次回の撮像で 16bit 取得にし、")
        print("            ゲイン/露光を上げて階調を使い切ってください。")
        print("          → 今回の陽性率は『暫定値』として扱ってください。")
    return diag


# =====================================================================
# 6. セグメンテーション（Cellpose-SAM）
# =====================================================================

def segment_nuclei(dapi: np.ndarray, cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    """
    Cellpose で核を検出する。ラベル画像と cellprob マップを返す。

    前処理は意図的に行っていない。
    CLAHE・トップハット・ガンマ補正・cellprob_threshold の引き下げは
    本データで検証した結果、いずれも密な領域で隣接核を融合させ
    検出数をむしろ減らした。Cellpose-SAM の内部正規化に任せるのが最良。
    """
    from cellpose import models, core

    gpu = bool(cfg.use_gpu and core.use_gpu())
    if cfg.use_gpu and not gpu:
        print("   GPU が使えないため CPU で実行します（数分かかることがあります）")
    print(f"-> Cellpose-SAM を読み込み中 (GPU={gpu}) ...")
    model = models.CellposeModel(gpu=gpu)

    eval_kw = dict(
        normalize=True,
        diameter=cfg.diameter,
        cellprob_threshold=cfg.cellprob_threshold,
        flow_threshold=cfg.flow_threshold,
        min_size=cfg.min_size,
    )

    if cfg.use_3d and dapi.ndim == 3:
        if cfg.stitch_threshold > 0:
            print(f"-> 3D: 2D+stitch モード (stitch_threshold={cfg.stitch_threshold}) で "
                  f"{dapi.shape[0]} 枚を処理中...")
            eval_kw["stitch_threshold"] = cfg.stitch_threshold
        else:
            print(f"-> 3D: do_3D モードで {dapi.shape[0]} 枚を処理中"
                  f"（anisotropy={cfg.anisotropy}）...")
            eval_kw["do_3D"] = True
            eval_kw["anisotropy"] = cfg.anisotropy
    else:
        print("-> DAPI から核を検出中...")

    masks, flows, _ = model.eval(dapi, **eval_kw)
    labels = np.asarray(masks).astype(np.int32)
    cellprob = np.asarray(flows[2]).astype(np.float32) if len(flows) > 2 \
        else np.zeros(labels.shape, np.float32)
    if cellprob.shape != labels.shape:
        cellprob = np.zeros(labels.shape, np.float32)

    print(f"-> Cellpose が検出したオブジェクト数: {labels.max()} 個（この時点ではゴミを含む）")
    return labels, cellprob


# =====================================================================
# 7. ROI の構築
# =====================================================================

def build_rois(labels: np.ndarray, distance: float,
               spacing: tuple[float, ...] | None = None) -> dict[str, np.ndarray]:
    """
    核マスク・拡張マスク・リングマスクを作る。

    expand_labels による等距離（ボロノイ的）拡張を使い、隣接細胞に公平に境界を引く
    （順に膨張させると、ラベル番号の若い細胞が画素を先取りして偏る）。

    ★spacing を渡すのが第8版の修正点。
      spacing 無しの expand_labels は距離を【ボクセル数】で測る。
      xy 0.312 µm / z 2.0 µm のような異方性のあるスタックでは、
      distance=10 が xy で 3.1 µm・z で 20 µm を意味してしまい、
      核の上下に 10 µm ずつという非常識なリングができる。
      spacing=(z, y, x) を渡せば distance はそのまま実寸[µm]になる。

      なお spacing が等方（全軸が同じ実寸）なら、距離をボクセル数に直して
      spacing 無しで呼ぶ。数学的には同じだが、spacing を渡すと距離計算に
      浮動小数の誤差が乗り、等距離にある 2 つの核の境界で
      ごく一部の画素の帰属が入れ替わる（実測で 2906 画素中 2 画素）。
      2D の既存結果とビット単位で一致させたいのでこちらを使う。
    """
    nucleus = labels
    if distance > 0:
        if spacing is not None and len(set(spacing)) == 1:
            cell = segmentation.expand_labels(labels, distance=distance / spacing[0])
        elif spacing is not None:
            cell = segmentation.expand_labels(labels, distance=distance, spacing=spacing)
        else:
            cell = segmentation.expand_labels(labels, distance=distance)
    else:
        cell = labels.copy()
    ring = np.where(nucleus > 0, 0, cell)
    return {"nucleus": nucleus, "cell": cell, "ring": ring}


def voxel_spacing(ndim: int, um_px: float | None,
                  um_z: float | None) -> tuple[float, ...] | None:
    """ボクセルの実寸を (z, y, x) または (y, x) で返す。分からなければ None。"""
    if not um_px:
        return None
    if ndim == 2:
        return (um_px, um_px)
    if not um_z:
        return None
    return (um_z, um_px, um_px)


# =====================================================================
# 8. 背景推定とトップハット
# =====================================================================

def _morph_2d_or_perplane(f: np.ndarray, op: int, radius: int) -> np.ndarray:
    """2D ならそのまま、3D なら面ごとにモルフォロジ演算を掛ける。"""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
    if f.ndim == 2:
        return cv2.morphologyEx(f, op, k)
    out = np.empty_like(f)
    for z in range(f.shape[0]):
        out[z] = cv2.morphologyEx(f[z], op, k)
    return out


def estimate_background(img: np.ndarray, nucleus_diameter: float, cfg: Config) -> np.ndarray:
    """
    局所背景像を推定する（rolling ball 相当）。

    核直径の数倍のカーネルでオープニングすると、核サイズの構造が消えた
    「なだらかな背景」が残る。これを引くことで、細胞が密で
    「何も無い背景画素」が存在しない標本でも局所背景補正ができる。

    画素レベルのノイズ σ は推定しない。8bit 書き出しでは背景が 0 にクリップされ、
    MAD による σ 推定が潰れて「σ の何倍」が意味を失うため。
    閾値はすべて細胞集団そのものの分布から決める（score_marker を参照）。
    """
    f = img.astype(np.float32)
    radius = max(5, int(round(nucleus_diameter * cfg.bg_radius_factor)))
    bg = _morph_2d_or_perplane(f, cv2.MORPH_OPEN, radius)
    sigma = radius / 2.0
    if bg.ndim == 2:
        return cv2.GaussianBlur(bg, (0, 0), sigmaX=sigma)
    for z in range(bg.shape[0]):
        bg[z] = cv2.GaussianBlur(bg[z], (0, 0), sigmaX=sigma)
    return bg


def white_tophat(f: np.ndarray, radius_px: int) -> np.ndarray:
    """
    小さな輝点だけを残す（点状マーカー用）。

    カーネルより小さい明るい構造だけが残るので、
    ゆるやかな背景のムラや、広がった細胞質の染まりが落ちて、
    シナプス輝点のような小さな点が相対的に浮き上がる。
    """
    return _morph_2d_or_perplane(f.astype(np.float32), cv2.MORPH_TOPHAT, max(1, int(radius_px)))


def robust_threshold(pool: np.ndarray, method: str, mad_k: float,
                     fixed: float | None = None) -> float:
    """細胞ごとの値の 1 次元分布から陽性閾値を決める。"""
    pool = np.asarray(pool, dtype=np.float64)
    if method == "fixed" and fixed is not None:
        return float(fixed)
    if method == "mad" or pool.size < 20 or np.allclose(pool, pool[0] if pool.size else 0):
        med = float(np.median(pool)) if pool.size else 0.0
        mad = float(np.median(np.abs(pool - med))) if pool.size else 0.0
        return med + mad_k * 1.4826 * mad
    try:
        return float(filters.threshold_otsu(pool))
    except Exception:
        med = float(np.median(pool))
        mad = float(np.median(np.abs(pool - med)))
        return med + mad_k * 1.4826 * mad


def annulus_background(img: np.ndarray, labels: np.ndarray, roi_labels: np.ndarray,
                       cfg: Config) -> dict[int, float]:
    """各細胞の周囲リング（他の核を除く）から局所背景を求める。疎な培養向け。"""
    if img.ndim != 2:
        print("   注意: annulus 背景は 2D 専用です。opening 背景のみを使います。")
        return {}

    f = img.astype(np.float32)
    inner = cfg.expansion_pixels + cfg.bg_gap
    outer = inner + cfg.bg_width
    k_in = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * inner + 1,) * 2)
    k_out = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * outer + 1,) * 2)

    out: dict[int, float] = {}
    other_nuclei = labels > 0
    for prop in measure.regionprops(roi_labels):
        lid = prop.label
        pad = outer + 2
        r0 = max(prop.bbox[0] - pad, 0); c0 = max(prop.bbox[1] - pad, 0)
        r1 = min(prop.bbox[2] + pad, labels.shape[0]); c1 = min(prop.bbox[3] + pad, labels.shape[1])
        sub = (roi_labels[r0:r1, c0:c1] == lid).astype(np.uint8)
        ring = cv2.dilate(sub, k_out) - cv2.dilate(sub, k_in)
        ring = (ring > 0) & (~other_nuclei[r0:r1, c0:c1])
        vals = f[r0:r1, c0:c1][ring]
        out[lid] = float(np.median(vals)) if vals.size >= 20 else 0.0
    return out


# =====================================================================
# 9. オブジェクトの特徴量抽出とデブリ判定
# =====================================================================

def _solidity_3d(prop) -> float:
    """3D の solidity（凸包体積に対する充填率）。計算できなければ 1.0 を返す。"""
    try:
        return float(prop.area / max(prop.convex_image.sum(), 1))
    except Exception:
        return 1.0


def measure_objects(labels: np.ndarray, dapi: np.ndarray, cellprob: np.ndarray,
                    dapi_bg: np.ndarray) -> pd.DataFrame:
    """
    各オブジェクトの形態・強度・Cellpose 確信度をまとめる。

    3D では eccentricity が定義されないため NaN を入れる
    （該当する QC 規則は classify_debris 側で自動的に無効になる）。
    """
    is3d = labels.ndim == 3
    sat_value = int(dapi.max())
    corrected = dapi.astype(np.float32) - dapi_bg
    shape = labels.shape

    rows = []
    for prop in measure.regionprops(labels, intensity_image=dapi):
        idx = tuple(prop.coords[:, i] for i in range(prop.coords.shape[1]))
        vals = dapi[idx].astype(np.float32)
        corr = corrected[idx]
        bbox = prop.bbox
        half = len(bbox) // 2
        row = {
            "cell_id": prop.label,
            "area": prop.area,
            "equiv_diameter": prop.equivalent_diameter,
            "solidity": _solidity_3d(prop) if is3d else float(prop.solidity),
            "eccentricity": np.nan if is3d else float(prop.eccentricity),
            "extent": prop.extent,
            "cellprob_mean": float(cellprob[idx].mean()),
            "dapi_mean": float(vals.mean()),
            "dapi_p75": float(np.percentile(vals, 75)),
            "dapi_std": float(vals.std()),
            "dapi_corrected_p75": float(np.percentile(corr, 75)),
            "saturated_frac": float((vals >= sat_value).mean()),
        }
        # 画像端の判定は xy 面と z 面を分ける。
        # z スタックの上端・下端に掛かる核は「z 方向に切れている」が、
        # xy の視野端に掛かるのとは意味が違う（薄い切片では大半の核が z 端に掛かる）。
        ax = list(range(half))
        xy_axes = ax[1:] if is3d else ax
        row["touches_border_xy"] = bool(
            any(bbox[i] == 0 for i in xy_axes)
            or any(bbox[half + i] == shape[i] for i in xy_axes))
        row["touches_border_z"] = bool(
            is3d and (bbox[0] == 0 or bbox[half] == shape[0]))
        if is3d:
            row["centroid_z"], row["centroid_y"], row["centroid_x"] = prop.centroid
        else:
            row["centroid_y"], row["centroid_x"] = prop.centroid
            row["perimeter"] = prop.perimeter
        rows.append(row)
    return pd.DataFrame(rows)


def classify_debris(df: pd.DataFrame, imgs: dict[str, np.ndarray],
                    markers: list[MarkerSpec], roi_maps: dict[str, np.ndarray],
                    backgrounds: dict[str, np.ndarray], cfg: Config) -> pd.DataFrame:
    """
    多基準でゴミを判定する。

    Cellpose は「核らしい形」で学習しているので、形の似たゴミは弾けない。
    そこで形態・輝度・Cellpose の確信度・そしてチャンネル間の関係を組み合わせる。
    どの基準に引っかかったかは qc_reason 列に全て残す（後から基準を調整できるように）。
    """
    n = len(df)
    reasons: list[list[str]] = [[] for _ in range(n)]
    if not cfg.qc_enabled or n == 0:
        df["qc_reason"] = ["" for _ in range(n)]
        df["is_cell"] = True
        return df

    median_area = float(df["area"].median())

    small = df["area"] < median_area * cfg.qc_min_area_ratio
    large = df["area"] > median_area * cfg.qc_max_area_ratio
    jagged = df["solidity"] < cfg.qc_min_solidity
    elong = df["eccentricity"].fillna(0.0) > cfg.qc_max_eccentricity   # 3D では常に False

    cp_cut = float(np.percentile(df["cellprob_mean"], cfg.qc_min_cellprob_pct))
    lowprob = df["cellprob_mean"] < cp_cut

    # DAPI 強度は「集団中央値に対する相対値」で見る。
    # 画素ノイズ σ は背景が 0 にクリップされていて推定できないため使わない。
    # 意図的にゆるく設定する（厳しくすると救いたい薄い核まで落ちる）。
    med_dapi = float(np.median(df["dapi_corrected_p75"]))
    df["dapi_relative"] = df["dapi_corrected_p75"] / max(med_dapi, 1e-6)
    dim = df["dapi_relative"] < cfg.qc_min_dapi_rel

    flat = df["saturated_frac"] > cfg.qc_max_saturated_frac

    # 汎チャンネル自家蛍光：ホコリ・析出物は全チャンネルに漏れ込んで同時に光る。
    # σ 倍ではなく「集団内での順位」で見る（スケールに依存せず頑健）。
    # ただし多重陽性の本物の細胞も同じ挙動をするので、既定ではフラグのみ。
    pan = pd.Series(False, index=df.index)
    if cfg.qc_pan_channel and len(markers) >= 2:
        above_all = np.ones(n, dtype=bool)
        for m in markers:
            f = imgs[m.fluorophore].astype(np.float32) - backgrounds[m.fluorophore]
            vals = ndi.labeled_comprehension(
                f, roi_maps["cell"], df["cell_id"].to_numpy(),
                lambda v: float(np.percentile(v, 75)), float, 0.0)
            above_all &= vals > float(np.percentile(vals, cfg.qc_pan_channel_pct))
        df["pan_channel_flag"] = above_all
        note = "除外します" if cfg.qc_pan_channel_reject else "フラグのみ（除外しません）"
        print(f"   汎チャンネル自家蛍光の疑い: {int(above_all.sum())} 個（上位 "
              f"{100 - cfg.qc_pan_channel_pct:.0f}% を全チャンネルで満たすもの） → {note}")
        if cfg.qc_pan_channel_reject:
            pan = pd.Series(above_all, index=df.index)

    no = pd.Series(False, index=df.index)
    border_xy = df["touches_border_xy"] if cfg.qc_exclude_border else no
    border_z = df["touches_border_z"] if cfg.qc_exclude_z_border else no

    rules = [
        ("面積が小さすぎる", small),
        ("面積が大きすぎる", large),
        ("凸性が低い(いびつ)", jagged),
        ("細長すぎる", elong),
        ("Cellpose確信度が低い", lowprob),
        ("DAPIが暗すぎる", dim),
        ("飽和してのっぺり", flat),
        ("全チャンネルで発光(自家蛍光)", pan),
        ("視野端(xy)にかかる", border_xy),
        ("スタック端(z)にかかる", border_z),
    ]
    for name, mask in rules:
        for i in np.flatnonzero(np.asarray(mask)):
            reasons[i].append(name)

    df["qc_reason"] = ["; ".join(r) for r in reasons]
    df["is_cell"] = df["qc_reason"] == ""

    n_rej = int((~df["is_cell"]).sum())
    print(f"-> デブリ判定: {n} 個中 {n_rej} 個を除外、{n - n_rej} 個を細胞として採用")
    if n_rej:
        for name, mask in sorted(rules, key=lambda kv: -int(np.asarray(kv[1]).sum())):
            c = int(np.asarray(mask).sum())
            if c:
                print(f"     - {name}: {c} 個")
    return df


# =====================================================================
# 10. 陽性判定（染色パターンごとに測り方を変える）
# =====================================================================

def score_marker(df: pd.DataFrame, m: MarkerSpec, img: np.ndarray,
                 roi_maps: dict[str, np.ndarray], bg: np.ndarray, cfg: Config,
                 annulus_bg: dict[int, float] | None,
                 um_per_px: float | None) -> tuple[pd.DataFrame, float, np.ndarray]:
    """
    マーカー 1 つ分の陽性判定。補正後画像も返す（puncta 解析で再利用するため）。

    手順：
      1. 局所背景を引いた補正画像を作る（点状マーカーならさらにトップハット）
      2. 細胞ごとに ROI 内の指定分位を「その細胞のシグナル」とする
      3. その細胞レベルの分布（1 次元）に対して閾値を決める
         → 画素の集合ではなく細胞の集合に対する大津なので、
           背景画素の多さに閾値が引きずられない
      4. 加えて「ROI 内で閾値を超える画素が一定割合以上」を要求する

    ここで 2 と 4 の値が染色パターンで変わるのが第7版の要点。
    面で広がる染色（cytoplasmic 等）は p75 と 30%、
    点状の染色（punctate）は p97 と 2%。同じ基準で測ると点状マーカーは全部陰性になる。

    注意：この判定の解像度は元画像の階調幅に直接支配される。
    p99 が全階調の 1 割程度しかない撮像では閾値の位置がノイズで揺れるため、
    diagnose_dynamic_range の警告が出ている場合、得られた陽性率は暫定値である。
    """
    roi = roi_maps[m.roi]
    corrected = img.astype(np.float32) - bg

    if m.enhance == "tophat":
        r = max(1, int(round((cfg.puncta_tophat_um / um_per_px) if um_per_px else 3)))
        corrected = white_tophat(corrected, r)
        print(f"   {m.name:16s} 点状マーカーのためトップハット強調（半径 {r} px）")

    ids = df["cell_id"].to_numpy()
    pct = float(m.signal_percentile)

    # ROI が空（例：ring で expansion=0）の細胞に備えて 0 を既定値にする
    sig = ndi.labeled_comprehension(
        corrected, roi, ids, lambda v: float(np.percentile(v, pct)), float, 0.0)
    if annulus_bg:
        sig = sig - np.array([annulus_bg.get(int(i), 0.0) for i in ids], dtype=np.float32)

    pool = sig[df["is_cell"].to_numpy()]
    thr = robust_threshold(pool, m.threshold_method, m.mad_k, m.fixed_threshold)

    frac = ndi.labeled_comprehension(
        corrected, roi, ids, lambda v: float((v >= thr).mean()), float, 0.0)

    df[f"{m.key}_signal"] = sig
    df[f"{m.key}_bright_frac"] = frac
    df[f"{m.key}_positive"] = (
        (sig >= thr) & (frac >= float(m.min_positive_fraction)) & df["is_cell"].to_numpy()
    )
    return df, thr, corrected


# =====================================================================
# 11. 点状（puncta）解析
# =====================================================================

def measure_puncta(enhanced: np.ndarray, tissue: np.ndarray, m: MarkerSpec,
                   n_cells: int, um_per_px: float | None, um_per_z: float | None,
                   cfg: Config) -> dict:
    """
    点状マーカーの輝点を数え、面積（3D なら体積）あたりの密度を出す。

    なぜ陽性細胞率ではなくこれを見るのか：
        シナプスは細胞ではなく突起の上にあり、どの細胞のものか帰属できない。
        隣り合う 2 つのニューロンの間にある輝点は、どちらの持ち物とも言えない。
        だから「陽性細胞率」は原理的に曖昧で、
        標準的な readout は【単位面積（体積）あたりの輝点数】になる。

    ★第8版の修正点：単位をボクセルの次元に合わせる。
      第7版は px_area = um_per_px ** 2 を固定で使っていたので、
      3D で走らせると「ボクセル数 × µm²」という意味のない量になり、
      密度の桁が狂っていた（しかもエラーにならず黙って間違った数字が出る）。
      本版は 2D なら µm²、3D なら µm³ で数え、単位を出力に明記する。

    閾値は解析対象領域（細胞 ROI の和集合）の画素だけを使った大津で決める。
    画像の大半を占める真っ黒な背景を含めると閾値が背景側に引っ張られるため。
    """
    is3d = enhanced.ndim == 3
    if um_per_px is None or (is3d and um_per_z is None):
        print(f"   {m.name:16s} ボクセルサイズが不明なため puncta 密度は算出できません")
        return {}

    # 2D はボクセル面積[µm²]、3D はボクセル体積[µm³]
    unit_size = um_per_px ** 2 * (um_per_z if is3d else 1.0)
    unit = "um^3" if is3d else "um^2"
    lo = cfg.puncta_min_vol_um3 if is3d else cfg.puncta_min_area_um2
    hi = cfg.puncta_max_vol_um3 if is3d else cfg.puncta_max_area_um2

    vals = enhanced[tissue]
    if vals.size < 100:
        return {}
    try:
        thr = float(filters.threshold_otsu(vals))
    except Exception:
        med = float(np.median(vals))
        thr = med + 3.0 * 1.4826 * float(np.median(np.abs(vals - med)))

    mask = (enhanced >= thr) & tissue
    lab, _ = ndi.label(mask)
    if lab.max() == 0:
        return {}

    sizes = np.bincount(lab.ravel())[1:] * unit_size
    keep = (sizes >= lo) & (sizes <= hi)
    n_puncta = int(keep.sum())

    tissue_size = float(tissue.sum()) * unit_size
    return {
        "Marker": m.name,
        "Pattern": m.resolved_pattern,
        "Dimensionality": "3D" if is3d else "2D",
        "Unit": unit,
        "Puncta": n_puncta,
        "Rejected_by_size": int((~keep).sum()),
        "Tissue_size": round(tissue_size, 1),
        "Density(/1000 unit)": round(n_puncta / tissue_size * 1000, 3) if tissue_size else np.nan,
        "Puncta_per_cell": round(n_puncta / n_cells, 2) if n_cells else np.nan,
        "Mean_puncta_size": round(float(sizes[keep].mean()), 4) if n_puncta else np.nan,
        "Size_range_used": f"{lo}–{hi} {unit}",
        "Pixel_threshold": round(thr, 3),
    }


# =====================================================================
# 12. QC 画像の出力
# =====================================================================

def imwrite_unicode(path: str, img: np.ndarray) -> None:
    """cv2.imwrite は非 ASCII パスで黙って失敗するため、エンコードしてから書く。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f"画像のエンコードに失敗しました: {path}")
    buf.tofile(path)


def project2d(arr: np.ndarray) -> np.ndarray:
    """3D なら z 最大値投影して 2D にする（表示用）。"""
    return arr.max(axis=0) if arr.ndim == 3 else arr


def to_bgr(img: np.ndarray) -> np.ndarray:
    v = project2d(img).astype(np.float32)
    lo, hi = np.percentile(v, [1, 99.5])
    v = np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1)
    return cv2.cvtColor((v * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def save_qc_images(out_dir: str, imgs: dict[str, np.ndarray], markers: list[MarkerSpec],
                   labels: np.ndarray, roi_maps: dict[str, np.ndarray],
                   df: pd.DataFrame, cfg: Config) -> None:
    """採用/除外、および各マーカーの陽性細胞を可視化する。3D なら投影して表示する。"""
    accepted = set(df.loc[df["is_cell"], "cell_id"].tolist())
    lab2d = project2d(labels)

    # --- セグメンテーション QC：採用=緑、除外=赤 ---
    # mode="inner" が必須。"outer" だと輪郭画素が対象の外側（背景や隣の細胞）に載るため、
    # その画素のラベルを引くと別の細胞の採否を参照してしまい色分けが崩れる。
    canvas = to_bgr(imgs["DAPI"])
    bnd = segmentation.find_boundaries(lab2d, mode="inner")
    acc_mask = np.isin(lab2d, list(accepted)) if accepted else np.zeros(lab2d.shape, bool)
    canvas[bnd & acc_mask] = (0, 255, 0)
    canvas[bnd & (lab2d > 0) & ~acc_mask] = (0, 0, 255)
    imwrite_unicode(os.path.join(out_dir, "qc_segmentation.png"), canvas)

    rng = np.random.default_rng(42)
    colors = rng.integers(0, 255, size=(int(labels.max()) + 1, 3), dtype=np.uint8)
    colors[0] = 0
    imwrite_unicode(os.path.join(out_dir, "labels_colored.png"), colors[lab2d])
    np.save(os.path.join(out_dir, "labels.npy"), labels)

    for m in markers:
        col = f"{m.key}_positive"
        if col not in df.columns:
            continue
        pos = set(df.loc[df[col], "cell_id"].tolist())
        canvas = to_bgr(imgs[m.fluorophore])
        roi = project2d(roi_maps[m.roi])
        rb = segmentation.find_boundaries(roi, mode="inner")
        pos_mask = np.isin(roi, list(pos)) if pos else np.zeros(roi.shape, bool)
        neg_mask = np.isin(roi, list(accepted - pos)) if accepted else np.zeros(roi.shape, bool)
        canvas[rb & neg_mask] = (120, 120, 120)  # 陰性 = 灰
        canvas[rb & pos_mask] = (0, 255, 255)    # 陽性 = 黄（陰性より優先して描く）
        imwrite_unicode(os.path.join(out_dir, f"qc_positive_{m.key}.png"), canvas)

    # LUT を経由しない素の入力（マーカー名でファイル名を付ける）
    slot_to_marker = {m.fluorophore: m.key for m in markers}
    for slot, im in imgs.items():
        imwrite_unicode(os.path.join(out_dir, f"raw_{slot_to_marker.get(slot, slot)}.png"),
                        to_bgr(im))


# =====================================================================
# 13. メイン
# =====================================================================

def analyze(cfg: Config) -> dict[str, pd.DataFrame] | None:
    markers = cfg.markers()

    print("-> パネル構成:")
    unsure = []
    for m in markers:
        auto = "" if m.pattern else "（自動判定）"
        print(f"     {m.fluorophore:5s} = {m.name:16s} pattern={m.resolved_pattern:11s}"
              f" ROI={m.roi:7s} p{m.signal_percentile:.0f} / 面積条件 "
              f"{m.min_positive_fraction * 100:.0f}% {auto}")
        if not m.pattern_confident:
            unsure.append(m.name)
    if unsure:
        print(f"   [注意] 次のマーカーは MARKER_LIBRARY に登録がないため "
              f"'{DEFAULT_PATTERN}' を仮定しました: {', '.join(unsure)}")
        print(f"          染まり方が違う場合は MarkerSpec(..., pattern='...') で明示するか、")
        print(f"          MARKER_LIBRARY に追加してください "
              f"（{list(PATTERN_DEFAULTS)}）。")

    if cfg.sparse_culture_preset:
        apply_sparse_culture_preset(cfg)

    # ---- 出力先 ----
    if cfg.output_dir:
        out_dir = cfg.output_dir
    elif cfg.input_mode == "czi":
        base = os.path.splitext(os.path.basename(cfg.czi_path))[0]
        out_dir = os.path.join(os.path.dirname(cfg.czi_path), f"{base}_results_9th")
    else:
        out_dir = os.path.join(os.path.dirname(cfg.dapi_path), "results_9th")
    os.makedirs(out_dir, exist_ok=True)

    # ---- 1. 読み込み ----
    if cfg.input_mode == "czi" and cfg.register_channels:
        print("-> .czi は同一撮像なので位置合わせは不要です（register_channels を無効化しました）")
        cfg.register_channels = False
    imgs, meta = load_all_images(cfg, markers)

    # ---- 2. スケールに基づくパラメータの自動決定 ----
    um_px = meta.get("um_per_px")
    um_z = meta.get("um_per_z")
    if um_px:
        if cfg.nucleus_diameter_um:
            cfg.diameter = cfg.nucleus_diameter_um / um_px
            print(f"-> diameter を {cfg.diameter:.1f} px に設定 "
                  f"({cfg.nucleus_diameter_um} µm ÷ {um_px:.4f} µm/px)")
        else:
            print(f"-> 参考: 核直径 7 µm は約 {7.0 / um_px:.1f} px "
                  f"（diameter=None のまま Cellpose-SAM の自動推定に任せます。"
                  f"密領域で核が融合するなら nucleus_diameter_um を設定して試すこと）")
        if cfg.use_3d and cfg.anisotropy is None and um_z:
            cfg.anisotropy = um_z / um_px
            print(f"-> anisotropy を {cfg.anisotropy:.2f} に自動設定")

    # ---- 3. ダイナミックレンジ診断と z プロファイル ----
    slot_to_marker = {m.fluorophore: m.name for m in markers}
    diag = diagnose_dynamic_range(imgs, slot_to_marker, cfg)
    diag.to_csv(os.path.join(out_dir, "channel_diagnostics.csv"),
                index=False, encoding="utf-8-sig")
    report_z_profile(meta.pop("_z_profile", None), out_dir)

    # ---- 4. セグメンテーション ----
    labels, cellprob = segment_nuclei(imgs["DAPI"], cfg)
    if labels.max() == 0:
        print("エラー: 核が 1 つも検出されませんでした。")
        print("  raw_DAPI.png を見て、そもそも核が写っているか確認してください。")
        return None

    # ---- ROI（拡張距離は実寸[µm]で、ボクセルの異方性を考慮して広げる）----
    spacing = voxel_spacing(labels.ndim, um_px, um_z)
    if um_px:
        exp_um = cfg.expansion_um if cfg.expansion_um else cfg.expansion_pixels * um_px
    else:
        exp_um = cfg.expansion_um or float(cfg.expansion_pixels)
    if spacing is not None:
        sp = "×".join(f"{s:.3f}" for s in spacing)
        print(f"-> ROI 拡張: {exp_um:.2f} µm（ボクセル {sp} µm を考慮した等方拡張）")
    else:
        print(f"-> ROI 拡張: {exp_um:.1f} ボクセル"
              f"（ボクセルサイズが不明なため実寸換算できません）")
        if labels.ndim == 3:
            print("   [警告] 3D で z 間隔が不明なため、拡張がボクセル等方になります。")
            print("          z 方向に過剰に広がる可能性があります。"
                  " CONFIG で anisotropy / 画素サイズを確認してください。")
    roi_maps = build_rois(labels, exp_um, spacing)

    # ---- 5. 背景 ----
    areas = np.bincount(labels.ravel())[1:]
    areas = areas[areas > 0]
    med_area = float(np.median(areas))
    if labels.ndim == 3:   # 体積 → 等価球の直径
        nuc_diam = float(2.0 * (3.0 * med_area / (4.0 * np.pi)) ** (1.0 / 3.0))
    else:
        nuc_diam = float(2.0 * np.sqrt(med_area / np.pi))
    scale_note = f"（{nuc_diam * um_px:.1f} µm 相当）" if um_px else ""
    print(f"-> 核の代表直径: {nuc_diam:.1f} px{scale_note}"
          f"／背景推定カーネルはこの {cfg.bg_radius_factor} 倍")

    backgrounds = {slot: estimate_background(im, nuc_diam, cfg) for slot, im in imgs.items()}

    # ---- 6. 特徴量とデブリ判定 ----
    df = measure_objects(labels, imgs["DAPI"], cellprob, backgrounds["DAPI"])
    df = classify_debris(df, imgs, markers, roi_maps, backgrounds, cfg)

    total_cells = int(df["is_cell"].sum())
    if total_cells == 0:
        print("エラー: QC を通過した細胞がありません。qc_* の閾値を緩めてください。")
        return None

    # ---- 7. 陽性判定 ----
    thresholds: dict[str, float] = {}
    enhanced_imgs: dict[str, np.ndarray] = {}
    for m in markers:
        ann = None
        if cfg.bg_mode == "annulus":
            ann = annulus_background(imgs[m.fluorophore], labels, roi_maps[m.roi], cfg)
        df, thr, enh = score_marker(df, m, imgs[m.fluorophore], roi_maps,
                                    backgrounds[m.fluorophore], cfg, ann, um_px)
        thresholds[m.name] = thr
        enhanced_imgs[m.key] = enh

    # ---- 8. 集計 ----
    summary = pd.DataFrame([{
        "Marker": m.name,
        "Fluorophore": m.fluorophore,
        "Pattern": m.resolved_pattern,
        "ROI": m.roi,
        "Total_Cells(DAPI)": total_cells,
        "Positive_Cells": int(df[f"{m.key}_positive"].sum()),
        "Positive_Rate(%)": round(int(df[f"{m.key}_positive"].sum()) / total_cells * 100, 2),
        "Threshold": round(thresholds[m.name], 3),
        "Signal_percentile": m.signal_percentile,
        "Min_positive_fraction": m.min_positive_fraction,
    } for m in markers])

    # ---- 共発現 ----
    acc = df[df["is_cell"]]
    keys = [m.key for m in markers]
    disp = {m.key: m.name for m in markers}
    co_rows = []
    for combo in range(1, 2 ** len(keys)):
        sel = [keys[i] for i in range(len(keys)) if combo >> i & 1]
        mask = np.ones(len(acc), dtype=bool)
        for k in keys:
            v = acc[f"{k}_positive"].to_numpy()
            mask &= v if k in sel else ~v
        cnt = int(mask.sum())
        co_rows.append({
            "Population": " / ".join(f"{disp[k]}+" for k in sel),
            "Cells": cnt,
            "Rate(%)": round(cnt / total_cells * 100, 2),
        })
    neg = int((~acc[[f"{k}_positive" for k in keys]].to_numpy().any(axis=1)).sum())
    co_rows.append({"Population": "すべて陰性", "Cells": neg,
                    "Rate(%)": round(neg / total_cells * 100, 2)})
    coexp = pd.DataFrame(co_rows).sort_values("Cells", ascending=False)

    # ---- 9. 点状マーカーの puncta 定量 ----
    puncta = pd.DataFrame()
    punctate_markers = [m for m in markers if m.resolved_pattern == "punctate"]
    if cfg.puncta_analysis and punctate_markers:
        print("-> 点状マーカーの puncta を定量中...")
        tissue = roi_maps["cell"] > 0     # 解析対象領域＝細胞 ROI の和集合
        rows = [r for r in (measure_puncta(enhanced_imgs[m.key], tissue, m,
                                           total_cells, um_px, um_z, cfg)
                            for m in punctate_markers) if r]
        if rows:
            puncta = pd.DataFrame(rows)
            puncta.to_csv(os.path.join(out_dir, "puncta_summary.csv"),
                          index=False, encoding="utf-8-sig")

    # ---- 10. 出力 ----
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    coexp.to_csv(os.path.join(out_dir, "coexpression.csv"), index=False, encoding="utf-8-sig")
    if cfg.save_per_cell_csv:
        df.to_csv(os.path.join(out_dir, "cells.csv"), index=False, encoding="utf-8-sig")

    try:
        from cellpose import version as cellpose_version
    except Exception:
        cellpose_version = "unknown"
    record = {
        "script": os.path.basename(__file__),
        "panel": [asdict(m) for m in markers],
        "config": {k: v for k, v in asdict(cfg).items() if k != "panel"},
        "acquisition": meta,
        "cellpose_version": str(cellpose_version),
        "cellpose_model": "cpsam (Cellpose-SAM)",
        "thresholds": {k: float(v) for k, v in thresholds.items()},
        "n_objects_detected": int(labels.max()),
        "n_cells_accepted": total_cells,
        "roi_expansion_um": float(exp_um),
        "voxel_spacing_um": list(spacing) if spacing else None,
        "dimensionality": "3D" if labels.ndim == 3 else "2D",
    }
    with open(os.path.join(out_dir, "config_used.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2, default=str)

    if cfg.save_qc_images:
        print("-> QC 画像を出力中...")
        save_qc_images(out_dir, imgs, markers, labels, roi_maps, df, cfg)

    print(f"\n-> 出力先: {out_dir}")
    print("     summary.csv              マーカーごとの陽性率")
    print("     coexpression.csv         共発現の内訳")
    print("     cells.csv                細胞 1 個ごとの全測定値と除外理由")
    print("     channel_diagnostics.csv  各チャンネルの階調利用状況")
    if not puncta.empty:
        print("     puncta_summary.csv       点状マーカーの輝点数と密度")
    print("     config_used.json         パネル・設定・撮像メタ・Cellpose 版数")
    print("     qc_segmentation.png      緑=採用した細胞 / 赤=ゴミとして除外")
    print("     qc_positive_*.png        黄=陽性 / 灰=陰性")
    print("     raw_*.png                LUT を経由しない素の入力画像")

    return {"summary": summary, "coexpression": coexp, "cells": df,
            "diagnostics": diag, "puncta": puncta}


# =====================================================================
# 14. 複数シーン（Position）をまとめて処理する
# =====================================================================

def analyze_all_scenes(cfg: Config) -> dict[str, pd.DataFrame] | None:
    """
    .czi に含まれる全シーン（Position）を 1 つずつ処理し、最後にプールする。

    巨大な結合画像を 1 枚作って解析するより、1 視野ずつ回して最後に足す方が
    実装も座標管理も素直で、メモリも読める。
    工場のラインと同じで、1 ステーション 1 仕事にしておくと詰まった場所が分かる。

    各シーンの出力は <出力先>/scene00/, scene01/ … に入り、
    プール結果が <出力先>/pooled_summary.csv などにまとまる。
    """
    n = count_czi_scenes(cfg.czi_path)
    base_out = cfg.output_dir or os.path.join(
        os.path.dirname(cfg.czi_path),
        f"{os.path.splitext(os.path.basename(cfg.czi_path))[0]}_results_9th")
    os.makedirs(base_out, exist_ok=True)
    print(f"-> 全 {n} シーンを順に処理します（出力先: {base_out}）")

    per_scene, cells_all, puncta_all = [], [], []
    for s in range(n):
        print(f"\n{'=' * 60}\nシーン {s} / {n - 1}\n{'=' * 60}")
        sub = Config(**{**asdict(cfg), "panel": None})
        sub.panel = cfg.panel
        sub.czi_scene = s
        sub.output_dir = os.path.join(base_out, f"scene{s:02d}")
        try:
            res = analyze(sub)
        except Exception as exc:                 # 1 シーンの失敗で全体を止めない
            print(f"   [エラー] シーン {s} の解析に失敗しました: {exc}")
            continue
        if res is None:
            print(f"   [スキップ] シーン {s} からは細胞が得られませんでした")
            continue
        sm = res["summary"].copy(); sm.insert(0, "Scene", s); per_scene.append(sm)
        cl = res["cells"].copy(); cl.insert(0, "Scene", s); cells_all.append(cl)
        if not res["puncta"].empty:
            pc = res["puncta"].copy(); pc.insert(0, "Scene", s); puncta_all.append(pc)

    if not per_scene:
        print("エラー: どのシーンからも結果が得られませんでした。")
        return None

    by_scene = pd.concat(per_scene, ignore_index=True)
    cells = pd.concat(cells_all, ignore_index=True)

    # プール：シーンごとの率を平均するのではなく、細胞数を足してから率を出す。
    # 視野ごとに細胞数が違うので、率の単純平均だと細胞の少ない視野が過大評価される。
    pooled = (by_scene.groupby(["Marker", "Fluorophore", "Pattern", "ROI"], as_index=False)
              .agg(Scenes=("Scene", "nunique"),
                   Total_Cells=("Total_Cells(DAPI)", "sum"),
                   Positive_Cells=("Positive_Cells", "sum"),
                   Rate_mean_of_scenes=("Positive_Rate(%)", "mean"),
                   Rate_sd_of_scenes=("Positive_Rate(%)", "std")))
    pooled["Positive_Rate(%)"] = (pooled["Positive_Cells"] /
                                  pooled["Total_Cells"] * 100).round(2)
    pooled["Rate_mean_of_scenes"] = pooled["Rate_mean_of_scenes"].round(2)
    pooled["Rate_sd_of_scenes"] = pooled["Rate_sd_of_scenes"].round(2)

    by_scene.to_csv(os.path.join(base_out, "per_scene_summary.csv"),
                    index=False, encoding="utf-8-sig")
    pooled.to_csv(os.path.join(base_out, "pooled_summary.csv"),
                  index=False, encoding="utf-8-sig")
    cells.to_csv(os.path.join(base_out, "pooled_cells.csv"),
                 index=False, encoding="utf-8-sig")
    puncta = pd.concat(puncta_all, ignore_index=True) if puncta_all else pd.DataFrame()
    if not puncta.empty:
        puncta.to_csv(os.path.join(base_out, "pooled_puncta.csv"),
                      index=False, encoding="utf-8-sig")

    print(f"\n-> プール結果: {base_out}")
    print("     per_scene_summary.csv  シーンごとの陽性率")
    print("     pooled_summary.csv     全シーンを合算した陽性率（率の平均ではなく細胞数の合計から算出）")
    print("     pooled_cells.csv       全シーンの細胞 1 個ごとの測定値（Scene 列付き）")
    return {"summary": pooled, "per_scene": by_scene, "cells": cells,
            "coexpression": pd.DataFrame(), "puncta": puncta, "diagnostics": pd.DataFrame()}


# =====================================================================
# 14b. 起動前の確認（第9版の追加分）
# =====================================================================

def check_czi_reader() -> None:
    """
    .czi を読むライブラリがあるかを起動時に確かめる。

    第8版もリーダ層では正しく分岐していたが、依存が無いと気づくのが
    解析の途中だった。読み込みに入る前に、入れ方ごと知らせる。
    """
    for mod in ("czifile", "bioio"):
        try:
            __import__(mod)
            return
        except ImportError:
            continue
    raise SystemExit(
        "\n.czi を読むライブラリが見つかりません。次のどちらかを入れてください:\n"
        "    pip install czifile\n"
        "    pip install bioio bioio-czi\n\n"
        "PNG で解析する場合は CONFIG.input_mode='images' に切り替えてください。\n")


# よくある置き場所。ここを順に探す。
def _czi_search_dirs() -> list[str]:
    home = os.path.expanduser("~")
    return [
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "デスクトップ"),
        os.path.abspath(os.sep),
    ]


def resolve_czi_path(path: str) -> str:
    """
    設定された .czi が見つからないとき、よくある置き場所を探して知らせる。

    第8版は既定パスを直書きしていたので、ファイルを別のフォルダへ移すだけで
    FileNotFoundError で止まった。ファイルは消えていないのに止まるのは不親切なので、
    探した場所と見つかった候補を必ず表示する。
    候補が 1 つだけならそれを採用し、複数なら選ばせる（黙って選ばない）。
    """
    if path and os.path.exists(path):
        return path

    if path:
        print(f"-> 設定された .czi が見つかりません: {path}")
    print("   よくある置き場所を探します...")

    seen: set[str] = set()
    found: list[str] = []
    for d in _czi_search_dirs():
        rd = os.path.realpath(d)
        if rd in seen or not os.path.isdir(rd):
            continue
        seen.add(rd)
        try:
            names = sorted(os.listdir(rd))
        except OSError:
            continue
        for nm in names:
            if nm.lower().endswith(".czi"):
                full = os.path.join(rd, nm)
                if full not in found:
                    found.append(full)

    if not found:
        raise SystemExit(
            "\n.czi が見つかりませんでした。探した場所:\n"
            + "".join(f"    {d}\n" for d in seen)
            + "\n--czi でパスを直接指定してください:\n"
              '    python run_analysis_9th.py --czi "D:\\data\\sample.czi"\n')

    if len(found) == 1:
        print(f"   見つかりました: {found[0]}")
        return found[0]

    raise SystemExit(
        "\n複数の .czi が見つかりました。--czi でどれを解析するか指定してください:\n"
        + "".join(f"    {p}\n" for p in found))


# =====================================================================
# 15. CLI
# =====================================================================

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="蛍光免疫染色の細胞数・陽性率解析（第9版）")
    ap.add_argument("--list-channels", metavar="CZI",
                    help=".czi のチャンネル構成・シーン数・色素スロット判定を表示して終了")
    ap.add_argument("--czi", metavar="PATH", help="解析する .czi（CONFIG より優先）")
    ap.add_argument("--panel", metavar="NAME",
                    help=f"使うパネル {list(PANELS)}（CONFIG より優先）")
    ap.add_argument("--out", metavar="DIR", help="出力先ディレクトリ")
    ap.add_argument("--3d", dest="three_d", action="store_true",
                    help="Z を潰さず真の 3D セグメンテーションを行う"
                         "（z_reduce='none' + use_3d=True）")
    ap.add_argument("--scene", metavar="N", type=int,
                    help="解析するシーン（Position）の番号。既定 0")
    ap.add_argument("--all-scenes", action="store_true",
                    help="全シーンを順に処理し、最後にプールして集計する")
    ap.add_argument("--nucleus-diameter-um", metavar="UM", type=float,
                    dest="nuc_um",
                    help="核の想定直径[µm]を明示する。省略すると Cellpose に推定させる。"
                         "検出核が小さすぎる件の検証用（例: 7.0）")
    args = ap.parse_args(argv)

    check_czi_reader()

    if args.list_channels:
        describe_czi(resolve_czi_path(args.list_channels))
        return 0

    cfg = CONFIG
    if args.czi:
        cfg.czi_path, cfg.input_mode = args.czi, "czi"
    if args.panel:
        cfg.active_panel, cfg.panel = args.panel, None
    if args.out:
        cfg.output_dir = args.out
    if args.nuc_um is not None:
        cfg.nucleus_diameter_um = args.nuc_um
    if args.three_d:
        cfg.use_3d, cfg.z_reduce = True, "none"
    if args.scene is not None:
        cfg.czi_scene = args.scene

    # 本解析の経路でもパスを解決する（--list-channels だけでは足りない）。
    if cfg.input_mode == "czi":
        cfg.czi_path = resolve_czi_path(cfg.czi_path)

    print("--- 蛍光免疫染色 解析（第9版） ---")
    res = analyze_all_scenes(cfg) if args.all_scenes else analyze(cfg)
    if res is None:
        return 1

    print("\n--- 解析結果 ---")
    print(res["summary"].to_string(index=False))
    if not res["coexpression"].empty:
        print("\n--- 共発現 ---")
        print(res["coexpression"].to_string(index=False))
    if not res["puncta"].empty:
        print("\n--- 点状マーカーの puncta 定量 ---")
        print(res["puncta"].to_string(index=False))
        print("  ※ 点状マーカーは『陽性細胞率』より『単位面積（体積）あたりの輝点数』が"
              "標準的な readout です。")
        print("     シナプスは突起の上にあり、どの細胞のものか帰属できないためです。")

    print("\n[確認のお願い]")
    print("  1) qc_segmentation.png を必ず目視してください。")
    print("     赤で囲まれた「ゴミ」に本物の細胞が混ざっていたら qc_* の閾値を緩め、")
    print("     緑の中にゴミが残っていたら閾値を厳しくしてください。")
    print("  2) qc_positive_*.png で、黄色（陽性）が納得できる細胞に付いているか見てください。")
    print("     特に新しいマーカーを追加した直後は、pattern の自動判定が妥当か必ず確認を。")
    print("  3) channel_diagnostics.csv で階調の利用率を確認してください。")
    print("     狭い場合、陽性率は暫定値です。次回の撮像を 16bit ＋ 高ゲインにしてください。")
    print("  4) 3D で解析した場合は z_profile.csv も見てください。")
    print("     深部ほど暗いなら、陽性判定に z 依存のバイアスが乗っています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
