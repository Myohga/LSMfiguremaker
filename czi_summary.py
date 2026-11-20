# -*- coding: utf-8 -*-
r"""
czi_summary.py
==============
「pptx データまとめ」モードのエンジン。

Nega（陰性対照 noAb）の .czi から各抗体チャンネルの表示 White（白飛び）しきい値を
客観的に決め、その White を実験画像に当てて 7 パネルを 1 枚のスライドにまとめる。

  段階 2（このファイルの現状）：White しきい値の計算と、Nega/実験画像の整合チェック。
  段階 3 以降：7 パネルの描画と、参考 pptx をテンプレートにした書き出し。

.czi の読み込み・チャンネルの判定（名前と発光波長でスロット AF488/AF555/AF647/DAPI を決める）は
czi_figure_core（＝ run_analysis_9th.py を無改変で利用）をそのまま使う。

    python czi_summary.py --nega "Nega.czi" [--exp "実験.czi"]
"""
from __future__ import annotations

import os
import sys

import numpy as np

import czi_figure_core as core

# 抗体チャンネル（パネルに使うもの）。Hoechst（DAPI）と透過光はここでは使わない。
ANTIBODY_SLOTS = ("AF488", "AF555", "AF647")
# White(%) の目標：その画像で「White より明るい画素」が全体の何 % になるか。
# ZEN の Best Fit と同じ考え方で、既定は ZEN で使っている設定（White 0.25 %）に合わせる。
# 実験画像で ZEN の Best Fit（0.25 %）と照合済み：ZEN 37272/3819/9763 に対し 37230/3747/9582。
WHITE_TARGET_PERCENT = 0.25
WHITE_TARGET_FRACTION = WHITE_TARGET_PERCENT / 100.0
# 実際の割合が目標からこれ以上ずれたら警告（相対）
WHITE_WARN_RELATIVE = 0.10


def channel_index(data: core.CziData, slot: str) -> int | None:
    """スロット名（AF488 など）から C 番号を引く。プレーン順には依存しない。"""
    return data.slots.index(slot) if slot in data.slots else None


def bit_max(path: str, data: core.CziData, c: int) -> int:
    """そのチャンネルの最大値（BitCountRange があればそれ、無ければ配列の型の最大値）。"""
    for z in core.read_zen_display(path):
        if z["index"] == c and z.get("bits"):
            return int(2 ** z["bits"] - 1)
    dt = data.planes.dtype
    return int(np.iinfo(dt).max) if np.issubdtype(dt, np.integer) else int(data.planes[c].max())


def white_threshold(plane: np.ndarray, maxval: int = 65535,
                    target: float = WHITE_TARGET_FRACTION) -> dict:
    """
    「V より明るい画素の割合」が target に最も近い整数 V（0..maxval）を返す。

    度数分布を 1 回数えて、全ての V について割合を一度に出す（並べ替え不要・厳密）。
    割合は V が大きいほど小さくなる階段状なので、同じ近さの V が並んだら一番小さい V を採る
    （np.argmin は最初の最小値を返す）＝保守的。
    飽和画素（maxval）だけで target を超えると、どの V でも target ちょうどにはできない。
    そのときも一番近い V を採り、警告を付ける。
    """
    a = np.asarray(plane).ravel()
    if a.min() < 0 or a.max() > maxval:
        raise ValueError(f"画素値が 0〜{maxval} の範囲外です（{a.min()}〜{a.max()}）")
    n = a.size
    counts = np.bincount(a.astype(np.int64), minlength=maxval + 1)
    above = n - np.cumsum(counts)                 # above[V] = V より明るい画素の数
    frac = above / n
    V = int(np.argmin(np.abs(frac - target)))
    saturated = counts[maxval] / n
    rel = abs(frac[V] - target) / target
    warn = None
    if saturated > target:
        warn = (f"飽和画素（{maxval}）が {saturated * 100:.4f} % あり、目標 {target * 100:.2f} % まで"
                f"下げられません。実際の White(%) は {frac[V] * 100:.4f} % です。")
    elif rel > WHITE_WARN_RELATIVE:
        warn = (f"実際の White(%) が {frac[V] * 100:.4f} % で、目標 {target * 100:.2f} % から"
                f" {rel * 100:.0f} % ずれています（画素値の分布が粗いため）。")
    return {"V": V, "fraction": float(frac[V]), "saturated": float(saturated),
            "max": int(a.max()), "maxval": maxval, "warn": warn}


