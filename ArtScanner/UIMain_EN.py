import ctypes
import json
import os
import sys
import time

import mouse
import win32api
import win32gui
from PyQt5.QtCore import (pyqtSignal, pyqtSlot, QObject, QThread,
                          QMutex, QWaitCondition)
from PyQt5.QtGui import (QMovie, QPixmap)
from PyQt5.QtWidgets import (QMainWindow, QApplication, QDialog)

import ocr_EN
import utils
from art_saver_EN import ArtDatabase
from art_scanner_logic import ArtScannerLogic, GameInfo
from rcc import About_Dialog_EN
from rcc import Help_Dialog_EN
from rcc.MainWindow_EN import Ui_MainWindow


class AboutDlg(QDialog, About_Dialog_EN.Ui_Dialog):
    def __init__(self, parent=None):
        super(AboutDlg, self).__init__(parent)
        self.setupUi(self)


class HelpDlg(QDialog, Help_Dialog_EN.Ui_Dialog):
    def __init__(self, parent=None):
        super(HelpDlg, self).__init__(parent)
        self.setupUi(self)


class UIMain(QMainWindow, Ui_MainWindow):
    captureWindowSignal = pyqtSignal()
    startScanSignal = pyqtSignal(dict)
    initializeSignal = pyqtSignal()
    detectGameInfoSignal = pyqtSignal()

    def __init__(self):
        super(UIMain, self).__init__()
        self.setupUi(self)

        self.exportFileName = ''
        self.gif = QMovie(':/rcc/rcc/loading.gif')
        self.picOk = QPixmap(':/rcc/rcc/ok.png')

        # 连接按钮
        self.pushButton.clicked.connect(self.startScan)
        self.pushButton_2.clicked.connect(self.captureWindow)
        self.pushButton_3.clicked.connect(self.showHelpDlg)
        self.pushButton_4.clicked.connect(self.showExportedFile)
        self.action_help.triggered.connect(self.showHelpDlg)
        self.action_about.triggered.connect(self.showAboutDlg)

        # 创建工作线程
        self.worker = Worker()
        self.workerThread = QThread()
        self.worker.moveToThread(self.workerThread)

        self.worker.printLog.connect(self.printLog)
        self.worker.printErr.connect(self.printErr)
        self.worker.working.connect(self.onWorking)
        self.worker.endWorking.connect(self.endWorking)
        self.worker.endInit.connect(self.endInit)
        self.worker.endScan.connect(self.endScan)

        self.initializeSignal.connect(self.worker.initEngine)
        self.detectGameInfoSignal.connect(self.worker.detectGameInfo)
        self.startScanSignal.connect(self.worker.scanArts)

        self.workerThread.start()

        self.initialize()

    # 通知工作线程进行初始化
    def initialize(self):
        self.pushButton.setEnabled(False)
        self.pushButton_2.setEnabled(False)
        self.initializeSignal.emit()

    @pyqtSlot()
    def endInit(self):
        self.pushButton.setEnabled(True)
        self.pushButton_2.setEnabled(True)

    @pyqtSlot()
    def onWorking(self):
        self.label.setMovie(self.gif)
        self.gif.start()

    @pyqtSlot()
    def endWorking(self):
        self.label.setPixmap(self.picOk)

    @pyqtSlot()
    def showHelpDlg(self):
        dlg = HelpDlg(self)
        point = self.rect().topRight()
        globalPoint = self.mapToGlobal(point)
        dlg.move(globalPoint)
        return dlg.show()

    @pyqtSlot()
    def showAboutDlg(self):
        dlg = AboutDlg(self)
        return dlg.show()

    @pyqtSlot(str)
    def printLog(self, log: str):
        self.textBrowser_3.append(log)
        QApplication.processEvents()

    @pyqtSlot(str)
    def printErr(self, err: str):
        self.textBrowser_3.append(f'<font color="red">{err}</font>')

    @pyqtSlot()
    def captureWindow(self):
        self.detectGameInfoSignal.emit()

    @pyqtSlot()
    def startScan(self):
        info = {
            "star": [self.checkBox_5.isChecked(),
                     self.checkBox_4.isChecked(),
                     self.checkBox_3.isChecked(),
                     self.checkBox_2.isChecked(),
                     self.checkBox.isChecked()],
            "levelMin": self.spinBox.value(),
            "levelMax": self.spinBox_2.value(),
            "delay": self.doubleSpinBox.value(),
            "exporter": (0 if self.radioButton.isChecked() else
                         1 if self.radioButton_2.isChecked() else
                         2 if self.radioButton_3.isChecked() else -1)
        }

        self.setUIEnabled(False)

        self.startScanSignal.emit(info)

    def setUIEnabled(self, e: bool):
        self.pushButton.setEnabled(e)
        self.checkBox.setEnabled(e)
        self.checkBox_2.setEnabled(e)
        self.checkBox_3.setEnabled(e)
        self.checkBox_4.setEnabled(e)
        self.checkBox_5.setEnabled(e)

        self.spinBox.setEnabled(e)
        self.spinBox_2.setEnabled(e)
        self.doubleSpinBox.setEnabled(e)

        self.radioButton.setEnabled(e)
        self.radioButton_2.setEnabled(e)
        self.radioButton_3.setEnabled(e)

    @pyqtSlot(str)
    def endScan(self, filename: str):
        self.setUIEnabled(True)
        self.exportFileName = filename

    @pyqtSlot()
    def showExportedFile(self):
        if self.exportFileName != '':
            s = "/select, " + os.path.abspath(self.exportFileName)
            win32api.ShellExecute(None, "open", "explorer.exe", s, None, 1)
        else:
            self.printErr("No exported file")


