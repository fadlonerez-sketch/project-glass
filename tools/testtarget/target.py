"""Glass test target: a small Qt Widgets app with one control of each common kind.

Used by the automation and Garvis end-to-end tests. It is designed to be invisible to the user:
* it is placed far off-screen (-32000, -32000) and shown without activation (never takes focus);
* it is a tool window, so it has no taskbar button;
* every action is echoed to the `lastAction` label, so tests can verify effects through UI Automation.

    python tools/testtarget/target.py [--title "Glass Test Target"] [--onscreen]
"""
from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
    QMainWindow, QPushButton, QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


class Target(QMainWindow):
    def __init__(self, title: str):
        super().__init__()
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)

        menu = self.menuBar().addMenu("&File")
        menu.addAction("New Item", lambda: self.did("menu:New Item"))
        menu.addAction("Export", lambda: self.did("menu:Export"))
        self.menuBar().addMenu("&Help").addAction("About", lambda: self.did("menu:About"))

        central = QWidget()
        lay = QVBoxLayout(central)
        self.last = QLabel("ready")
        self.last.setObjectName("lastAction")
        lay.addWidget(self.last)

        b = QPushButton("Say Hello")
        b.setObjectName("helloButton")
        b.clicked.connect(lambda: self.did("clicked:Say Hello"))
        lay.addWidget(b)

        d = QPushButton("Open Dialog")
        d.setObjectName("dialogButton")
        d.clicked.connect(self.open_dialog)
        lay.addWidget(d)

        rm = QPushButton("Remove Me")
        rm.setObjectName("removeMe")
        rm.clicked.connect(lambda: (rm.deleteLater(), self.did("removed")))
        lay.addWidget(rm)

        self.name = QLineEdit()
        self.name.setObjectName("nameEdit")
        self.name.setAccessibleName("Name")
        self.name.textChanged.connect(lambda t: self.did(f"text:{t}"))
        lay.addWidget(self.name)

        pw = QLineEdit("hunter2")
        pw.setObjectName("passwordEdit")
        pw.setAccessibleName("Password")
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(pw)

        cb = QCheckBox("Enable feature")
        cb.setObjectName("featureCheck")
        cb.toggled.connect(lambda on: self.did(f"checked:{on}"))
        lay.addWidget(cb)

        combo = QComboBox()
        combo.setObjectName("colorCombo")
        combo.setAccessibleName("Color")
        combo.addItems(["Red", "Green", "Blue"])
        combo.currentTextChanged.connect(lambda t: self.did(f"combo:{t}"))
        lay.addWidget(combo)

        lst = QListWidget()
        lst.setObjectName("fruitList")
        lst.setAccessibleName("Fruits")
        lst.addItems(["Apple", "Banana", "Cherry", "Date"] + [f"Fruit {i}" for i in range(40)])
        lst.setFixedHeight(110)
        lst.itemSelectionChanged.connect(lambda: self.did("list:" + ",".join(i.text() for i in lst.selectedItems())))
        lay.addWidget(lst)

        tree = QTreeWidget()
        tree.setObjectName("folderTree")
        tree.setAccessibleName("Folders")
        tree.setHeaderLabel("Folder")
        root = QTreeWidgetItem(["Projects"])
        root.addChildren([QTreeWidgetItem(["Glass"]), QTreeWidgetItem(["Garvis"])])
        tree.addTopLevelItem(root)
        tree.itemExpanded.connect(lambda it: self.did(f"expanded:{it.text(0)}"))
        tree.itemCollapsed.connect(lambda it: self.did(f"collapsed:{it.text(0)}"))
        lay.addWidget(tree)

        area = QScrollArea()
        area.setObjectName("longArea")
        area.setAccessibleName("Long content")
        inner = QWidget()
        il = QVBoxLayout(inner)
        for i in range(60):
            il.addWidget(QLabel(f"Row {i}"))
        area.setWidget(inner)
        area.setFixedHeight(120)
        area.verticalScrollBar().valueChanged.connect(lambda v: self.did(f"scrolled:{v}"))
        lay.addWidget(area)

        self.setCentralWidget(central)
        self.resize(420, 760)

    def did(self, text: str) -> None:
        self.last.setText(text)

    def open_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Thing")
        dlg.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Proceed with the thing?"))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(lambda: (self.did("dialog:ok"), dlg.accept()))
        box.rejected.connect(lambda: (self.did("dialog:cancel"), dlg.reject()))
        lay.addWidget(box)
        dlg.move(self.x() + 20, self.y() + 20)
        dlg.show()
        self.did("dialog:open")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Glass Test Target")
    ap.add_argument("--onscreen", action="store_true", help="for manual debugging only")
    ap.add_argument("--protected", action="store_true", help="mark the window like Glass marks its own windows")
    args = ap.parse_args()
    app = QApplication(sys.argv[:1])
    w = Target(args.title)
    if not args.onscreen:
        w.move(-32000, -32000)
    w.show()
    if args.protected:
        import ctypes
        ctypes.windll.user32.SetPropW(ctypes.c_void_p(int(w.winId())), "ProjectGlass.Protected", ctypes.c_void_p(1))
    print("READY", int(w.winId()), flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