_WHITE_CACHE: dict[tuple, dict] = {}


def image_whites(path: str, slots=ANTIBODY_SLOTS, label: str = "Nega",
                 percent: float = WHITE_TARGET_PERCENT) -> tuple[dict[str, dict], list[str]]:
    """
    .czi の各抗体チャンネルで White（上位 percent % ルール）を求める。({slot: 結果}, 警告のリスト)
    Nega にも実験画像にも同じ計算を使う。結果はファイルの更新時刻ごとに覚えておく（画面で何度切り替えても速い）。
    """
    key0 = (os.path.abspath(path), os.path.getmtime(path), float(percent))
    out, warns, data = {}, [], None
    for slot in slots:
        key = key0 + (slot,)
        if key not in _WHITE_CACHE:
            data = data or core.load_czi(path)
            c = channel_index(data, slot)
            if c is None:
                _WHITE_CACHE[key] = None
            else:
                r = white_threshold(data.planes[c], bit_max(path, data, c), percent / 100.0)
                r.update(index=c, name=data.chans[c].get("name", ""))
                _WHITE_CACHE[key] = r
        r = _WHITE_CACHE[key]
        if r is None:
            warns.append(f"{label} に {slot} のチャンネルがありません。")
            continue
        out[slot] = dict(r)
        if r["warn"]:
            warns.append(f"{slot}（{label}）: {r['warn']}")
    return out, warns


def nega_whites(path: str, slots=ANTIBODY_SLOTS, percent: float = WHITE_TARGET_PERCENT
                ) -> tuple[dict[str, dict], list[str]]:
    """Nega の .czi から各抗体チャンネルの White を求める。({slot: 結果}, 警告のリスト)"""
    return image_whites(path, slots, "Nega", percent)


# White の決め方：抗体（スロット）ごとに "nega"（Nega から）か "exp"（実験画像から）
SOURCE_LABELS = {"nega": "Nega から", "exp": "実験画像から"}


def compute_whites(nega_path: str, exp_path: str, sources: dict[str, str] | None = None,
                   slots=ANTIBODY_SLOTS, percent: float = WHITE_TARGET_PERCENT
                   ) -> tuple[dict[str, dict], list[str]]:
    """
    各抗体の White を、指定された元画像（既定は全部 Nega）で求める。
    戻り値の各結果には "source"（"nega"/"exp"）が付く。警告は使う方の画像のものだけを返す。
    """
    sources = {s: (sources or {}).get(s, "nega") for s in slots}
    out, warns = {}, []
    for src, path, label in (("nega", nega_path, "Nega"), ("exp", exp_path, "実験画像")):
        want = [s for s in slots if sources[s] == src]
        if not want:
            continue
        res, w = image_whites(path, want, label, percent)
        for s, r in res.items():
            r["source"] = src
            out[s] = r
        warns += w
    return out, warns


def check_pair(nega_path: str, exp_path: str, slots=ANTIBODY_SLOTS) -> list[str]:
    """Nega と実験画像が同じ撮像条件・同じチャンネル構成かを確かめ、食い違いを警告で返す。"""
    n, e = core.load_czi(nega_path), None
    n_slots = {s: channel_index(n, s) for s in slots}
    n_bits = {s: bit_max(nega_path, n, c) for s, c in n_slots.items() if c is not None}
    n_shape, n_um, n_dtype = n.planes.shape[1:], n.um_px, n.planes.dtype
    e = core.load_czi(exp_path)
    warns = []
    for s in slots:
        ce = channel_index(e, s)
        if ce is None and n_slots[s] is not None:
            warns.append(f"実験画像に {s} がありません（Nega にはあります）。")
        elif ce is not None and n_slots[s] is None:
            warns.append(f"Nega に {s} がありません（実験画像にはあります）。")
        elif ce is not None:
            be = bit_max(exp_path, e, ce)
            if be != n_bits[s]:
                warns.append(f"{s} のビット深度が違います（Nega {n_bits[s]} / 実験 {be}）。")
    if e.planes.dtype != n_dtype:
        warns.append(f"画素の型が違います（Nega {n_dtype} / 実験 {e.planes.dtype}）。")
    if e.planes.shape[1:] != n_shape:
        warns.append(f"画像サイズが違います（Nega {n_shape} / 実験 {e.planes.shape[1:]}）。")
    if n_um and e.um_px and abs(n_um - e.um_px) / n_um > 0.001:
        warns.append(f"画素サイズが違います（Nega {n_um:.5f} / 実験 {e.um_px:.5f} µm/px）。")
    return warns


