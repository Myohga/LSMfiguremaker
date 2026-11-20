# -*- coding: utf-8 -*-
"""
czi_figure_gui.py
=================
czi_figure_core.py の上に載せる薄い GUI（Qt / qtpy 経由）。
左で設定をいじると右のプレビューが即座に描き直され、
「PNG を保存」で書き出す。描画は全て core が行う
（プレビューと保存結果は同じ関数で作るので見た目が一致する）。

    python czi_figure_gui.py              … 起動してから「開く」
    python czi_figure_gui.py "xxx.czi"    … そのファイルを開いた状態で起動

.czi や 設定 JSON / 保存済み PNG はウィンドウへドラッグ＆ドロップでも開ける。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

import numpy as np
from qtpy.QtCore import QSettings, Qt, QTimer
from qtpy.QtGui import QAction, QFont, QImage, QKeySequence, QPixmap
from qtpy.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QToolButton, QVBoxLayout, QWidget,
)

import czi_figure_core as core

try:  # 2 つのつまみを持つスライダー（napari と一緒に入っている superqt）
    from superqt import QRangeSlider
except ImportError:  # 無ければ普通のスライダー 2 本で代用する
    QRangeSlider = None
from qtpy.QtCore import Signal
from qtpy.QtWidgets import QSlider

COLOR_LABELS = {"blue": "青", "green": "緑", "red": "赤", "orange": "オレンジ", "magenta": "マゼンタ",
                "cyan": "シアン", "yellow": "黄", "gray": "白（グレー）"}
PCT_DEFAULT = (0.1, 99.8)


def pil_to_pixmap(img) -> QPixmap:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, 3 * img.width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def color_icon_css(name: str) -> str:
    r, g, b = core.text_rgb(name)
    return f"color: rgb({r},{g},{b}); font-weight: bold;"


class Preview(QLabel):
    """ウィンドウの大きさに合わせて縦横比を保って表示するラベル。"""

    def __init__(self):
        super().__init__("「.czi を開く」を押すか、.czi をここへドラッグしてください")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#e8e8e8; color:#555; font-size:14px;")
        self._pix: QPixmap | None = None

    def set_image(self, pix: QPixmap) -> None:
        self._pix = pix
        self._rescale()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))


SLIDER_STEPS = 1000


class _TwoSliders(QWidget):
    """superqt が無いときの代用：下限・上限のスライダーを横に 2 本並べる。"""
    valueChanged = Signal(tuple)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._lo, self._hi = _NoWheelSlider(), _NoWheelSlider()
        for s in (self._lo, self._hi):
            s.setRange(0, SLIDER_STEPS)
            s.valueChanged.connect(lambda _v: self.valueChanged.emit(self.value()))
            lay.addWidget(s)

    def value(self) -> tuple[int, int]:
        return self._lo.value(), self._hi.value()

    def setValue(self, v) -> None:
        # QRangeSlider と同じく変更を通知する（止めたいときは呼び出し側で blockSignals）
        changed = (int(v[0]), int(v[1])) != self.value()
        for s, x in ((self._lo, v[0]), (self._hi, v[1])):
            s.blockSignals(True)
            s.setValue(int(x))
            s.blockSignals(False)
        if changed:
            self.valueChanged.emit(self.value())


class _NoWheelSlider(QSlider):
    """スクロール中にマウスホイールで勝手に値が変わらないようにする。"""

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)

    def wheelEvent(self, e):
        e.ignore()


if QRangeSlider is not None:
    class _NoWheelRange(QRangeSlider):
        def __init__(self):
            super().__init__(Qt.Orientation.Horizontal)
            self.setRange(0, SLIDER_STEPS)
            self.setBarIsRigid(False)

        def wheelEvent(self, e):
            e.ignore()


def fit_spin(sp) -> None:
    """
    数値欄の幅を、入りうる一番長い数字＋▲▼ボタンが収まる幅にする。
    固定ピクセルで決めると、Windows 11 の見た目や画面の拡大率（125 %・150 % など）で
    ボタンが太くなり、数字が隠れてしまうため。最小値・最大値・接尾語（%）から Qt に計算させる。
    """
    sp.setMinimumWidth(sp.sizeHint().width() + 2)


def make_range_slider() -> QWidget:
    return _NoWheelRange() if QRangeSlider is not None else _TwoSliders()


class ChannelRow:
    """チャンネル 1 行分のウィジェットと、設定 dict（ch）の対応。"""

    def __init__(self, win: "MainWindow", ch: dict, r: int):
        self.win, self.ch = win, ch
        data = win.data
        c = data.index_of(ch)
        raw = data.chans[c].get("name", "") if c is not None else ""
        self.available = c is not None

        self.up = QToolButton(text="▲")
        self.down = QToolButton(text="▼")
        self.up.setToolTip("タイトルで前に出す")
        self.down.setToolTip("タイトルで後ろに下げる")
        self.up.clicked.connect(lambda: win.move_channel(ch, -1))
        self.down.clicked.connect(lambda: win.move_channel(ch, +1))

        self.cb = QCheckBox()
        self.cb.setChecked(bool(ch["enabled"]) and self.available)
        self.cb.setEnabled(self.available)
        self.cb.toggled.connect(lambda v: self._set("enabled", v))

        self.raw = QLabel(f"ch{c} {raw}" if self.available else "（無い）")
        self.raw.setToolTip(f"ch{c} {raw} / スロット: {ch.get('slot')}")
        self.raw.setMaximumWidth(130)

        self.name = QLineEdit(ch["name"])
        self.name.setMinimumWidth(80)
        self.name.textChanged.connect(lambda t: self._set("name", t))

        self.color = QComboBox()
        if core.parse_hex(ch["color"]):          # ZEN から読んだ色（#RRGGBB）はそのまま選べるように先頭へ
            self.color.addItem(f"ZEN {ch['color']}", ch["color"])
        for k, t in COLOR_LABELS.items():
            self.color.addItem(t, k)
        self.color.setCurrentIndex(max(0, self.color.findData(ch["color"])))
        self.color.currentIndexChanged.connect(self._color_changed)
        self._color_changed(self.color.currentIndex(), notify=False)

        self.mode = QComboBox()
        self.mode.addItem("%", "percentile")
        self.mode.addItem("輝度", "absolute")
        self.mode.setToolTip("% … 明るい方から何 % を飽和させるか（ファイルが変わっても使い回しやすい）\n"
                             "輝度 … 生の輝度値で固定（同じ条件で撮った画像を同じ明るさで並べたいとき）")
        self.mode.setCurrentIndex(0 if ch.get("range_mode", "percentile") == "percentile" else 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)

        self.lo, self.hi = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.lo, self.hi):
            sp.setKeyboardTracking(False)   # 幅は _config_spins で中身に合わせる
        self.lo.valueChanged.connect(lambda v: self._spin_changed("low", v))
        self.hi.valueChanged.connect(lambda v: self._spin_changed("high", v))

        # 明るさスライダー：つまみの位置＝実際の輝度。暗い側を細かく動かせるよう平方根目盛り。
        self.slider = make_range_slider()
        self.slider.setToolTip("左のつまみ＝下限（右へ動かすと背景が暗く締まる）\n"
                               "右のつまみ＝上限（左へ動かすと明るくなる）")
        self.slider.setMinimumWidth(240)
        self._config_spins()
        self.slider.valueChanged.connect(self._slider_changed)

        # ガンマ（中間調）：ZEN と同じ向き。1 未満で中間調が明るく、1 より大きいと暗く。
        self.gamma = QDoubleSpinBox()
        self.gamma.setRange(0.10, 5.00)
        self.gamma.setDecimals(2)
        self.gamma.setSingleStep(0.05)
        self.gamma.setKeyboardTracking(False)
        self.gamma.setValue(float(ch.get("gamma", 1.0)))
        fit_spin(self.gamma)
        self.gamma.setToolTip("中間調の明るさ（ZEN の Gamma と同じ向き）\n"
                              "1.00 … 直線（そのまま）\n"
                              "1 未満 … 中間調が明るくなり、暗い構造が見えやすい（例 0.70）\n"
                              "1 より大きい … 中間調が暗くなり、背景が締まる（例 1.50）\n"
                              "黒（下限）と白（上限）の位置は変わりません。右クリックで 1.00 に戻す")
        self.gamma.valueChanged.connect(lambda v: self._set("gamma", round(v, 2)))
        self.gamma.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.gamma.customContextMenuRequested.connect(lambda _p: self.gamma.setValue(1.0))

        self.actual = QLabel("")
        self.actual.setStyleSheet("color:#666;")
        self.actual.setToolTip("実際に 0〜255 へ割り当てている輝度の範囲")

        self.auto = QToolButton(text="自動")
        self.auto.setToolTip(f"表示レンジを既定（{PCT_DEFAULT[0]}〜{PCT_DEFAULT[1]} %）に戻す")
        self.auto.clicked.connect(self._reset)

        # 1 チャンネル＝2 行。横幅を詰めるため（画面拡大 150 % のノート PC でも横スクロールしないよう）
        #   上段: ▲ ON 表示名 色 範囲 下限 上限 ガンマ 自動
        #   下段: ▼ ・ 元の名前 [====明るさスライダー====] → 輝度
        g = win.grid
        for col, w in enumerate((self.up, self.cb, self.name, self.color, self.mode,
                                 self.lo, self.hi, self.gamma, self.auto)):
            g.addWidget(w, r, col)
        self.raw.setStyleSheet("color:#666; font-size:8pt;")
        g.addWidget(self.down, r + 1, 0)
        g.addWidget(self.raw, r + 1, 2)
        g.addWidget(self.slider, r + 1, 3, 1, 4)
        g.addWidget(self.actual, r + 1, 7, 1, 2)
        if not self.available:
            for w in (self.name, self.color, self.mode, self.lo, self.hi, self.auto,
                      self.slider, self.gamma):
                w.setEnabled(False)

    def _set(self, key, value):
        self.ch[key] = value
        self.win.schedule()

    # ---- スライダー ⇔ 下限/上限 ----
    def _vmax(self) -> float:
        c = self.win.data.index_of(self.ch)
        return max(1.0, self.win.data.channel_max(c)) if c is not None else 1.0

    def _to_pos(self, v: float) -> int:
        return int(round(SLIDER_STEPS * (max(0.0, v) / self._vmax()) ** 0.5))

    def _to_value(self, pos: int) -> float:
        return self._vmax() * (pos / SLIDER_STEPS) ** 2

    def _sync_slider(self):
        c = self.win.data.index_of(self.ch)
        if c is None:
            return
        lo, hi = core.display_range(self.win.data, c, self.ch)
        self.slider.blockSignals(True)
        self.slider.setValue((self._to_pos(lo), self._to_pos(min(hi, self._vmax()))))
        self.slider.blockSignals(False)

    def _spin_changed(self, key, v):
        self.ch[key] = v
        self._sync_slider()
        self.win.schedule()

    def _slider_changed(self, value):
        c = self.win.data.index_of(self.ch)
        if c is None:
            return
        p_lo, p_hi = sorted(int(x) for x in value)
        if p_hi <= p_lo:
            p_hi = min(SLIDER_STEPS, p_lo + 1)
        lo, hi = self._to_value(p_lo), self._to_value(p_hi)
        if self.ch.get("range_mode", "percentile") == "percentile":
            # 輝度で動かして、% に直して持つ（ファイルを替えても使い回せる形のまま）
            lo = round(self.win.data.percentile_of(c, lo), 2)
            hi = round(self.win.data.percentile_of(c, hi), 2)
            if hi <= lo:
                hi = min(100.0, lo + 0.01)
        else:
            lo, hi = round(lo), max(round(hi), round(lo) + 1)
        self.ch.update(low=lo, high=hi)
        for sp, v in ((self.lo, lo), (self.hi, hi)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self.win.schedule()

    def _color_changed(self, i, notify=True):
        key = self.color.itemData(i)
        self.color.setStyleSheet(color_icon_css(key))
        if notify:
            self._set("color", key)

    def _config_spins(self):
        pct = self.ch.get("range_mode", "percentile") == "percentile"
        planes = self.win.data.planes        # 輝度の上限：整数画像ならその型の最大値（ZEN の全範囲 65535 も入るように）
        dmax = np.iinfo(planes.dtype).max if np.issubdtype(planes.dtype, np.integer) else planes.max()
        top = 100.0 if pct else float(max(1, dmax, float(self.ch.get("high", 0))))
        for sp, key in ((self.lo, "low"), (self.hi, "high")):
            sp.blockSignals(True)
            sp.setDecimals(2 if pct else 0)
            sp.setRange(0.0, top)
            sp.setSingleStep((0.1 if key == "low" else 0.05) if pct else max(1.0, top / 200))
            sp.setSuffix(" %" if pct else "")
            sp.setValue(float(self.ch[key]))
            sp.blockSignals(False)
            fit_spin(sp)                     # % と 輝度 で桁数が違うので、切り替えのたびに合わせ直す
        self._sync_slider()

    def _mode_changed(self, i):
        new = self.mode.itemData(i)
        c = self.win.data.index_of(self.ch)
        if new == "absolute" and c is not None:
            # 今見えている明るさのまま輝度値に切り替える
            lo, hi = core.display_range(self.win.data, c, self.ch)
            self.ch.update(range_mode="absolute", low=round(lo), high=round(hi))
        else:
            self.ch.update(range_mode="percentile", low=PCT_DEFAULT[0], high=PCT_DEFAULT[1])
        self._config_spins()
        self.win.schedule()

    def _reset(self):
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        self.ch.update(range_mode="percentile", low=PCT_DEFAULT[0], high=PCT_DEFAULT[1])
        self._config_spins()
        self.win.schedule()

    def update_actual(self):
        c = self.win.data.index_of(self.ch)
        if c is None:
            return
        lo, hi = core.display_range(self.win.data, c, self.ch)
        self.actual.setText(f"{lo:.0f}–{hi:.0f}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CZI 図作成")
        # 画面の拡大率が 150 % のノート PC では使える幅が 1280 px 程度しかないので、画面に合わせる
        avail = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1600, int(avail.width() * 0.95)), min(1000, int(avail.height() * 0.9)))
        self.setAcceptDrops(True)
        self.settings = QSettings("czi_figure", "czi_figure_gui")
        self.cfg: dict | None = None
        self.data: core.CziData | None = None
        self.style: dict | None = None        # 「設定を読込」したがまだファイルを開いていないとき
        self.rows: list[ChannelRow] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self.refresh)

        self._build_menu()

        side = QWidget()
        self.side = QVBoxLayout(side)

        # ---- ファイル ----
        top = QHBoxLayout()
        for text, fn, tip in ((".czi を開く…", self.open_dialog, "Ctrl+O"),
                              ("設定を読込…", self.load_style_dialog,
                               "保存した設定 JSON か、このツールで作った PNG から体裁を読み込む"),
                              ("設定を保存…", self.save_style_dialog,
                               "今の体裁を JSON に保存して、別の .czi に使い回す"),
                              ("ZEN の表示に合わせる", self.apply_zen,
                               ".czi に保存されている ZEN の表示設定（色・黒・白・ガンマ）を読み込んで、\n"
                               "ZEN と同じ見た目にする（抗体名・ラベル・枠はそのまま）")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            top.addWidget(b)
        self.side.addLayout(top)
        self.cb_zen_open = QCheckBox("開いたときは ZEN の表示設定から始める")
        self.cb_zen_open.setToolTip("オンにすると、.czi を開くたびに ZEN の色・黒・白・ガンマで表示します")
        self.cb_zen_open.setChecked(self.settings.value("zen_on_open", True, type=bool))
        self.cb_zen_open.toggled.connect(lambda v: self.settings.setValue("zen_on_open", v))
        self.side.addWidget(self.cb_zen_open)
        self.lbl_file = QLabel("（未選択）")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet("font-weight:bold;")
        self.lbl_info = QLabel("")
        self.side.addWidget(self.lbl_file)
        self.side.addWidget(self.lbl_info)
        srow = QHBoxLayout()
        self.lbl_scene = QLabel("シーン（Position）")
        self.sp_scene = QSpinBox()
        self.sp_scene.setKeyboardTracking(False)
        self.sp_scene.valueChanged.connect(self.change_scene)
        self.lbl_nscene = QLabel("")
        for w in (self.lbl_scene, self.sp_scene, self.lbl_nscene):
            srow.addWidget(w)
        srow.addStretch(1)
        self.side.addLayout(srow)
        self._show_scene_row(False)

        # ---- チャンネル ----
        self.side.addWidget(QLabel("<b>チャンネル</b>　ON にしたものを合成。▲▼ でタイトルの並び順。"
                                   "下限を上げると背景が締まり、上限を下げると明るくなる"))
        self.box_ch = QGroupBox()
        self.grid = QGridLayout(self.box_ch)
        self.grid.setHorizontalSpacing(6)
        self.side.addWidget(self.box_ch)

        # ---- ラベル・スケールバー ----
        box_lab = QGroupBox("ラベル・タイトル・スケールバー")
        form = QFormLayout(box_lab)
        self.ed_label = QLineEdit()
        self.ed_label.setPlaceholderText("例: ACh DIV 26")
        self.ed_label.textChanged.connect(lambda t: self._set("label", t))
        form.addRow("左の縦書きラベル", self.ed_label)
        self.ed_sep = QLineEdit(" / ")
        self.ed_sep.textChanged.connect(lambda t: self._set("title_sep", t))
        form.addRow("タイトルの区切り", self.ed_sep)
        vis = QHBoxLayout()
        self.cb_title = QCheckBox("タイトル枠")
        self.cb_title.toggled.connect(lambda v: self._set("show_title", v))
        self.cb_lab = QCheckBox("ラベル枠")
        self.cb_lab.toggled.connect(lambda v: self._set("show_label", v))
        vis.addWidget(self.cb_title)
        vis.addWidget(self.cb_lab)
        vis.addStretch(1)
        form.addRow("表示する枠", vis)
        row = QHBoxLayout()
        self.cb_sb = QCheckBox("表示")
        self.cb_sb.toggled.connect(lambda v: self._set_sb("show", v))
        self.sp_sb = QDoubleSpinBox()
        self.sp_sb.setRange(1, 5000)
        self.sp_sb.setDecimals(0)
        self.sp_sb.setSuffix(" µm")
        self.sp_sb.setKeyboardTracking(False)
        self.sp_sb.valueChanged.connect(lambda v: self._set_sb("um", v))
        self.lbl_sbpx = QLabel("")
        self.lbl_sbpx.setStyleSheet("color:#666;")
        row.addWidget(self.cb_sb)
        row.addWidget(self.sp_sb)
        row.addWidget(self.lbl_sbpx)
        row.addStretch(1)
        form.addRow("スケールバー", row)
        self.cb_mag = QCheckBox("赤をマゼンタにする（色覚対応・画像とタイトルの両方）")
        self.cb_mag.toggled.connect(lambda v: self._set("colorblind_magenta", v))
        form.addRow("", self.cb_mag)
        self.cmb_blend = QComboBox()
        for k, t in (("screen", "スクリーン（既定）"), ("max", "最大値"), ("add", "加算")):
            self.cmb_blend.addItem(t, k)
        self.cmb_blend.currentIndexChanged.connect(
            lambda i: self._set("blend", self.cmb_blend.itemData(i)))
        form.addRow("合成方法", self.cmb_blend)
        self.sp_font = QDoubleSpinBox()
        self.sp_font.setRange(0.5, 3.0)
        self.sp_font.setSingleStep(0.1)
        self.sp_font.setSuffix(" 倍")
        self.sp_font.valueChanged.connect(lambda v: self._set("font_scale", v))
        form.addRow("文字・枠の大きさ", self.sp_font)
        self.side.addWidget(box_lab)

        # ---- 書き出し ----
        box_out = QGroupBox("書き出し")
        fo = QFormLayout(box_out)
        what = QHBoxLayout()
        self.cb_comp = QCheckBox("合成パネル")
        self.cb_single = QCheckBox("単色パネル（各チャンネルをグレーで）")
        self.cb_comp.setChecked(self.settings.value("export_composite", True, type=bool))
        self.cb_single.setChecked(self.settings.value("export_single", False, type=bool))
        what.addWidget(self.cb_comp)
        what.addWidget(self.cb_single)
        what.addStretch(1)
        fo.addRow("書き出すもの", what)
        self.cmb_fmt = QComboBox()
        for k, t in (("png", "PNG 画像"),
                     ("pptx", "PowerPoint（.pptx）… 画像・枠・文字・スケールバーを別々のオブジェクトで"),
                     ("both", "PNG と PowerPoint の両方")):
            self.cmb_fmt.addItem(t, k)
        self.cmb_fmt.setCurrentIndex(max(0, self.cmb_fmt.findData(
            self.settings.value("export_format", "png", type=str))))
        fo.addRow("形式", self.cmb_fmt)
        dr = QHBoxLayout()
        self.lbl_outdir = QLabel("")
        self.lbl_outdir.setWordWrap(True)
        b = QPushButton("変更…")
        b.clicked.connect(self.choose_out_dir)
        dr.addWidget(self.lbl_outdir, 1)
        dr.addWidget(b)
        fo.addRow("保存先", dr)
        res = QHBoxLayout()
        self.sp_up = QSpinBox()
        self.sp_up.setRange(1, 4)
        self.sp_up.setSuffix(" 倍")
        self.sp_up.setToolTip("最近傍で整数倍に拡大（画素値は変えない）。スケールバーも正しく伸びる")
        self.sp_up.valueChanged.connect(lambda v: self._set("upscale", v))
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(72, 1200)
        self.sp_dpi.setSuffix(" dpi")
        self.sp_dpi.valueChanged.connect(lambda v: self._set("dpi", v))
        res.addWidget(QLabel("拡大"))
        res.addWidget(self.sp_up)
        res.addWidget(QLabel("解像度の記録"))
        res.addWidget(self.sp_dpi)
        res.addStretch(1)
        fo.addRow("サイズ", res)
        self.btn_save = QPushButton("保存…   (Ctrl+S)")
        self.btn_save.setStyleSheet("font-weight:bold; padding:6px;")
        self.btn_save.clicked.connect(self.save)
        self.btn_scenes = QPushButton("全シーンを一括保存")
        self.btn_scenes.clicked.connect(self.save_all_scenes)
        self.btn_files = QPushButton("複数の .czi に同じ体裁で一括保存…")
        self.btn_files.setToolTip("色・明るさ・枠などの体裁を当てて保存。抗体名と左ラベルは各ファイル名から推測")
        self.btn_files.clicked.connect(self.save_many_files)
        fo.addRow(self.btn_save)
        fo.addRow(self.btn_scenes)
        fo.addRow(self.btn_files)
        self.btn_summary = QPushButton("pptx データまとめ（Nega ＋ 実験画像 → 7 パネル）…")
        self.btn_summary.setToolTip("Nega から White を決めて、実験画像の単染色 3 枚＋マージ 4 枚を\n"
                                    "参考様式の pptx 1 枚にまとめる（別の画面が開きます）")
        self.btn_summary.clicked.connect(self.open_summary)
        fo.addRow(self.btn_summary)
        self.side.addWidget(box_out)
        self.side.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidget(side)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumWidth(560)        # ファイルを開いたら中身に合わせて広げる

        self.preview = Preview()
        self.split = QSplitter()
        self.split.addWidget(self.scroll)
        self.split.addWidget(self.preview)
        self.split.setStretchFactor(1, 1)
        self.setCentralWidget(self.split)
        self._enable(False)
        self.statusBar().showMessage("準備完了")

    # ---------------------------------------------------------------- 共通
    def _build_menu(self):
        m = self.menuBar().addMenu("ファイル(&F)")
        for text, key, fn in (("開く…", QKeySequence.StandardKey.Open, self.open_dialog),
                              ("保存…", QKeySequence.StandardKey.Save, self.save),
                              ("設定を読込…", "Ctrl+L", self.load_style_dialog),
                              ("設定を保存…", "Ctrl+Shift+S", self.save_style_dialog),
                              ("pptx データまとめ…", "Ctrl+M", self.open_summary),
                              (None, None, None),
                              ("終了", QKeySequence.StandardKey.Quit, self.close)):
            if text is None:
                m.addSeparator()
                continue
            act = QAction(text, self)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(fn)
            m.addAction(act)

    def _enable(self, on: bool):
        for w in (self.btn_save, self.btn_files):
            w.setEnabled(on)
        self.btn_scenes.setEnabled(on and self.data is not None and self.data.n_scenes > 1)

    def open_summary(self):
        """「pptx データまとめ」の画面を開く。いま開いている .czi があれば実験画像として入れておく。"""
        try:
            import czi_summary_gui
        except Exception as e:
            self._error("pptx データまとめを開けません", e)
            return
        exp = self.cfg["czi_path"] if self.cfg else None
        self._summary = czi_summary_gui.SummaryDialog(self, exp)
        self._summary.setModal(False)
        self._summary.show()

    def _show_scene_row(self, on: bool):
        for w in (self.lbl_scene, self.sp_scene, self.lbl_nscene):
            w.setVisible(on)

    def schedule(self):
        # 間引き：ドラッグ中も一定間隔でプレビューを更新する（止めるまで待たない）
        if not self._timer.isActive():
            self._timer.start()

    def _set(self, key, value):
        if self.cfg is not None:
            self.cfg[key] = value
            self.schedule()

    def _set_sb(self, key, value):
        if self.cfg is not None:
            self.cfg["scalebar"][key] = value
            self.schedule()

    def _error(self, title: str, e: Exception):
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(self, title, f"{e}\n\n--- 詳細 ---\n{traceback.format_exc()}")

    def _last_dir(self, key: str, fallback: str) -> str:
        d = self.settings.value(key, "", type=str)
        return d if d and os.path.isdir(d) else fallback

    # ---------------------------------------------------------------- ドラッグ＆ドロップ
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        styles = [p for p in paths if p.lower().endswith((".json", ".png"))]
        czis = [p for p in paths if p.lower().endswith(".czi")]
        if styles:
            self.load_style(styles[0])
        if czis:
            self.open_file(czis[0])

    # ---------------------------------------------------------------- ファイル
    def open_dialog(self):
        start = self._last_dir("czi_dir", os.path.expanduser("~/Downloads"))
        path, _ = QFileDialog.getOpenFileName(self, ".czi を開く", start, "CZI (*.czi)")
        if path:
            self.open_file(path)

    def open_file(self, path: str, scene: int = 0):
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            cfg = core.default_config(path, scene)
            data = core.load_czi(path, scene, cfg["z_reduce"])
            prev = self.cfg or self.style
            if prev is not None:
                cfg = core.merge_config(cfg, prev)   # 体裁を引き継ぐ（名前・ラベルは賢く）
            zen_notes = []
            if self.cb_zen_open.isChecked():
                cfg, zen_notes = core.apply_zen_display(cfg, data)
            QApplication.restoreOverrideCursor()
        except Exception as e:
            self._error("読み込みエラー", e)
            return
        self.settings.setValue("czi_dir", os.path.dirname(path))
        if self.settings.value("out_dir", "", type=str) and prev is None:
            cfg["out_dir"] = self.settings.value("out_dir", type=str)
        self.cfg, self.data, self.style = cfg, data, None
        self._after_load()
        if zen_notes:
            self._show_zen_notes(zen_notes)

    def apply_zen(self):
        if self.cfg is None:
            QMessageBox.information(self, "ZEN の表示", "先に .czi を開いてください。")
            return
        try:
            self.cfg, notes = core.apply_zen_display(self.cfg, self.data)
        except Exception as e:
            self._error("ZEN の表示設定の読み込みエラー", e)
            return
        self._load_widgets()
        self.refresh()
        self._show_zen_notes(notes)

    def _show_zen_notes(self, notes: list[str]):
        """1 行目はステータスバーへ。注意（白の位置が無い等）があるときだけ画面にも出す。"""
        self.statusBar().showMessage(notes[0], 15000)
        if len(notes) > 1:                      # 作業を止めないよう、閉じなくても操作できる窓で出す
            self._zen_box = QMessageBox(QMessageBox.Icon.Information, "ZEN の表示設定",
                                        "\n\n".join(notes), QMessageBox.StandardButton.Ok, self)
            self._zen_box.setModal(False)
            self._zen_box.show()

    def change_scene(self, s: int):
        if self.cfg is None or s == self.cfg["scene"]:
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            data = core.load_czi(self.cfg["czi_path"], s, self.cfg["z_reduce"])
            QApplication.restoreOverrideCursor()
        except Exception as e:
            self._error("シーンの読み込みエラー", e)
            return
        self.cfg["scene"] = s
        self.data = data
        self._after_load()

    def _after_load(self):
        d, cfg = self.data, self.cfg
        self.lbl_file.setText(os.path.basename(cfg["czi_path"]))
        h, w = d.planes.shape[1:]
        um = f"{d.um_px:.4f} µm/px" if d.um_px else "µm/px 不明（スケールバーは描けません）"
        self.lbl_info.setText(f"{w}×{h} px ・ {um} ・ {d.planes.dtype}")
        self._show_scene_row(d.n_scenes > 1)
        self.sp_scene.blockSignals(True)
        self.sp_scene.setRange(0, max(0, d.n_scenes - 1))
        self.sp_scene.setValue(cfg["scene"])
        self.sp_scene.blockSignals(False)
        self.lbl_nscene.setText(f"/ {d.n_scenes - 1}（全 {d.n_scenes} シーン）")
        self._load_widgets()
        self._enable(True)
        self.refresh()

    def _load_widgets(self):
        cfg = self.cfg
        setters = (
            (self.ed_label, "setText", cfg["label"]),
            (self.ed_sep, "setText", cfg["title_sep"]),
            (self.cb_title, "setChecked", cfg.get("show_title", True)),
            (self.cb_lab, "setChecked", cfg.get("show_label", True)),
            (self.cb_sb, "setChecked", cfg["scalebar"].get("show", True)),
            (self.sp_sb, "setValue", float(cfg["scalebar"].get("um", 50))),
            (self.cb_mag, "setChecked", cfg.get("colorblind_magenta", False)),
            (self.sp_font, "setValue", float(cfg.get("font_scale", 1.0))),
            (self.sp_up, "setValue", int(cfg.get("upscale", 1))),
            (self.sp_dpi, "setValue", int(cfg.get("dpi", 300))),
            (self.cmb_blend, "setCurrentIndex",
             max(0, self.cmb_blend.findData(cfg.get("blend", "screen")))),
        )
        for w, meth, v in setters:
            w.blockSignals(True)
            getattr(w, meth)(v)
            w.blockSignals(False)
        self.lbl_outdir.setText(cfg.get("out_dir") or core.DEFAULT_OUT_DIR)
        self._build_channel_rows()

    def _build_channel_rows(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        heads = ("", "ON", "表示名（抗体名）", "色", "範囲", "下限", "上限", "ガンマ", "")
        for col, t in enumerate(heads):
            if t:
                self.grid.addWidget(QLabel(f"<b>{t}</b>"), 0, col)
        # 1 チャンネル＝2 行（上：設定、下：明るさスライダー）
        self.rows = [ChannelRow(self, ch, 1 + 2 * i) for i, ch in enumerate(self.cfg["channels"])]
        for i, row in enumerate(self.rows):
            row.up.setEnabled(i > 0)
            row.down.setEnabled(i < len(self.rows) - 1)
        self._fit_side_panel()
        # 作ったばかりの行は幅がまだ確定していないので、レイアウトが落ち着いた直後にもう一度合わせる
        QTimer.singleShot(0, self._fit_side_panel)

    def _fit_side_panel(self):
        """左の設定パネルを、中身が横スクロールなしで収まる幅にする（プレビュー分は残す）。"""
        side = self.scroll.widget()
        side.layout().activate()
        need = (side.sizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width()
                + 2 * self.scroll.frameWidth() + 4)
        want = min(need, max(560, self.width() - 380))   # プレビューに最低 380 px は残す
        self.scroll.setMinimumWidth(want)
        sizes = self.split.sizes()               # 仕切りは自動では動かないので、明示的に寄せる
        if sizes and sizes[0] < want:
            total = sum(sizes)
            self.split.setSizes([want, max(300, total - want)])

    def move_channel(self, ch: dict, step: int):
        chs = self.cfg["channels"]
        i = chs.index(ch)
        j = i + step
        if 0 <= j < len(chs):
            chs[i], chs[j] = chs[j], chs[i]
            self._build_channel_rows()
            self.schedule()

    # ---------------------------------------------------------------- 設定の保存/読込
    def save_style_dialog(self):
        if self.cfg is None:
            QMessageBox.information(self, "設定を保存", "先に .czi を開いてください。")
            return
        start = os.path.join(self._last_dir("style_dir", self.cfg.get("out_dir") or core.DEFAULT_OUT_DIR),
                             "体裁.json")
        path, _ = QFileDialog.getSaveFileName(self, "設定を保存", start, "設定 JSON (*.json)")
        if not path:
            return
        try:
            core.save_config(self.cfg, path)
        except Exception as e:
            self._error("保存エラー", e)
            return
        self.settings.setValue("style_dir", os.path.dirname(path))
        self.statusBar().showMessage(f"設定を保存しました: {path}")

    def load_style_dialog(self):
        start = self._last_dir("style_dir", core.DEFAULT_OUT_DIR)
        path, _ = QFileDialog.getOpenFileName(
            self, "設定を読込（JSON か、このツールで保存した PNG）", start,
            "設定 (*.json *.png);;JSON (*.json);;PNG (*.png)")
        if path:
            self.load_style(path)

    def load_style(self, path: str):
        try:
            style = core.load_config(path)
        except Exception as e:
            self._error("設定の読込エラー", e)
            return
        self.settings.setValue("style_dir", os.path.dirname(path))
        if self.cfg is None:
            self.style = style
            src = style.get("czi_path")
            if src and os.path.exists(src) and QMessageBox.question(
                    self, "設定を読込",
                    f"この設定は次の .czi で作られています。開きますか？\n\n{os.path.basename(src)}"
            ) == QMessageBox.StandardButton.Yes:
                self.open_file(src, int(style.get("scene", 0)))
            else:
                self.statusBar().showMessage("設定を読み込みました。.czi を開くと適用されます。")
            return
        self.cfg = core.merge_config(core.default_config(self.cfg["czi_path"], self.cfg["scene"]), style)
        self._load_widgets()
        self.refresh()
        self.statusBar().showMessage(f"設定を適用しました: {os.path.basename(path)}")

    # ---------------------------------------------------------------- 描画
    def refresh(self):
        if self.cfg is None:
            return
        try:
            img, info = core.render_panel(self.cfg, self.data, with_info=True)
        except Exception as e:
            self.statusBar().showMessage(f"描画エラー: {e}")
            return
        self.preview.set_image(pil_to_pixmap(img))
        for r in self.rows:
            r.update_actual()
        sb = info.get("scalebar")
        self.lbl_sbpx.setText(f"= {sb['length_px']} px" if sb else "")
        msg = f"出力 {img.width}×{img.height} px（{self.cfg['dpi']} dpi で {img.width / self.cfg['dpi'] * 25.4:.0f} mm 幅）"
        if sb:
            msg += f" ・ スケールバー {sb['um']:g} µm = {sb['length_px']} px"
        self.statusBar().showMessage(msg)

    # ---------------------------------------------------------------- 書き出し
    def choose_out_dir(self):
        start = (self.cfg or {}).get("out_dir") or core.DEFAULT_OUT_DIR
        d = QFileDialog.getExistingDirectory(self, "保存先フォルダ", start)
        if d:
            self.settings.setValue("out_dir", d)
            self.lbl_outdir.setText(d)
            if self.cfg is not None:
                self.cfg["out_dir"] = d

    def _what(self) -> tuple[bool, bool, bool, bool] | None:
        """(合成, 単色, PNG を書くか, PPTX を書くか)。"""
        comp, single = self.cb_comp.isChecked(), self.cb_single.isChecked()
        fmt = self.cmb_fmt.currentData()
        self.settings.setValue("export_composite", comp)
        self.settings.setValue("export_single", single)
        self.settings.setValue("export_format", fmt)
        if not (comp or single):
            QMessageBox.information(self, "書き出し", "「合成パネル」か「単色パネル」のどちらかに印を付けてください。")
            return None
        return comp, single, fmt in ("png", "both"), fmt in ("pptx", "both")

    def _ask_pptx_path(self, default: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self, "PowerPoint を保存（1 パネル＝1 スライド）", default, "PowerPoint (*.pptx)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return None
        return path if path.lower().endswith(".pptx") else path + ".pptx"

    def _confirm_overwrite(self, paths: list[str]) -> set[str] | None:
        """既存ファイルがあれば聞く。戻り値は飛ばすパスの集合（None はキャンセル）。"""
        exist = [p for p in paths if os.path.exists(p)]
        if not exist:
            return set()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("上書き確認")
        shown = "\n".join(os.path.basename(p) for p in exist[:12])
        more = f"\n…ほか {len(exist) - 12} 件" if len(exist) > 12 else ""
        box.setText(f"次の {len(exist)} 件は既にあります。\n\n{shown}{more}")
        b_over = box.addButton("上書きする", QMessageBox.ButtonRole.AcceptRole)
        b_skip = box.addButton("既存は残して他だけ保存", QMessageBox.ButtonRole.ActionRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_over:
            return set()
        if box.clickedButton() is b_skip:
            return set(exist)
        return None

    def save(self):
        if self.cfg is None:
            QMessageBox.information(self, "保存", "先に .czi を開いてください。")
            return
        what = self._what()
        if what is None:
            return
        comp, single, png, pptx = what
        plan, pptx_path = [], None
        if png:
            path, _ = QFileDialog.getSaveFileName(
                self, "PNG を保存（単色パネルはこの名前＋_抗体名 になります）",
                core.default_out_path(self.cfg), "PNG (*.png)",
                options=QFileDialog.Option.DontConfirmOverwrite)
            if not path:
                return
            if not path.lower().endswith(".png"):
                path += ".png"
            plan = core.plan_outputs(self.cfg, comp, single, path)
            if pptx:                                  # 両方のときは PNG と同じ名前で .pptx
                pptx_path = os.path.splitext(path)[0] + ".pptx"
        else:
            pptx_path = self._ask_pptx_path(core.default_pptx_path([self.cfg]))
            if not pptx_path:
                return
        targets = [p for p, _ in plan] + ([pptx_path] if pptx_path else [])
        skip = self._confirm_overwrite(targets)
        if skip is None:
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            saved = core.write_outputs(self.cfg, plan, self.data, skip) if plan else []
            if pptx_path and pptx_path not in skip:
                n = core.write_pptx(pptx_path, [self.cfg], comp, single, data=self.data)
                saved.append(f"{os.path.basename(pptx_path)}（{n} スライド）")
            QApplication.restoreOverrideCursor()
        except Exception as e:
            self._error("保存エラー", e)
            return
        self.cfg["out_dir"] = os.path.dirname(targets[0])
        self.lbl_outdir.setText(self.cfg["out_dir"])
        self.settings.setValue("out_dir", self.cfg["out_dir"])
        self.statusBar().showMessage(f"{len(saved)} 件保存しました: "
                                     + ", ".join(os.path.basename(p) for p in saved))

    def _run_batch(self, jobs: list[dict], title: str):
        """jobs（設定のリスト）を全部書き出す。上書きはまとめて 1 回だけ確認する。
        PowerPoint は全部を 1 つのファイルにまとめる（1 パネル＝1 スライド）。"""
        what = self._what()
        if what is None:
            return
        comp, single, png, pptx = what
        pptx_path = None
        if pptx:
            pptx_path = self._ask_pptx_path(core.default_pptx_path(jobs))
            if not pptx_path:
                return
        try:
            plans = [(c, core.plan_outputs(c, comp, single)) for c in jobs] if png else []
        except Exception as e:
            self._error("準備エラー", e)
            return
        targets = [p for _, pl in plans for p, _ in pl] + ([pptx_path] if pptx_path else [])
        skip = self._confirm_overwrite(targets)
        if skip is None:
            return
        steps = len(plans) + (len(jobs) if pptx_path and pptx_path not in skip else 0)
        prog = QProgressDialog(title, "中止", 0, max(1, steps), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        saved, failed = [], []
        done = 0

        def tick(c: dict, what: str) -> bool:
            nonlocal done
            prog.setValue(done)
            prog.setLabelText(f"{title}（{what}）\n{os.path.basename(c['czi_path'])}  シーン {c['scene']}")
            QApplication.processEvents()
            done += 1
            return not prog.wasCanceled()

        for c, pl in plans:
            if not tick(c, "PNG"):
                break
            try:
                saved += core.write_outputs(c, pl, None, skip)
            except Exception as e:
                failed.append(f"{os.path.basename(c['czi_path'])} S{c['scene']}: {e}")
        if pptx_path and pptx_path not in skip and not prog.wasCanceled():
            try:
                n = core.write_pptx(pptx_path, jobs, comp, single,
                                    progress=lambda i, n, c: tick(c, "PowerPoint"))
                saved.append(f"{os.path.basename(pptx_path)}（{n} スライド）")
            except Exception as e:
                failed.append(f"PowerPoint: {e}")
        prog.setValue(prog.maximum())
        # プレビュー中のファイルのキャッシュを戻す
        self.data = core.load_czi(self.cfg["czi_path"], self.cfg["scene"], self.cfg["z_reduce"])
        where = os.path.dirname(pptx_path) if pptx_path and not png else jobs[0].get("out_dir")
        msg = f"{len(saved)} 件保存しました（保存先: {where}）"
        if failed:
            QMessageBox.warning(self, title, msg + "\n\n失敗:\n" + "\n".join(failed))
        else:
            QMessageBox.information(self, title, msg)
        self.statusBar().showMessage(msg)

    def save_all_scenes(self):
        if self.cfg is None:
            return
        self._run_batch(core.configs_for_scenes(self.cfg), "全シーンを書き出し中")

    def save_many_files(self):
        if self.cfg is None:
            return
        start = self._last_dir("czi_dir", os.path.dirname(self.cfg["czi_path"]))
        paths, _ = QFileDialog.getOpenFileNames(self, "同じ体裁で書き出す .czi を選ぶ（複数可）",
                                                start, "CZI (*.czi)")
        if not paths:
            return
        all_scenes = False
        try:
            multi = [p for p in paths if core.count_scenes(p) > 1]
        except Exception:
            multi = []
        if multi:
            all_scenes = QMessageBox.question(
                self, "シーン", f"{len(multi)} 個のファイルに複数のシーンがあります。全シーンを書き出しますか？\n"
                "（いいえ＝各ファイルのシーン 0 だけ）") == QMessageBox.StandardButton.Yes
        jobs = []
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            for p in paths:
                c = self.cfg if os.path.samefile(p, self.cfg["czi_path"]) else core.config_for_file(p, self.cfg)
                jobs += core.configs_for_scenes(c) if all_scenes else [{**c, "scene": c.get("scene", 0)}]
            QApplication.restoreOverrideCursor()
        except Exception as e:
            self._error("準備エラー", e)
            return
        self._run_batch(jobs, f"{len(paths)} 個の .czi を書き出し中")


LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "czi_figure")


def _write_log(text: str) -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, "error.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    return path


def _excepthook(etype, value, tb):
    """想定外のエラーで黙って落ちないよう、内容を表示してログに残す（.exe 版は黒い画面が無いため）。"""
    text = "".join(traceback.format_exception(etype, value, tb))
    log = _write_log(text)
    try:
        QMessageBox.critical(None, "予期しないエラー",
                             f"{value}\n\n詳細は次のファイルに保存しました:\n{log}\n\n{text[-1500:]}")
    except Exception:
        pass


UI_FONTS = ["Yu Gothic UI", "Meiryo UI", "Yu Gothic", "MS UI Gothic"]   # 全部ゴシック（明朝に化けないよう）
# Windows は部品の種類ごとに別のフォントを割り当てることがある（例：小さいボタン QToolButton）。
# その既定フォントに日本語が無いと、文字だけ明朝体に置き換わって見えるので、種類ごとに上書きする。
UI_FONT_CLASSES = ("QWidget", "QToolButton", "QPushButton", "QLabel", "QCheckBox", "QComboBox",
                   "QAbstractItemView", "QLineEdit", "QAbstractSpinBox", "QGroupBox", "QMenu",
                   "QMenuBar", "QMessageBox", "QToolTip", "QStatusBar", "QHeaderView",
                   "QProgressDialog", "QDialog", "QTabBar", "QDockWidget")


def setup_app_font(app: QApplication, size_pt: float = 10) -> QFont:
    """画面の文字を Yu Gothic UI に統一する（無い PC では Meiryo UI → 游ゴシック → MS UI Gothic）。"""
    font = QFont()
    font.setFamilies(UI_FONTS)
    font.setPointSizeF(size_pt)
    app.setFont(font)
    for cls in UI_FONT_CLASSES:
        app.setFont(font, cls)
    return font


def selftest(czi: str, out_dir: str, nega: str | None = None) -> int:
    """.exe が正しく組み上がったかの確認用：開く→描く→PNG と PPTX を保存、結果を selftest.txt に書く。"""
    lines = []
    try:
        os.makedirs(out_dir, exist_ok=True)
        cfg = core.default_config(czi)
        cfg["out_dir"] = out_dir
        data = core.load_czi(czi)
        lines.append(f"engine: {core.load_engine().__name__}")
        lines.append(f"czi: {data.planes.shape} {data.planes.dtype} um_px={data.um_px}")
        img, info = core.render_panel(cfg, data, with_info=True)
        png = core.save_png(img, os.path.join(out_dir, "selftest.png"), cfg)
        n = core.write_pptx(os.path.join(out_dir, "selftest.pptx"), [cfg], True, True, data=data)
        lines.append(f"png: {png} {img.size} scalebar={info['scalebar']['length_px'] if info['scalebar'] else None}")
        lines.append(f"pptx: {n} slides")
        app = QApplication.instance() or QApplication(sys.argv)
        setup_app_font(app)
        win = MainWindow()
        win.open_file(czi)
        win.rows[0].slider.setValue((100, 900))
        win.refresh()
        lines.append(f"gui: rows={len(win.rows)} slider={type(win.rows[0].slider).__name__} "
                     f"status={win.statusBar().currentMessage()}")
        if nega:                                   # pptx データまとめ（テンプレートの同梱も確かめる）
            import czi_summary as cs
            import czi_summary_gui
            lines.append(f"summary template: {os.path.exists(cs.TEMPLATE_PATH)} {cs.TEMPLATE_PATH}")
            r = cs.build_summary(nega, czi, {s: core._guess_antibodies(czi).get(s, s) for s in cs.ANTIBODY_SLOTS},
                                 os.path.join(out_dir, "selftest_summary.pptx"))
            lines.append("summary: " + " | ".join(
                f"{cs.SOURCE_LABELS[sl['source']]} {sl['whites']}" for sl in r["slides"]))
            names = {s: core._guess_antibodies(czi).get(s, s) for s in cs.ANTIBODY_SLOTS}
            names["DAPI"] = cs.default_dapi_name(czi)
            r2 = cs.build_summary(None, czi, names, os.path.join(out_dir, "selftest_summary_dapi.pptx"),
                                  nega_slide=False, dapi=True)
            lines.append(f"summary (DAPI on, slide 2 off): slides={len(r2['slides'])} "
                         f"whites={r2['slides'][0]['whites']}")
            dlg = czi_summary_gui.SummaryDialog(win, czi)
            dlg.set_file("nega", nega)
            lines.append(f"summary dialog: save_enabled={dlg.btn_save.isEnabled()}")
        lines.append("OK")
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("FAILED")
        code = 1
    with open(os.path.join(out_dir, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CZI 図作成 GUI")
    ap.add_argument("czi", nargs="?", help="最初に開く .czi")
    ap.add_argument("--engine", help="run_analysis_9th.py のパス（既定は同じフォルダ）")
    ap.add_argument("--selftest", metavar="OUT_DIR", help="動作確認だけして終了（.exe の検証用）")
    ap.add_argument("--nega", help="（--selftest と一緒に）pptx データまとめも確かめるときの Nega の .czi")
    a = ap.parse_args(argv)
    if a.engine:
        core.load_engine(a.engine)
    if a.selftest:
        return selftest(a.czi, a.selftest, a.nega)
    sys.excepthook = _excepthook
    app = QApplication.instance() or QApplication(sys.argv)
    setup_app_font(app)
    win = MainWindow()
    win.show()
    if a.czi:
        win.open_file(a.czi)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
