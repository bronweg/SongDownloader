import sys
import os
import json
import validators

import downloader

from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                               QLineEdit, QFileDialog, QComboBox, QMessageBox, QProgressBar)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import (QIcon, QPixmap)


class MP3DownloaderThread(QThread):
    creationStarted = Signal()
    progressUpdated = Signal(int, str)
    creationFinished = Signal()

    def __init__(self, url, audio_file):
        super().__init__()
        self.url_to_download = url
        self.mp3_to_create = audio_file

    def run(self):
        self.creationStarted.emit()
        downloader.download_song(self.url_to_download, self.mp3_to_create, self.update_progress)
        self.creationFinished.emit()

    def update_progress(self, value, label=None):
        self.progressUpdated.emit(value, label)

class SongDownloader(QWidget):
    def __init__(self):
        super().__init__()
        settings = self.load_settings()
        self.current_language = self.get_language(settings)
        self.translations = self.load_translations(self.current_language)
        self.project_path, self.project_folder = self.get_project_path(settings)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.locale_subjects = dict()
        self.direction_subjects = list()
        self.setup_ui()
        self.apply_settings(settings)
        self.change_language(self.current_language)

    @staticmethod
    def get_settings_file():
        home_dir = os.path.expanduser('~')
        filename = 'SongDownloader.json'
        return os.path.join(home_dir, filename)

    def save_settings(self, language):
        settings = {
            'language': language,
            'projectPath': self.project_path,
            'projectFolder': self.project_folder,
        }
        try:
            with open(self.get_settings_file(), 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            QMessageBox.warning(self, self.translate_key('saving_settings_warning'), str(e))

    def load_settings(self):
        settings = {
            'language': 'English',
        }
        try:
            with open(self.get_settings_file(), 'r') as f:
                settings.update(json.load(f))
        except FileNotFoundError:
            pass
        return settings

    @staticmethod
    def get_project_path(settings) -> tuple[str, str]:
        return \
            settings.get('projectPath', os.path.expanduser("~")), \
                settings.get('projectFolder', 'projects')

    def apply_settings(self, settings):
        self.langComboBox.setCurrentText(self.current_language)

        date_project_path = os.path.join(self.project_path, self.project_folder)
        self.projLineEdit.setText(date_project_path)

    @staticmethod
    def get_language(settings):
        return settings.get('language', 'English')

    @staticmethod
    def load_language_codes():
        path = 'locales/language_codes.json'
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @classmethod
    def load_language_names(cls):
        language_codes = cls.load_language_codes()
        return list(language_codes.keys())

    @classmethod
    def load_translations(cls, language_name):
        language_codes = cls.load_language_codes()
        language_code = language_codes.get(language_name, "en")
        path = f'locales/{language_code}.json'
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def translate_key(self, text_key):
        return self.translations.get(text_key, text_key)

    def setup_ui(self):
        # Update Logo
        self.logoLabel = QLabel(self)
        self.logoPixmap = QPixmap('images/logo.png')
        scaledLogoPixmap = self.logoPixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.logoLabel.setPixmap(scaledLogoPixmap)
        self.logoLabel.setFixedSize(scaledLogoPixmap.size())
        self.layout.addWidget(self.logoLabel)

        # Language selection
        self.languageLabel = QLabel()
        self.locale_subjects['language_label'] = self.languageLabel
        self.langComboBox = QComboBox()
        self.langComboBox.addItems(self.load_language_names())
        self.langComboBox.currentTextChanged.connect(self.change_language)
        langLayout = QHBoxLayout()
        langLayout.addWidget(self.languageLabel)
        langLayout.addWidget(self.langComboBox)
        self.direction_subjects.append(langLayout)
        self.layout.addLayout(langLayout)

        # Project selection
        self.projLabel = QLabel()
        self.locale_subjects['project_label'] = self.projLabel
        self.projLineEdit = QLineEdit()
        self.projButton = QPushButton()
        self.locale_subjects['choose_project'] = self.projButton
        self.projButton.clicked.connect(self.choose_project)
        self.projLayout = QHBoxLayout()
        self.projLayout.addWidget(self.projLabel)
        self.projLayout.addWidget(self.projLineEdit)
        self.projLayout.addWidget(self.projButton)
        self.direction_subjects.append(self.projLayout)
        self.layout.addLayout(self.projLayout)

        # Audio file selection
        self.downloadUrlLabel = QLabel()
        self.locale_subjects['video_url'] = self.downloadUrlLabel
        self.downloadUrlLineEdit = QLineEdit()
        self.downloadUrlLineEdit.setMinimumWidth(400)
        downloadUrlLayout = QHBoxLayout()
        downloadUrlLayout.addWidget(self.downloadUrlLabel)
        downloadUrlLayout.addWidget(self.downloadUrlLineEdit)
        self.direction_subjects.append(downloadUrlLayout)
        self.layout.addLayout(downloadUrlLayout)

        # Output file selection
        self.outputFileLabel = QLabel()
        self.locale_subjects['output_mp3_label'] = self.outputFileLabel
        self.outputFileLineEdit = QLineEdit()
        self.outputFileButton = QPushButton()
        self.outputFileButton.clicked.connect(self.create_output_audio)
        self.locale_subjects['create_mp3_button'] = self.outputFileButton
        outputFileLayout = QHBoxLayout()
        outputFileLayout.addWidget(self.outputFileLabel)
        outputFileLayout.addWidget(self.outputFileLineEdit)
        outputFileLayout.addWidget(self.outputFileButton)
        self.direction_subjects.append(outputFileLayout)
        self.layout.addLayout(outputFileLayout)

        # Process button
        self.processButton = QPushButton(self.translate_key('process_button'))
        self.locale_subjects['process_button'] = self.processButton
        self.processButton.clicked.connect(self.download_audio)
        self.layout.addWidget(self.processButton)

        # Progress Bar
        self.progressLabel = QLabel('')
        self.progressStatus = ''
        self.layout.addWidget(self.progressLabel)
        self.progressBar = QProgressBar(self)
        self.progressBar.setValue(0)  # start value
        self.progressBar.setMaximum(100)  # 100% completion
        self.layout.addWidget(self.progressBar)

    def reset_progress(self):
        self.set_progress_status('')
        self.progressBar.setValue(0)

    def choose_project(self):
        proj_path = QFileDialog.getExistingDirectory(self,
                                                     self.translate_key('choose_project'),
                                                     dir=self.projLineEdit.text())
        if proj_path:
            self.projLineEdit.setText(proj_path)

            proj_name = os.path.basename(proj_path)
            proj_parent_name = os.path.basename(os.path.dirname(proj_path))
            file_name = f'{proj_parent_name}_{proj_name}.mp3'
            file_path = os.path.join(proj_path, file_name)
            self.outputFileLineEdit.setText(file_path)

        self.reset_progress()

    def create_output_audio(self):
        file_path, _ = QFileDialog.getSaveFileName(self,
                                                   self.translate_key('create_file'),
                                                   dir=self.outputFileLineEdit.text(),
                                                   filter="Audio files (*.mp3)"
                                                   )
        if file_path:
            self.outputFileLineEdit.setText(file_path)
        self.reset_progress()

    def change_language(self, language):
        self.current_language = language
        self.translations = self.load_translations(language)

        # Update texts
        self.setWindowTitle(self.translate_key('title'))

        if self.progressStatus:
            self.progressLabel.setText(self.translate_key(self.progressStatus))

        for locale_key in self.locale_subjects:
            self.locale_subjects[locale_key].setText(self.translate_key(locale_key))

        # Update layout
        is_rtl = (language == 'עברית')
        for direction_subject in self.direction_subjects:
            direction_subject.setDirection(QHBoxLayout.RightToLeft if is_rtl else QHBoxLayout.LeftToRight)

    def download_audio(self):
        if not self.downloadUrlLineEdit.text() or not validators.url(self.downloadUrlLineEdit.text()):
            QMessageBox.warning(self, self.translate_key('error_title'), self.translate_key('url_not_valid'))
            return

        if not self.outputFileLineEdit.text() or not self.outputFileLineEdit.text().endswith('mp3'):
            QMessageBox.warning(self, self.translate_key('error_title'), self.translate_key('output_path_not_found'))
            return

        external_url = self.downloadUrlLineEdit.text()
        audio_path = self.outputFileLineEdit.text()

        try:
            self.mp3Thread = MP3DownloaderThread(external_url, audio_path)
            self.mp3Thread.creationStarted.connect(self.on_download_started)
            self.mp3Thread.progressUpdated.connect(self.update_progress_bar)
            self.mp3Thread.creationFinished.connect(self.on_download_finished)
            self.mp3Thread.start()
        except Exception as e:
            error_message = f"{self.translate_key('video_creation_failed')} {str(e)}"
            QMessageBox.warning(self, self.translate_key('error_title'), error_message)


    def on_download_started(self):
        self.processButton.setEnabled(False)
        self.save_settings(self.current_language)
        self.set_progress_status('creation')

    def set_progress_status(self, status):
        self.progressStatus = status
        self.progressLabel.setText(self.translate_key(self.progressStatus))

    def update_progress_bar(self, value, label):
        if label:
            self.set_progress_status(label)
        self.progressBar.setValue(value)

    def on_download_finished(self):
        self.set_progress_status('finished')
        self.processButton.setEnabled(True)
        QMessageBox.information(self, self.translate_key('success_title'), self.translate_key('success_message'))


if __name__ == "__main__":
    if hasattr(sys, '_MEIPASS'):
        os.chdir(sys._MEIPASS)
    app = QApplication(sys.argv)
    window = SongDownloader()
    window.show()
    sys.exit(app.exec())