# =====================================================================
# 段階 3：7 パネルの描画と、参考 pptx をテンプレートにした書き出し
# =====================================================================
# 色（参考 pptx 準拠。変えたいときはここだけ）。DAPI は AF555 の青と混ざらないよう白（グレー）で表示する
SUMMARY_COLORS = {"AF488": "#00CD29", "AF555": "#0000FF", "AF647": "#FF0014", "DAPI": "gray"}
SUMMARY_BLEND = "screen"            # 重なりの合成：screen（既定）/ add / max
SCALEBAR_UM = 50.0
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates",
                             "summary_template.pptx")
# 7 パネル：テンプレート上のグループの位置（左端 cm・上段/下段）と、合成するチャンネル（タイトルの並び順）
PANELS = (
    ((5.49, "top"), ("AF488", "AF555", "AF647")),
    ((12.89, "top"), ("AF488",)),
    ((20.19, "top"), ("AF555",)),
    ((27.48, "top"), ("AF647",)),
    ((9.38, "bottom"), ("AF488", "AF647")),
    ((16.62, "bottom"), ("AF488", "AF555")),
    ((23.87, "bottom"), ("AF555", "AF647")),
)
# DAPI を入れるとき：下段を上段と同じ 4 列にそろえ、右端に DAPI の単染色を足す
DAPI_PANELS = (
    ((5.49, "top"), ("AF488", "AF555", "AF647")),
    ((12.89, "top"), ("AF488",)),
    ((20.19, "top"), ("AF555",)),
    ((27.48, "top"), ("AF647",)),
    ((5.49, "bottom"), ("AF488", "AF647")),
    ((12.89, "bottom"), ("AF488", "AF555")),
    ((20.19, "bottom"), ("AF555", "AF647")),
    ((27.48, "bottom"), ("DAPI",)),
)
EMU_PER_CM = 360000


def title_hex(color: str) -> str:
    """タイトル文字の色（#RRGGBB）。#RRGGBB はそのまま、色名（DAPI の gray など）は読める色に直す。"""
    if core.parse_hex(color):
        return "#{:02X}{:02X}{:02X}".format(*core.parse_hex(color))
    return "#{:02X}{:02X}{:02X}".format(*core.text_rgb(color))


def active_slots(dapi: bool) -> tuple[str, ...]:
    return ANTIBODY_SLOTS + (("DAPI",) if dapi else ())


def panel_layout(dapi: bool):
    return DAPI_PANELS if dapi else PANELS


def panel_config(exp_path: str, slots, whites: dict[str, int], names: dict[str, str],
                 colors=None, blend: str = SUMMARY_BLEND) -> dict:
    """
    既存エンジンの設定 dict を作る：指定スロットだけ ON、Black=0・White=その値・ガンマ 1・各色。
    これを core.composite_rgb に渡すと、out = clip(pixel / White) × 色 を screen 合成した画像になる。
    """
    colors = colors or SUMMARY_COLORS
    cfg = core.default_config(exp_path)
    chans = []
    for slot in slots:
        ch = next(c for c in cfg["channels"] if c.get("slot") == slot)
        ch.update(enabled=True, name=names.get(slot, slot), color=colors[slot],
                  range_mode="absolute", low=0, high=int(whites[slot]), gamma=1.0)
        chans.append(ch)
    cfg["channels"] = chans                      # 並び順＝タイトルの並び順
    cfg["blend"] = blend
    cfg["colorblind_magenta"] = False
    return cfg