class Worker(QObject):
    printLog = pyqtSignal(str)
    printErr = pyqtSignal(str)
    working = pyqtSignal()
    endWorking = pyqtSignal()
    endInit = pyqtSignal()
    endScan = pyqtSignal(str)

    def __init__(self):
        super(Worker, self).__init__()
        self.isQuit = False
        self.workingMutex = QMutex()
        self.cond = QWaitCondition()
        self.isInitialized = False
        self.isWindowCaptured = False

        # in initEngine
        self.game_info = None
        self.model = None
        self.bundle_dir = None

        # init in scanArts
        self.art_id = 0
        self.saved = 0
        self.skipped = 0
        self.failed = 0
        self.star_dist = [0, 0, 0, 0, 0]
        self.star_dist_saved = [0, 0, 0, 0, 0]
        self.detectSettings = None

    @pyqtSlot()
    def initEngine(self):
        self.working.emit()

        # yield the thread
        time.sleep(0.1)
        self.log('initializing, please wait...')

        # 创建文件夹
        os.makedirs('artifacts_EN', exist_ok=True)
        self.log('Checking DPI settings...')
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                self.error('It is detected that the process DPI setting is not supported.'
                           '(maybe the system version is lower than Win10)')
                self.error('The program will continue...')
            except:
                self.error('It is detected that reading the system DPI setting is not supported.'
                           '(maybe the system version is lower than Win8) ')
                self.error('The program will continue...')

        self.log('Trying to capture the window...')

        self.detectGameInfo()

        self.log('Initializing the OCR model...')
        if len(sys.argv) > 1:
            self.bundle_dir = sys.argv[1]
        else:
            self.bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))

        self.model = ocr_EN.OCR(model_weight=os.path.join(self.bundle_dir,
                                                          'weights-improvement-EN-81-1.00.hdf5'))

        self.log('Initialize is finished.')
        if self.isWindowCaptured:
            self.log('The window has been captured, '
                     'please check that the number of rows and columns is correct before start scanning.')
            self.log(f'rows: {self.game_info.art_rows} , columns: {self.game_info.art_cols}')
            self.log("If that's wrong, please change the resolution and try again")
        else:
            self.error('The window is not captured, please recapture the window before start scanning.')

        self.log('Please open Bag - Artifacts and turn the page to the top before start scanning.')
        self.endWorking.emit()
        self.endInit.emit()

    # 捕获窗口与计算边界
    @pyqtSlot()
    def detectGameInfo(self):
        self.working.emit()
        hwnd = self.captureWindow()
        if self.isWindowCaptured:
            self.game_info = GameInfo(hwnd)
            if self.game_info.w == 0 or self.game_info.h == 0:
                self.isWindowCaptured = False
                self.error("The current Genshin Impact window is in full-screen mode or minimized, "
                           "please adjust and recapture the window.")
            else:
                self.game_info.calculateCoordinates()
        self.endWorking.emit()

    # 捕获窗口
    def captureWindow(self) -> int:
        hwnd = win32gui.FindWindow("UnityWndClass", "Genshin Impact")
        if hwnd > 0:
            self.isWindowCaptured = True
            self.log('Capture window succeeded.')
        else:
            self.isWindowCaptured = False
            self.error('Capture window failed.')
        return hwnd

    @pyqtSlot(dict)
    def scanArts(self, info: dict):
        self.working.emit()
        if not self.isWindowCaptured:
            self.error('The window is not captured, please recapture the window.')
            self.endScan.emit('')
            self.endWorking.emit()
            return

        self.model.setScaleRatio(self.game_info.scale_ratio)

        if info['levelMin'] > info['levelMax']:
            self.error('The min and max settings are incorrect.')
            self.endScan.emit('')
            self.endWorking.emit()
            return
        self.detectSettings = info
        artifactDB = ArtDatabase()
        artScanner = ArtScannerLogic(self.game_info)

        exporter = [artifactDB.exportGenshinArtJSON,
                    artifactDB.exportMingyuLabJSON,
                    artifactDB.exportGenshinOptimizerJSON][info['exporter']]
        export_name = ['artifacts.genshinart.json',
                       'artifacts.mingyulab.json',
                       'artifacts.genshin-optimizer.json'][info['exporter']]

        mouse.on_middle_click(artScanner.interrupt)

        self.log('Scanning will start in 3 seconds...')
        time.sleep(1)
        utils.setWindowToForeground(self.game_info.hwnd)

        self.log('3...')
        time.sleep(1)
        self.log('2...')
        time.sleep(1)
        self.log('1...')
        time.sleep(1)

        self.log('Aligning...')
        artScanner.alignFirstRow()
        self.log('Complete, scan will start now.')
        time.sleep(0.5)

        start_row = 0
        self.art_id = 0
        self.saved = 0
        self.skipped = 0
        self.failed = 0
        self.star_dist = [0, 0, 0, 0, 0]
        self.star_dist_saved = [0, 0, 0, 0, 0]

        def artscannerCallback(art_img):
            detectedInfo = self.model.detect_info(art_img)
            self.star_dist[detectedInfo['star'] - 1] += 1
            detectedLevel = utils.decodeValue(detectedInfo['level'])

            detectedStar = utils.decodeValue(detectedInfo['star'])

            if not ((self.detectSettings['levelMin'] <= detectedLevel <= self.detectSettings['levelMax']) and
                    (self.detectSettings['star'][detectedStar - 1])):
                self.skipped += 1
            elif artifactDB.add(detectedInfo, art_img):
                self.saved += 1
                self.star_dist_saved[detectedInfo['star'] - 1] += 1
            else:
                art_img.save(f'artifacts_EN/fail_{self.art_id}.png')
                s = json.dumps(detectedInfo, ensure_ascii=False)
                with open(f"artifacts_EN/fail_{self.art_id}.json", "wb") as f:
                    f.write(s.encode('utf-8'))
                self.failed += 1
            self.art_id += 1
            self.log(f" Scanned: {self.art_id}, Saved: {self.saved}, Skipped: {self.skipped}")

        try:
            while True:
                if artScanner.stopped or not artScanner.scanRows(rows=range(start_row, self.game_info.art_rows),
                                                                 callback=artscannerCallback) or start_row != 0:
                    break
                start_row = self.game_info.art_rows - artScanner.scrollToRow(self.game_info.art_rows, max_scrolls=20,
                                                                             extra_scroll=int(
                                                                                 self.game_info.art_rows > 5),
                                                                             interval=self.detectSettings['delay'])
                if start_row == self.game_info.art_rows:
                    break
            if artScanner.stopped:
                self.log('Interrupted')
            else:
                self.log('Completed')
        except Exception as e:
            self.error(repr(e))
            self.log('Stopped with an Error.')

        if self.saved != 0:
            exporter(export_name)
        self.log(f'Scanned: {self.saved}')
        self.log(f'  - Saved:   {self.saved}')
        self.log(f'  - Skipped: {self.skipped}')
        self.log(f'Failed: {self.failed}')
        self.log('The failed result has been stored in the folder artifacts_EN.')

        self.log('Star: (Saved / Scanned)')
        self.log(f'5: {self.star_dist_saved[4]} / {self.star_dist[4]}')
        self.log(f'4: {self.star_dist_saved[3]} / {self.star_dist[3]}')
        self.log(f'3: {self.star_dist_saved[2]} / {self.star_dist[2]}')
        self.log(f'2: {self.star_dist_saved[1]} / {self.star_dist[1]}')
        self.log(f'1: {self.star_dist_saved[0]} / {self.star_dist[0]}')

        del artifactDB
        self.endScan.emit(export_name)
        self.endWorking.emit()

    def log(self, content: str):
        self.printLog.emit(content)

    def error(self, err: str):
        self.printErr.emit(err)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    uiMain = UIMain()
    uiMain.show()
    app.exec()
