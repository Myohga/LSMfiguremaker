# -*- coding: utf-8 -*-
"""
czi_summary_gui.py
==================
「pptx データまとめ」の画面（czi_summary.py の上に載せる薄い GUI）。
メイン画面（czi_figure_gui.py）の「pptx データまとめ…」から開く。

  Nega と実験画像の .czi を選ぶ → 抗体名を確かめる → プレビューで確かめて → pptx を保存
  pptx は 2 枚：1 枚目は White を実験画像から、2 枚目は White を Nega から決める（表示はどちらも実験画像）。
"""
from __future__ import annotations

import os
import traceback

from qtpy.QtCore import QSettings, Qt, QTimer
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QVBoxLayout,
)

import czi_figure_core as core
import czi_summary as cs


def _pixmap(img) -> QPixmap:
    img = img.convert("RGB")
    q = QImage(img.tobytes("raw", "RGB"), img.width, img.height, 3 * img.width,
               QImage.Format.Format_RGB888)
    return QPixmap.fromImage(q.copy())


class SummaryDialog(QDialog):
    def __init__(self, parent=None, exp_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("pptx データまとめ（Nega ＋ 実験画像 → 7〜8 パネル × 1〜2 枚）")
        self.settings = QSettings("czi_figure", "czi_figure_gui")
        self.whites: dict[str, dict[str, dict]] = {}     # {"exp": {slot: 結果}, "nega": {...}}
        self._pix = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.update_preview)

        lay = QVBoxLayout(self)

        # ---- ファイル ----
        box_f = QGroupBox("画像（.czi）")
        ff = QFormLayout(box_f)
        self.ed_nega, self.ed_exp = QLineEdit(), QLineEdit()
        for ed, label, key in ((self.ed_nega, "Nega（陰性対照・noAb）", "nega"),
                               (self.ed_exp, "実験画像（本染色）", "exp")):
            ed.setReadOnly(True)
            ed.setPlaceholderText("「参照…」で選んでください")
            row = QHBoxLayout()
            b = QPushButton("参照…")
            b.clicked.connect(lambda _=False, k=key: self.choose(k))
            row.addWidget(ed, 1)
            row.addWidget(b)
            ff.addRow(label, row)
        lay.addWidget(box_f)

        # ---- 作るもの ----
        box_s = QGroupBox("作るもの")
        hs = QHBoxLayout(box_s)
        self.cb_nega_slide = QCheckBox("2 枚目（White を Nega から決めたスライド）も作る")
        self.cb_nega_slide.setChecked(self.settings.value("summary_nega_slide", True, type=bool))
        self.cb_nega_slide.setToolTip("オフにすると 1 枚目（White を実験画像から）だけを作ります。Nega の .czi は不要になります")
        self.cb_dapi = QCheckBox("DAPI（Hoechst）のパネルを入れる")
        self.cb_dapi.setChecked(self.settings.value("summary_dapi", False, type=bool))
        self.cb_dapi.setToolTip("オンにすると下段を 4 枚にそろえ、右端に DAPI の単染色（白黒）を入れます。"
                                "White の枠にも DAPI の値が入ります")
        for cb in (self.cb_nega_slide, self.cb_dapi):
            cb.toggled.connect(self._switch_changed)
            hs.addWidget(cb)
        hs.addStretch(1)
        lay.addWidget(box_s)

        # ---- 抗体名と White ----
        self.box_a = box_a = QGroupBox()
        g = QGridLayout(box_a)
        heads = ("色素", "抗体名（タイトル）", "1 枚目：White（実験画像から）", "2 枚目：White（Nega から）", "")
        for col, t in enumerate(heads):
            g.addWidget(QLabel(f"<b>{t}</b>"), 0, col)
        self.rows = {}
        for r, slot in enumerate(cs.active_slots(True), start=1):
            rgb = core.parse_hex(cs.title_hex(cs.SUMMARY_COLORS[slot]))
            lab = QLabel(f"■ {slot}" if slot != "DAPI" else "□ DAPI")
            lab.setStyleSheet(f"color: rgb{rgb}; font-weight: bold;")
            name = QLineEdit()
            name.textChanged.connect(self.schedule)
            v_exp, v_nega, warn = QLabel("—"), QLabel("—"), QLabel("")
            warn.setStyleSheet("color:#c00000;")
            for col, w in enumerate((lab, name, v_exp, v_nega, warn)):
                g.addWidget(w, r, col)
            self.rows[slot] = {"name": name, "exp": v_exp, "nega": v_nega, "warn": warn,
                               "widgets": (lab, name, v_exp, v_nega, warn)}
        g.setColumnStretch(4, 1)
        lay.addWidget(box_a)

        # ---- そのほか ----
        box_o = QGroupBox("そのほか")
        fo = QFormLayout(box_o)
        self.cmb_blend = QComboBox()
        for k, t in (("screen", "スクリーン（既定）"), ("add", "加算"), ("max", "最大値")):
            self.cmb_blend.addItem(t, k)
        self.cmb_blend.currentIndexChanged.connect(self.schedule)
        fo.addRow("重なりの合成", self.cmb_blend)
        self.sp_pct = QDoubleSpinBox()
        self.sp_pct.setRange(0.001, 5.0)
        self.sp_pct.setDecimals(3)
        self.sp_pct.setSingleStep(0.01)
        self.sp_pct.setSuffix(" %")
        self.sp_pct.setKeyboardTracking(False)
        self.sp_pct.setValue(self.settings.value("summary_white_percent", cs.WHITE_TARGET_PERCENT, type=float))
        self.sp_pct.setToolTip("ZEN の Best Fit の White(%) と同じ意味：その画像で White より明るい画素の割合。\n"
                               "1 枚目・2 枚目とも同じ値を使います（既定 0.25 % ＝ ZEN の設定）")
        self.sp_pct.valueChanged.connect(self._pct_changed)
        fo.addRow("White（%）", self.sp_pct)
        self._update_box_title()
        self.ed_comment = QPlainTextEdit()
        self.ed_comment.setPlaceholderText("（任意）両方のスライドの下のコメント枠に入れる文字。空なら枠だけ置きます")
        self.ed_comment.setFixedHeight(56)
        fo.addRow("コメント", self.ed_comment)
        lay.addWidget(box_o)

        # ---- プレビューと警告 ----
        prow = QHBoxLayout()
        prow.addWidget(QLabel("プレビュー"))
        self.cmb_prev = QComboBox()
        self.cmb_prev.addItem("1 枚目（White を実験画像から）", "exp")
        self.cmb_prev.addItem("2 枚目（White を Nega から）", "nega")
        self.cmb_prev.currentIndexChanged.connect(self.schedule)
        prow.addWidget(self.cmb_prev)
        prow.addStretch(1)
        lay.addLayout(prow)
        self.preview = QLabel("Nega と実験画像を選ぶと、ここに 7 パネルのプレビューが出ます")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(300)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#f4f4f4; color:#666;")
        lay.addWidget(self.preview, 1)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#c00000;")
        lay.addWidget(self.lbl_warn)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_save = QPushButton("pptx を保存…")
        self.btn_save.setStyleSheet("font-weight:bold; padding:6px 16px;")
        self.btn_save.clicked.connect(self.save)
        self.btn_save.setEnabled(False)
        b_close = QPushButton("閉じる")
        b_close.clicked.connect(self.close)
        btns.addWidget(self.btn_save)
        btns.addWidget(b_close)
        lay.addLayout(btns)

        self.resize(1080, 940)
        self._apply_switches()
        if exp_path:
            self.set_file("exp", exp_path)

    # ---------------------------------------------------------------- ファイル
    def choose(self, which: str):
        key = f"summary_{which}_dir"
        start = self.settings.value(key, os.path.expanduser("~/Downloads"), type=str)
        title = "Nega（陰性対照）の .czi を選ぶ" if which == "nega" else "実験画像の .czi を選ぶ"
        path, _ = QFileDialog.getOpenFileName(self, title, start, "CZI (*.czi)")
        if path:
            self.settings.setValue(key, os.path.dirname(path))
            self.set_file(which, path)

    def set_file(self, which: str, path: str):
        (self.ed_nega if which == "nega" else self.ed_exp).setText(path)
        if which == "exp":
            guessed = core._guess_antibodies(path)
            guessed["DAPI"] = cs.default_dapi_name(path)
            for slot, row in self.rows.items():
                if not row["name"].text().strip():
                    row["name"].setText(guessed.get(slot, slot))
        self.recompute()

    def paths(self) -> tuple[str, str]:
        return self.ed_nega.text().strip(), self.ed_exp.text().strip()

    def names(self) -> dict[str, str]:
        return {s: (r["name"].text().strip() or s) for s, r in self.rows.items()}

    def dapi(self) -> bool:
        return self.cb_dapi.isChecked()

    def nega_slide(self) -> bool:
        return self.cb_nega_slide.isChecked()

    def slots(self) -> tuple[str, ...]:
        return cs.active_slots(self.dapi())

    def _switch_changed(self, _v=None):
        self.settings.setValue("summary_nega_slide", self.nega_slide())
        self.settings.setValue("summary_dapi", self.dapi())
        self._apply_switches()
        self.recompute()

    def _apply_switches(self):
        """スイッチに合わせて、DAPI の行・Nega の欄・プレビューの選択肢を出し入れする。"""
        for w in self.rows["DAPI"]["widgets"]:
            w.setEnabled(self.dapi())
        self.ed_nega.setPlaceholderText("「参照…」で選んでください" if self.nega_slide()
                                        else "（2 枚目を作らないときは不要。選べば整合チェックをします）")
        self.cmb_prev.model().item(1).setEnabled(self.nega_slide())
        if not self.nega_slide():
            self.cmb_prev.setCurrentIndex(0)
        n_pan = 8 if self.dapi() else 7
        self.btn_save.setText(f"pptx を保存…（{2 if self.nega_slide() else 1} 枚・{n_pan} パネル）")

    # ---------------------------------------------------------------- 計算と表示
    def percent(self) -> float:
        return float(self.sp_pct.value())

    def _update_box_title(self):
        self.box_a.setTitle(f"抗体と White（その画像で、White より明るい画素が {self.percent():g} % になる値）")

    def _pct_changed(self, v):
        self.settings.setValue("summary_white_percent", float(v))
        self._update_box_title()
        self.recompute()

    def recompute(self):
        nega, exp = self.paths()
        slots = self.slots()
        if not exp or (self.nega_slide() and not nega):
            self.btn_save.setEnabled(False)
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            warns = []
            self.whites = {}
            for src in (("exp", "nega") if nega else ("exp",)):
                res, w = cs.compute_whites(nega, exp, {s: src for s in slots}, slots=slots,
                                           percent=self.percent())
                self.whites[src] = res
                if src == "exp" or self.nega_slide():
                    warns += w
            if nega:
                warns += cs.check_pair(nega, exp, slots)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "計算エラー", f"{e}\n\n{traceback.format_exc()}")
            return
        QApplication.restoreOverrideCursor()
        for slot, row in self.rows.items():
            notes, which = [], []
            for k, src in enumerate(("exp", "nega"), 1):
                r = self.whites.get(src, {}).get(slot) if slot in slots else None
                if src == "nega" and not self.nega_slide():
                    row[src].setText("（作らない）")
                    continue
                row[src].setText(f"<b>{r['V']}</b>　（{r['fraction'] * 100:.4f} %）" if r else "—")
                if r and r["warn"]:
                    notes.append(r["warn"])
                    which.append(f"{k} 枚目")
            row["warn"].setText(f"飽和あり（{'・'.join(which)}）" if which else "")
            row["warn"].setToolTip("\n".join(notes))
        self.lbl_warn.setText("\n".join("⚠ " + w for w in warns))
        need = ("exp", "nega") if self.nega_slide() else ("exp",)
        self.btn_save.setEnabled(all(all(s in self.whites.get(src, {}) for s in slots) for src in need))
        self.schedule()

    def schedule(self):
        self._timer.start()

    def update_preview(self):
        nega, exp = self.paths()
        src = self.cmb_prev.currentData()
        res = self.whites.get(src, {})
        if not (exp and all(s in res for s in self.slots())):
            return
        try:
            img = cs.render_preview(exp, {s: r["V"] for s, r in res.items()}, self.names(),
                                    blend=self.cmb_blend.currentData(), dapi=self.dapi())
        except Exception as e:
            self.preview.setText(f"プレビューを作れませんでした: {e}")
            return
        self._pix = _pixmap(img)
        self._show_pix()

    def _show_pix(self):
        if self._pix is not None:
            self.preview.setPixmap(self._pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show_pix()

    # ---------------------------------------------------------------- 保存
    def save(self):
        nega, exp = self.paths()
        out_dir = self.settings.value("summary_out_dir", core.DEFAULT_OUT_DIR, type=str)
        path, _ = QFileDialog.getSaveFileName(self, "pptx を保存", cs.default_summary_path(exp, out_dir),
                                              "PowerPoint (*.pptx)")   # 既存ファイルは Qt が上書き確認する
        if not path:
            return
        if not path.lower().endswith(".pptx"):
            path += ".pptx"
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            r = cs.build_summary(nega or None, exp, self.names(), path, blend=self.cmb_blend.currentData(),
                                 comment=self.ed_comment.toPlainText().strip(), percent=self.percent(),
                                 nega_slide=self.nega_slide(), dapi=self.dapi())
            QApplication.restoreOverrideCursor()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "保存エラー", f"{e}\n\n{traceback.format_exc()}")
            return
        self.settings.setValue("summary_out_dir", os.path.dirname(path))
        msg = f"保存しました（{len(r['slides'])} 枚）:\n{path}"
        if r["warnings"]:
            msg += "\n\n注意:\n" + "\n".join("・" + w for w in r["warnings"])
        QMessageBox.information(self, "pptx データまとめ", msg)