def render_panel_image(data: core.CziData, cfg: dict):
    """注釈なしの正方形 RGB 画像（PIL）。描画は既存の composite_rgb をそのまま使う。"""
    from PIL import Image
    return Image.fromarray(core.composite_rgb(data, cfg), "RGB")


def _find_groups(slide, panels=PANELS) -> dict[tuple[float, str], object]:
    """パネルのグループを（左端 cm, 上段/下段）で引けるようにする（名前や文字に頼らない）。"""
    groups = [sh for sh in slide.shapes if sh.shape_type == 6]
    out = {}
    for key, _ in panels:
        left, row = key
        cands = [g for g in groups if (g.top / EMU_PER_CM < 5) == (row == "top")]
        g = min(cands, key=lambda g: abs(g.left / EMU_PER_CM - left))
        if abs(g.left / EMU_PER_CM - left) > 0.5:
            raise ValueError(f"テンプレートに {row} 段 {left} cm のパネルが見つかりません。")
        out[key] = g
    return out


def _clone_group(slide, group):
    """グループ（パネル 1 つ分）を同じスライドに複製する。図形の番号（id）は重ならないよう振り直す。"""
    import copy
    import re as _re
    from pptx.oxml.ns import qn
    tree = slide.shapes._spTree
    next_id = max(int(x) for x in _re.findall(r'<p:cNvPr id="(\d+)"', tree.xml)) + 1
    el = copy.deepcopy(group._element)
    for c in el.iter(qn("p:cNvPr")):
        c.set("id", str(next_id))
        next_id += 1
    tree.append(el)
    return slide.shapes[-1]


def _apply_dapi_layout(slide) -> None:
    """
    テンプレートを DAPI ありの配置に組み替える（2 枚目を複製する前に 1 回だけ）：
      ・下段 3 パネルを上段と同じ列（5.49 / 12.89 / 20.19 cm）へ動かし、27.48 cm に DAPI のパネルを足す
      ・左下の White の枠を、下段 1 列目と重ならない幅（左端〜5.2 cm）に詰め、DAPI の行を足す
    """
    import copy
    from pptx.oxml.ns import qn
    from pptx.util import Pt
    cm = lambda v: int(round(v * EMU_PER_CM))          # noqa: E731
    g = _find_groups(slide, PANELS)
    bottom_top = g[(9.38, "bottom")].top
    for old, new in (((9.38, "bottom"), 5.49), ((16.62, "bottom"), 12.89), ((23.87, "bottom"), 20.19)):
        g[old].left = cm(new)
    dapi = _clone_group(slide, g[(27.48, "top")])
    dapi.left, dapi.top = cm(27.48), bottom_top

    for sh in slide.shapes:
        if sh.shape_type == 6:
            continue
        text = sh.text_frame.text.strip() if sh.has_text_frame else ""
        if "における" in text and "White" in text:           # 見出し：「○○における」で改行して 2 行に
            sh.left = cm(0.6)
            runs = sh.text_frame.paragraphs[0].runs
            for r in runs:                                  # 下段 1 列目（5.49 cm〜）に掛からない大きさ
                r.font.size = Pt(16)
            mid = next((r for r in runs if "における" in r.text), None)
            if mid is not None:
                mid._r.addnext(mid._r.makeelement(qn("a:br"), {}))
        elif text.startswith("AF488:"):                     # ラベル：DAPI の行を足し、少し小さく
            sh.left, sh.top = cm(0.85), cm(10.45)
            p = sh.text_frame.paragraphs[-1]._p
            new = copy.deepcopy(p)
            p.addnext(new)
            sh.text_frame.paragraphs[-1].runs[0].text = "DAPI:"
            for extra in sh.text_frame.paragraphs[-1].runs[1:]:
                extra._r.getparent().remove(extra._r)
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    r.font.size = Pt(16)
        elif text and all(t.strip().isdigit() for t in text.split("\n")):   # 値：行を 1 つ足し、少し小さく
            sh.left, sh.top = cm(2.95), cm(10.45)
            p = sh.text_frame.paragraphs[-1]._p
            p.addnext(copy.deepcopy(p))
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    r.font.size = Pt(16)
        elif not text and sh.width < cm(8) and cm(8) < sh.top < cm(10.5):  # 枠
            sh.left, sh.top, sh.width, sh.height = cm(0.6), cm(10.2), cm(4.6), cm(5.0)


def _child(group, name: str):
    for sh in group.shapes:
        if sh.name == name:
            return sh
    raise ValueError(f"テンプレートのグループに「{name}」がありません。")


def _replace_picture(slide, pic, img) -> None:
    """図形の位置・大きさはそのまま、参照している画像データだけを差し替える（古い画像は削除）。"""
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from pptx.oxml.ns import qn
    old = pic._element.blipFill.blip.rEmbed
    _part, rid = slide.part.get_or_add_image_part(buf)
    pic._element.blipFill.blip.rEmbed = rid
    # 古い画像を、もうどの図形も使っていなければ外す（外した画像は保存されない）。
    # python-pptx の drop_rel は画像の参照（r:embed）を数えないので、ここで自分で数える
    # （テンプレートの 7 枚が同じ見本画像を共有していても、最後の 1 枚を差し替えるまで残す）。
    still_used = any(b.get(qn("r:embed")) == old for b in slide._element.iter(qn("a:blip")))
    if old != rid and not still_used and old in slide.part.rels:
        slide.part.rels.pop(old)


def _set_runs(paragraph, segments) -> None:
    """段落の文字を [(文字, '#RRGGBB'), …] に置き換える。太字・大きさ・フォントは元の 1 つ目の run を引き継ぐ。"""
    import copy
    from pptx.dml.color import RGBColor
    runs = paragraph.runs
    proto = copy.deepcopy(runs[0]._r.rPr) if runs and runs[0]._r.rPr is not None else None
    for r in runs:
        paragraph._p.remove(r._r)
    for text, color in segments:
        r = paragraph.add_run()
        if proto is not None:
            r._r.insert(0, copy.deepcopy(proto))
        r.text = text
        if color:
            r.font.color.rgb = RGBColor.from_string(color.lstrip("#").upper())


def _set_text_keep_format(shape, lines: list[str]) -> None:
    """テキストボックスの各段落の文字だけを差し替える（書式は残す）。"""
    paras = shape.text_frame.paragraphs
    for p, text in zip(paras, lines):
        _set_runs(p, [(text, None)])


def _fit_scalebar(group, um: float, um_px: float, img_px: int) -> None:
    """スケールバーの幅を「µm ÷ µm/px」から求め直す（右端は固定）。文字もバーの真上にそろえる。"""
    pic, bar, txt = _child(group, "画像"), _child(group, "スケールバー"), _child(group, "スケールバー文字")
    right = bar.left + bar.width
    width = int(round(um / um_px / img_px * pic.width))
    bar.left, bar.width = right - width, width
    txt.left, txt.width = bar.left, width
    _set_text_keep_format(txt, [f"{um:g} µm"])


def _duplicate_slide(prs, src):
    """
    スライドを複製して末尾に足す（同じレイアウト・同じ図形）。
    図形の XML をそのまま写すと、画像の参照番号（rId）は元のスライドのものが残る。
    新しいスライドでは同じ番号が別の画像に割り当てられて取り違えが起きるので、
    画像ごとに新しいスライド側の参照を作り直して付け替える。
    """
    import copy
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.oxml.ns import qn
    new = prs.slides.add_slide(src.slide_layout)
    for ph in list(new.placeholders):                # レイアウトが勝手に足すプレースホルダーは消す
        ph._element.getparent().remove(ph._element)
    tree = new.shapes._spTree
    for el in src.shapes._spTree.iterchildren():
        if el.tag.endswith("}nvGrpSpPr") or el.tag.endswith("}grpSpPr"):
            continue
        tree.append(copy.deepcopy(el))
    for blip in tree.iter(qn("a:blip")):
        old = blip.get(qn("r:embed"))
        if old:
            blip.set(qn("r:embed"), new.part.relate_to(src.part.related_part(old), RT.IMAGE))
    return new


def _add_source_note(slide, date_box, lines: list[tuple[str, float]]) -> None:
    """日付の下に、どの画像で White を決めたかの説明を足す。lines = [(文字, 大きさ pt), …]"""
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    left = date_box.left
    top = date_box.top + date_box.height + int(0.05 * EMU_PER_CM)
    tb = slide.shapes.add_textbox(left, top, int(4.5 * EMU_PER_CM), int(2.0 * EMU_PER_CM))
    tb.name = "White の決め方"
    tf = tb.text_frame
    tf.word_wrap = True
    for k, (text, size) in enumerate(lines):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        if k == 0:
            r.font.bold = True
        elif k >= 2:
            r.font.color.rgb = RGBColor(0x59, 0x59, 0x59)


def _fill_slide(slide, data: core.CziData, exp_path: str, whites: dict[str, int],
                names: dict[str, str], colors, blend: str, scalebar_um: float,
                comment: str, date: str, heading: str, source_note=None, dapi: bool = False) -> None:
    """1 枚分：パネルの画像・タイトル・スケールバー、日付、White の枠（見出しと値）、コメント。"""
    import re as _re
    panels = panel_layout(dapi)
    groups = _find_groups(slide, panels)
    for key, slots in panels:
        g = groups[key]
        img = render_panel_image(data, panel_config(exp_path, slots, whites, names, colors, blend))
        _replace_picture(slide, _child(g, "画像"), img)
        segs = []
        for s in slots:
            if segs:
                segs.append((" / ", "#000000"))
            segs.append((names.get(s, s), title_hex(colors[s])))
        _set_runs(_child(g, "タイトル文字").text_frame.paragraphs[0], segs)
        if data.um_px:
            _fit_scalebar(g, scalebar_um, data.um_px, img.width)

    for sh in list(slide.shapes):
        if sh.shape_type == 6 or not sh.has_text_frame:
            continue
        text = sh.text_frame.text.strip()
        if _re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text):
            _set_text_keep_format(sh, [date])
            if source_note:
                _add_source_note(slide, sh, source_note)
        elif "における" in text and "White" in text:                 # 枠の見出し「○○におけるWhite」
            runs = sh.text_frame.paragraphs[0].runs
            head = next((r for r in runs if "Nega" in r.text or "実験画像" in r.text), None)
            if head is not None:
                head.text = heading
        elif _re.fullmatch(r"\d+(\s*\n\s*\d+){2,3}", text):          # White の値の欄（3 行、DAPI ありは 4 行）
            _set_text_keep_format(sh, [str(whites[s]) for s in active_slots(dapi)])
        elif text == "" and sh.width / EMU_PER_CM > 20:              # 下の横長のコメント枠
            if comment:
                sh.text_frame.text = comment


# 2 枚の構成：(White を決める画像, 枠の見出しに入れる語)
SLIDES = (("exp", "実験画像"), ("nega", "Nega"))


def build_summary(nega_path: str | None, exp_path: str, names: dict[str, str], out_path: str,
                  template: str = TEMPLATE_PATH, colors=None, blend: str = SUMMARY_BLEND,
                  scalebar_um: float = SCALEBAR_UM, comment: str = "",
                  date: str | None = None, percent: float = WHITE_TARGET_PERCENT,
                  nega_slide: bool = True, dapi: bool = False) -> dict:
    """
    まとめ pptx を作って保存する（どのスライドも実験画像を表示し、White の決め方だけが違う）。
      1 枚目：White を実験画像から決める
      2 枚目（nega_slide=True のとき）：White を Nega から決める。日付の下に Nega を使ったことを書く
    dapi=True で DAPI（Hoechst）の単染色パネルを下段右端に足し、下段を 4 列にそろえる。
    戻り値：{"slides": [{"source", "whites", "details"}, …], "warnings": [...], "path": out_path}
    """
    import datetime as _dt
    from pptx import Presentation

    if nega_slide and not nega_path:
        raise ValueError("2 枚目（Nega 基準）を作るには Nega の .czi が必要です。")
    colors = colors or SUMMARY_COLORS
    slots = active_slots(dapi)
    date = date or _dt.date.today().strftime("%Y/%m/%d")
    plan = SLIDES if nega_slide else SLIDES[:1]
    warns = check_pair(nega_path, exp_path, slots) if nega_path else []
    per_slide = []
    for src, _heading in plan:
        full, w = compute_whites(nega_path, exp_path, {s: src for s in slots}, slots=slots,
                                 percent=percent)
        missing = [s for s in slots if s not in full]
        if missing:
            raise ValueError(f"{missing} の White を決められません（チャンネルがありません）。")
        per_slide.append({"source": src, "details": full, "whites": {s: full[s]["V"] for s in slots}})
        warns += w

    data = core.load_czi(exp_path)
    if not data.um_px:
        warns.append("実験画像に µm/px が記録されていないため、スケールバーの長さはテンプレートのままです。")
    prs = Presentation(template)
    if dapi:
        _apply_dapi_layout(prs.slides[0])                  # 配置の組み替えは複製の前に 1 回だけ
    slides = [prs.slides[0]]
    if nega_slide:
        slides.append(_duplicate_slide(prs, prs.slides[0]))  # 書き込む前に複製する

    for slide, info, (src, heading) in zip(slides, per_slide, plan):
        note = None
        if src == "nega":
            # 日付の下の幅（約 4.5 cm）で単語の途中で折り返さない長さに分ける
            note = [("Nega 基準", 16), ("White を Nega から設定", 10),
                    (f"Nega: {os.path.basename(nega_path)}", 9)]
        _fill_slide(slide, data, exp_path, info["whites"], names, colors, blend, scalebar_um,
                    comment, date, heading, note, dapi)
        label = SOURCE_LABELS[src]
        notes = [f"White の決め方: {label}（その画像で White より明るい画素が "
                 f"{percent:g} % に最も近い整数。ZEN の Best Fit の White(%) に相当）",
                 f"表示している画像: 実験画像 {os.path.basename(exp_path)}"]
        if nega_path:
            notes.append(f"Nega: {os.path.basename(nega_path)}")
        notes.append("表示: Black = 0, ガンマ 1.0, 合成 = " + blend)
        for s in slots:
            r = info["details"][s]
            notes.append(f"{s} ({names.get(s, s)}): White {r['V']}（実際 {r['fraction'] * 100:.4f} %）色 {colors[s]}")
        if data.um_px:
            notes.append(f"スケールバー: {scalebar_um:g} µm（{data.um_px:.5f} µm/px）")
        notes += ["[警告] " + w for w in warns]
        slide.notes_slide.notes_text_frame.text = "\n".join(notes)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    prs.save(out_path)
    return {"slides": per_slide, "warnings": warns, "path": out_path}


def render_preview(exp_path: str, whites: dict[str, int], names: dict[str, str],
                   colors=None, blend: str = SUMMARY_BLEND, size: int = 220, dapi: bool = False):
    """画面確認用：パネルをスライドと同じ並び（上 4・下 3、DAPI ありは下も 4）で 1 枚の小さな画像にする。"""
    from PIL import Image, ImageDraw
    colors = colors or SUMMARY_COLORS
    data = core.load_czi(exp_path)
    pad, head = 10, 22
    W = 4 * size + 5 * pad
    H = 2 * (size + head) + 3 * pad
    out = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(out)
    font = core.get_font(14, "".join(names.values()))
    pos_top = [pad + i * (size + pad) for i in range(4)]
    pos_bot = pos_top if dapi else [pad + size // 2 + pad // 2 + i * (size + pad) for i in range(3)]
    for i, (key, slots) in enumerate(panel_layout(dapi)):
        x = pos_top[i] if i < 4 else pos_bot[i - 4]
        y = pad if i < 4 else 2 * pad + size + head
        img = render_panel_image(data, panel_config(exp_path, slots, whites, names, colors, blend))
        out.paste(img.resize((size, size), Image.BILINEAR), (x, y + head))
        tx = x
        for j, s in enumerate(slots):            # タイトルも本番と同じ色分けで
            if j:
                d.text((tx, y + 2), " / ", font=font, fill=(0, 0, 0))
                tx += font.getlength(" / ")
            d.text((tx, y + 2), names.get(s, s), font=font, fill=core.parse_hex(title_hex(colors[s])))
            tx += font.getlength(names.get(s, s))
    return out


def default_summary_path(exp_path: str, out_dir: str | None = None) -> str:
    import datetime as _dt
    stem = core.safe_filename(os.path.splitext(os.path.basename(exp_path))[0])
    return os.path.join(out_dir or core.DEFAULT_OUT_DIR,
                        f"{stem}_まとめ_{_dt.date.today().strftime('%Y%m%d')}.pptx")


def default_dapi_name(exp_path: str) -> str:
    """DAPI チャンネルの表示名：色素名に Hoechst とあれば Hoechst、無ければ DAPI。"""
    try:
        d = core.load_czi(exp_path)
        c = channel_index(d, "DAPI")
        raw = (d.chans[c].get("name", "") if c is not None else "").lower()
        return "Hoechst" if "hoechst" in raw or "h3342" in raw else "DAPI"
    except Exception:
        return "DAPI"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="実験画像の 7 パネル（DAPI ありは 8）を pptx にまとめる"
                                             "（1 枚目：White を実験画像から / 2 枚目：White を Nega から）")
    ap.add_argument("--exp", help="実験画像の .czi（pptx を書き出すときに必要）")
    ap.add_argument("--nega", help="陰性対照（noAb）の .czi（2 枚目を作るときに必要）")
    ap.add_argument("--no-nega-slide", action="store_true", help="2 枚目（Nega 基準）を作らない")
    ap.add_argument("--dapi", action="store_true", help="DAPI（Hoechst）の単染色パネルを下段に足す")
    ap.add_argument("--names", help='抗体名 "AF488名,AF555名,AF647名[,DAPI名]"（既定はファイル名から推測）')
    ap.add_argument("--out", help="出力 .pptx（既定はドキュメントに自動命名）")
    ap.add_argument("--blend", default=SUMMARY_BLEND, choices=("screen", "add", "max"))
    ap.add_argument("--comment", default="", help="下のコメント枠に入れる文字")
    ap.add_argument("--white-percent", type=float, default=WHITE_TARGET_PERCENT,
                    help=f"White(%%)：その画像で White より明るい画素の割合（既定 {WHITE_TARGET_PERCENT:g} %%、ZEN の Best Fit と同じ）")
    ap.add_argument("--force", action="store_true", help="既存ファイルを上書きする")
    a = ap.parse_args(argv)
    nega_slide = not a.no_nega_slide
    slots = active_slots(a.dapi)
    if a.nega:
        res, warns = image_whites(a.nega, slots, "Nega", a.white_percent)
        print(f"Nega: {os.path.basename(a.nega)}")
        for slot, r in res.items():
            print(f"  {slot}: White = {r['V']:>5d}   実際の White(%) = {r['fraction'] * 100:.4f} %"
                  f"   （ch{r['index']} {r['name']}, 最大 {r['max']}, 飽和 {r['saturated'] * 100:.4f} %）")
    if not a.exp:
        return 0
    if nega_slide and not a.nega:
        raise SystemExit("2 枚目（Nega 基準）を作るには --nega が必要です（作らないなら --no-nega-slide）。")
    guessed = core._guess_antibodies(a.exp)
    guessed["DAPI"] = default_dapi_name(a.exp)
    if a.names:
        guessed.update(dict(zip(slots, [p.strip() for p in a.names.split(",")])))
    names = {s: guessed.get(s, s) for s in slots}
    print("名前:", names)
    out = a.out or default_summary_path(a.exp)
    if os.path.exists(out) and not a.force:
        print(f"既にあります（上書きするなら --force）: {out}")
        return 1
    r = build_summary(a.nega, a.exp, names, out, blend=a.blend, comment=a.comment,
                      percent=a.white_percent, nega_slide=nega_slide, dapi=a.dapi)
    for k, sl in enumerate(r["slides"], 1):
        print(f"  {k} 枚目（White を{SOURCE_LABELS[sl['source']]}）: "
              + "  ".join(f"{s} {d['V']}（{d['fraction'] * 100:.4f} %）" for s, d in sl["details"].items()))
    for w in r["warnings"]:
        print("  [警告] " + w)
    print(f"保存: {out}（{len(r['slides'])} 枚）")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
