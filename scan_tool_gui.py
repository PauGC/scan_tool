#!/usr/bin/env python3

from argparse import ArgumentParser
import colorsys
from datetime import datetime
import json
import numpy as np
import os
import pyqtgraph as pg
import re
import sys
from threading import Thread

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

try:
    import pydoocs
except Exception as err:
    print(err)
    pass

from scan_classes import SimpleScan


def setWidgetValue(parent, name: str, value) -> None:
    if name in ['scan_type', 'mode', 'screen_station']:
        widget = parent.findChild(QComboBox, name)
        try:
            widget.setCurrentText(str(value))
        except:
            widget = parent.parent.findChild(QComboBox, name)
            try:
                widget.setCurrentText(str(value))
            except:
                pass
    elif name in ['samples', 'scan_steps', 'background_samples']:
        widget = parent.findChild(QSpinBox, name)
        try:
            widget.setValue(int(value))
        except:
            widget = parent.parent.findChild(QComboBox, name)
            try:
                widget.setValue(int(value))
            except:
                pass
    elif name == 'save':
        widget = parent.findChild(QCheckBox, name)
        widget.setChecked(bool(value))
    elif name == 'file_tag':
        widget = parent.findChild(QLineEdit, name)
        widget.setText(str(value))
    elif name == 'comment':
        widget = parent.findChild(QTextEdit, name)
        widget.setText(str(value))


def fillActuatorTree(parent, **kwargs) -> None:
    item = QTreeWidgetItem([kwargs['address_sp'], ""])
    for label, child in kwargs.items():
        if label == 'values':
            item_child = QTreeWidgetItem([label, ", ".join([str(val) for val in child])])
        else:
            item_child = QTreeWidgetItem([label, str(child)])
        item.addChild(item_child)
    parent.actuator_tree.addTopLevelItem(item)


class ConfigBox(QGroupBox):
    def __init__(self, parent):
        super().__init__('Configuration / Controls', parent)
        self.parent = parent
        self.setFixedHeight(350)
        self.scan_type = QComboBox(self)
        self.scan_type.setObjectName("scan_type")
        self.scan_type.addItems(['fixed-point',
                                 'simple scan'])
        self.scan_type.setCurrentText('simple scan')
        self.op_mode = QComboBox(self)
        self.op_mode.setObjectName("mode")
        self.op_mode.addItems(['manual', 'paused', 'automatic'])
        self.op_mode.setCurrentText('with pause')
        self.samples_per_step = QSpinBox(self)
        self.samples_per_step.setObjectName('samples')
        self.samples_per_step.setRange(1, 5000)
        self.samples_per_step.setValue(10)
        self.scan_steps = QSpinBox(self)
        self.scan_steps.setObjectName('scan_steps')
        self.scan_steps.setRange(1, 101)
        self.scan_steps.setValue(11)
        self.background_activate = QCheckBox('Background:')
        self.background_activate.setChecked(True)
        self.background_samples = QSpinBox()
        self.background_samples.setRange(1, 20)
        self.background_samples.setValue(10)
        self.background_samples.setEnabled(True)
        self.background_samples.setObjectName('background_samples')
        self.save_file_cb = QCheckBox("Save file")
        self.save_file_cb.setObjectName('save')
        self.save_file_cb.setChecked(True)
        self.file_tag = QLineEdit()
        self.file_tag.setEnabled(True)
        self.file_tag.setMaximumWidth(100)
        self.file_tag.setObjectName('file_tag')
        self.file_comment = QTextEdit()
        self.file_comment.setEnabled(True)
        self.file_comment.setMaximumHeight(53)
        self.file_comment.setObjectName('comment')
        self.act_laser_cb = QCheckBox('Act. laser')
        self.act_laser_cb.setObjectName('act_laser')
        self.beamline_cb = QComboBox()
        self.beamline_cb.setObjectName('laser_selection')
        self.beamline_cb.addItems(['FLASH3', 'FLASH2'])
        self.beamline_cb.setEnabled(False)
        self.start_scan_pb = QPushButton("START")
        self.start_scan_pb.setMinimumHeight(60)
        self.start_scan_pb.setStyleSheet('background-color: #97D856')
        self.abort_scan_pb = QPushButton("ABORT")
        self.abort_scan_pb.setMinimumHeight(60)
        self.abort_scan_pb.setEnabled(False)
        self.abort_scan_pb.setStyleSheet('background-color: #FCC4C4')
        self.initialize_scan_pb = QPushButton("INITIALIZE")
        self.load_scan_configuration_pb = QPushButton("Load configuration")
        self.save_scan_configuration_pb = QPushButton("Save configuration")

        layout = QGridLayout(self)
        layout.addWidget(QLabel("Scan type:"), 0, 0)
        layout.addWidget(self.scan_type, 0, 1)
        layout.addWidget(QLabel(""), 0, 2, 4, 1)
        layout.addWidget(self.start_scan_pb, 0, 3, 2, 1)
        layout.addWidget(QLabel("Mode:"), 1, 0)
        layout.addWidget(self.op_mode, 1, 1)
        self.samples_label = QLabel("Samples / step:")
        layout.addWidget(self.samples_label, 2, 0)
        layout.addWidget(self.samples_per_step, 2, 1)
        layout.addWidget(self.abort_scan_pb, 2, 3, 2, 1)
        layout.addWidget(QLabel("Scan steps:"), 3, 0)
        layout.addWidget(self.scan_steps, 3, 1)
        layout.addWidget(self.background_activate, 4, 0)
        layout.addWidget(self.background_samples, 4, 1)
        layout.addWidget(self.initialize_scan_pb, 4, 3)
        layout.addWidget(self.act_laser_cb, 5, 0)
        laser_sel_label = QLabel("beam line:")
        laser_sel_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(laser_sel_label, 5, 1)
        layout.addWidget(self.beamline_cb, 5, 2)
        layout.addWidget(self.save_file_cb, 6, 0)
        file_tag_label = QLabel("file tag:")
        file_tag_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(file_tag_label, 6, 1)
        layout.addWidget(self.file_tag, 6, 2)
        layout.addWidget(QLabel("comment:"), 7, 0)
        layout.addWidget(self.file_comment, 7, 1, 1, 2)
        layout.addWidget(self.load_scan_configuration_pb, 8, 0, 1, 2)
        layout.addWidget(self.save_scan_configuration_pb, 8, 2, 1, 2)

        self.scan_type.currentTextChanged.connect(self.set_scan_type)
        self.background_activate.stateChanged.connect(self.set_activate_background)
        self.act_laser_cb.stateChanged.connect(self.set_act_laser)
        self.save_file_cb.stateChanged.connect(self.set_save_flag)
        self.load_scan_configuration_pb.clicked.connect(self.load_scan_configuration)
        self.save_scan_configuration_pb.clicked.connect(self.save_scan_configuration)

    def set_scan_type(self):
        if self.scan_type.currentText() == 'fixed-point':
            self.samples_label.setText('Total samples')
            self.scan_steps.setEnabled(False)
            self.op_mode.setEnabled(False)
            try:
                self.parent.actuator_box.setEnabled(False)
            except:
                pass
        else:
            self.samples_label.setText('samples / step')
            self.scan_steps.setEnabled(True)
            self.op_mode.setEnabled(True)
            try:
                self.parent.actuator_box.setEnabled(True)
            except:
                pass

    def set_activate_background(self):
        if self.background_activate.isChecked():
            self.background_samples.setEnabled(True)
        else:
            self.background_samples.setEnabled(False)

    def set_act_laser(self):
        if self.act_laser_cb.isChecked():
            self.beamline_cb.setEnabled(True)
        else:
            self.beamline_cb.setEnabled(False)

    def set_save_flag(self):
        if self.save_file_cb.isChecked():
            self.file_tag.setEnabled(True)
            self.file_comment.setEnabled(True)
        else:
            self.file_tag.setEnabled(False)
            self.file_comment.setEnabled(False)

    def block(self):
        self.start_scan_pb.setEnabled(False)
        self.start_scan_pb.setStyleSheet('background-color: #F3FFCC')
        self.abort_scan_pb.setEnabled(True)
        self.abort_scan_pb.setStyleSheet('background-color: #FC5050')
        self.scan_type.setEnabled(False)
        self.op_mode.setEnabled(False)
        self.samples_per_step.setEnabled(False)
        self.scan_steps.setEnabled(False)
        self.save_file_cb.setEnabled(False)
        self.file_tag.setEnabled(False)
        self.load_scan_configuration_pb.setEnabled(False)
        self.save_scan_configuration_pb.setEnabled(False)

    def unblock(self):
        self.start_scan_pb.setEnabled(True)
        self.start_scan_pb.setStyleSheet('background-color: #97D856')
        self.abort_scan_pb.setEnabled(False)
        self.abort_scan_pb.setStyleSheet('background-color: #FCC4C4')
        self.scan_type.setEnabled(True)
        self.samples_per_step.setEnabled(True)
        if self.scan.scan_type == 'simple scan':
            self.op_mode.setEnabled(True)
            self.scan_steps.setEnabled(True)
        self.save_file_cb.setEnabled(True)
        self.file_tag.setEnabled(True)
        self.load_scan_configuration_pb.setEnabled(True)
        self.save_scan_configuration_pb.setEnabled(True)
        self.screen_station.setEnabled(True)

    def parse(self):
        scan_params = {'scan_type': self.scan_type.currentText(),
                       'mode': self.op_mode.currentText(),
                       'samples': self.samples_per_step.value(),
                       'background_samples': (self.background_samples.value() if self.background_activate.isChecked() else 0),
                       'facility': 'FLASH',
                       'beamline': self.beamline_cb.currentText(),
                       'act_laser': int(self.act_laser_cb.isChecked()),
                       'save': int(self.save_file_cb.isChecked()),
                       'file_tag': self.file_tag.text(),
                       'comment': self.file_comment.toPlainText()}
        return scan_params

    def load_scan_configuration(self):
        dlg = QFileDialog(caption='Load scan configuration file', directory='./templates')
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fname_fullpath = dlg.selectedFiles()[0]
            with open(fname_fullpath, 'r') as jf:
                config = json.load(jf)
            if 'scan_params' in config:
                for param, value in config['scan_params'].items():
                    if param == 'save':
                        value = bool(value)
                    if value == 'None':
                        value = None
                    print(param, value)
                    setWidgetValue(parent=self, name=param, value=value)
            if 'actuator' in config:
                for params in config['actuator']:
                    fillActuatorTree(self.parent.actuator_box, **params)
            if 'sensor' in config:
                for sensor in config['sensor']:
                    self.parent.sensor_box.channels_list.addItem(sensor)
                    if 'FLASH.DIAG/CAMERA/' in sensor:
                        screen = sensor.split('/')[2]
                        if screen in [self.parent.sensor_box.screen_station.itemText(i)
                                      for i in range(self.parent.sensor_box.screen_station.count())]:
                            self.parent.sensor_box.screen_station.setCurrentText(screen)
                        if 'IMAGE_EXT' in sensor.split('/')[3]:
                            self.parent.sensor_box.mock_image_cb.setChecked(False)

    def save_scan_configuration(self):
        filename = QFileDialog.getSaveFileName(caption='Save current scan configuration', directory='./templates')[0]
        if filename:
            conf = {'scan_params': self.parse(),
                    'actuator': self.parent.actuator_box.parse(),
                    'sensor': self.parent.sensor_box.parse(),
                    'device_settings': {}}
            with open(filename, 'w') as jf:
                json.dump(conf, jf, indent=8)


class Line(QLineEdit):

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(400)

    def dropEvent(self, e):
        self.setText(e.mimeData().text())
        self.returnPressed.emit()

    def dragEnterEvent(self, e):
        e.accept()


class ActuatorBox(QGroupBox):

    def __init__(self, parent):
        super().__init__('Actuators', parent=parent)
        self.parent = parent
        self.setFixedHeight(375)
        self.sp_channel = Line(self)
        self.sp_channel.setDragEnabled(True)
        self.rbv_channel = Line(self)
        self.rbv_channel.setDragEnabled(True)
        self.start_value = QLineEdit(self)
        self.start_value.setMaximumWidth(100)
        self.start_value.setValidator(QDoubleValidator())
        self.stop_value = QLineEdit(self)
        self.stop_value.setMaximumWidth(100)
        self.stop_value.setValidator(QDoubleValidator())
        self.spacing = QComboBox()
        self.spacing.addItems(['linear', 'logarithmic', 'manual'])
        self.manual_entry = QLineEdit()
        self.manual_entry.setEnabled(False)
        self.add_actuator_pb = QPushButton('Add\nactuator', self)
        self.add_actuator_pb.setMinimumHeight(70)
        self.actuator_tree = QTreeWidget()
        self.actuator_tree.setColumnCount(2)
        self.actuator_tree.setHeaderLabels(["actuator", ""])
        self.actuator_tree.setColumnWidth(0, 390)
        self.actuator_tree.setMinimumHeight(90)
        self.remove_selected_pb = QPushButton('Remove selected')
        self.remove_all_pb = QPushButton('Remove all')
        self.load_list_pb = QPushButton('Load list')
        self.save_list_pb = QPushButton('Save list')

        layout = QGridLayout(self)
        layout.addWidget(QLabel("SP channel:"), 0, 0)
        layout.addWidget(self.sp_channel, 0, 1, 1, 5)
        layout.addWidget(QLabel("RBV channel:"), 1, 0)
        layout.addWidget(self.rbv_channel, 1, 1, 1, 5)
        layout.addWidget(QLabel("start:"), 2, 0)
        layout.addWidget(self.start_value, 2, 1)
        layout.addWidget(QLabel("stop:"), 2, 2)
        layout.addWidget(self.stop_value, 2, 3)
        layout.addWidget(QLabel("spacing:"), 3, 0)
        layout.addWidget(self.spacing, 3, 1, 1, 3)
        layout.addWidget(QLabel("manual entry:"), 4, 0)
        layout.addWidget(self.manual_entry, 4, 1, 1, 5)
        layout.addWidget(self.add_actuator_pb, 2, 4, 2, 2)
        layout.addWidget(self.actuator_tree, 5, 0, 1, 6)
        layout.addWidget(self.remove_selected_pb, 6, 0, 1, 3)
        layout.addWidget(self.remove_all_pb, 6, 3, 1, 3)
        layout.addWidget(self.load_list_pb, 7, 0, 1, 3)
        layout.addWidget(self.save_list_pb, 7, 3, 1, 3)

        self.add_actuator_pb.clicked.connect(self.add_actuator)
        self.remove_selected_pb.clicked.connect(self.remove_actuator)
        self.remove_all_pb.clicked.connect(self.clear_list)
        self.load_list_pb.clicked.connect(self.load_list)
        self.save_list_pb.clicked.connect(self.save_list)

    def add_actuator(self):
        if self.sp_channel.text() == '' or self.start_value.text() == '' or self.stop_value.text() == '':
            QMessageBox.information(self, "ActuatorGroup INFO", "SP channel, start and stop cannot be empty!!!",
                                    QMessageBox.Ok)
            return
        if self.spacing.currentText() == 'linear':
            values = list(np.linspace(float(self.start_value.text()), float(self.stop_value.text()),
                                      self.parent.config_box.scan_steps.value()))
        elif self.spacing.currentText() == 'logarithmic':
            values = list(np.logspace(float(self.start_value.text()), float(self.stop_value.text()),
                                      self.parent.config_box.scan_steps.value()))
        else:
            values = eval(self.manual_entry.text())
        actuator = {'address_sp': self.sp_channel.text(), 'address_rbv': self.rbv_channel.text(), 'values': values}
        item = QTreeWidgetItem([self.sp_channel.text(), ""])
        for label, child in actuator.items():
            if label == 'values':
                item_child = QTreeWidgetItem([label, ", ".join([str(val) for val in child])])
            else:
                item_child = QTreeWidgetItem([label, str(child)])
            item.addChild(item_child)
        self.actuator_tree.addTopLevelItem(item)
        self.sp_channel.clear()
        self.rbv_channel.clear()
        self.start_value.clear()
        self.stop_value.clear()

    def remove_actuator(self):
        selected = self.actuator_tree.selectedItems()
        if not selected: return
        for item in selected:
            if not item.parent() is None:
                parent_item = item.parent()
                self.actuator_tree.takeTopLevelItem(self.actuator_tree.indexFromItem(parent_item).row())
            else:
                self.actuator_tree.takeTopLevelItem(self.actuator_tree.indexFromItem(item).row())

    def clear_list(self):
        root = self.actuator_tree.invisibleRootItem()
        child_count = root.childCount()
        for i in range(child_count):
            item = root.child(i)
            self.actuator_tree.takeTopLevelItem(int(self.actuator_tree.indexFromItem(item).row()))

    def parse(self):
        root = self.actuator_tree.invisibleRootItem()
        child_count = root.childCount()
        actuators = []
        for i in range(child_count):
            item = root.child(i)
            actuator = {'address_sp': item.child(0).data(1, 0),
                        'address_rbv': item.child(1).data(1, 0),
                        'values': [float(e) for e in item.child(2).data(1, 0).split(',')]}
            actuators.append(actuator)
        return actuators

    def load_list(self):
        dlg = QFileDialog(caption='Load actuator list file', directory='./templates')
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fname_fullpath = dlg.selectedFiles()[0]
            with open(fname_fullpath, 'r') as jf:
                config = json.load(jf)
            if 'actuator' in config:
                for params in config['actuator']:
                    fillActuatorTree(self, **params)

    def save_list(self):
        filename = QFileDialog.getSaveFileName(caption='Save current actuator list', directory='./templates')[0]
        if filename:
            if os.path.isfile(filename):
                with open(filename, 'r') as jf:
                    conf = json.load(jf)
                conf['actuator'] = self.parse()
            else:
                conf = {'actuator': self.parse()}
            with open(filename, 'w') as jf:
                json.dump(conf, jf, indent=4)

    def change_actuator_background(self):
        self.actuator_tree.setStyleSheet('background-color: #FBFFB7')

    def restore_actuator_background(self):
        self.actuator_tree.setStyleSheet('background-color: #FFFFFF')


class SensorBox(QGroupBox):
    def __init__(self, parent):
        super().__init__('Sensors', parent=parent)
        self.parent = parent
        self.setFixedHeight(340)
        self.new_channel = Line(self)
        self.new_channel.setDragEnabled(True)
        self.channels_list = QListWidget(self)
        self.channels_list.setMinimumHeight(70)
        self.channels_list.setSortingEnabled(True)
        self.remove_channel_pb = QPushButton('Remove selected')
        self.clear_list_pb = QPushButton('Remove all')
        self.load_list_pb = QPushButton('Load list')
        self.save_list_pb = QPushButton('Save list')

        screen_groupbox = QGroupBox("Screen station settings", self)
        screen_layout = QGridLayout(self)
        screen_groupbox.setLayout(screen_layout)
        self.mock_image_cb = QCheckBox("Mock image")
        self.mock_image_cb.setChecked(True)
        self.screen_station = QComboBox(self)
        self.screen_station.setObjectName('screen_station')
        self.screen_station.addItems(['None', '8FLFMAFF', '11FLFXTDS', '8FLFDUMP', 'OTRC.55.I1'])
        self.load_camera_settings_pb = QPushButton("Load camera settings")
        self.save_camera_settings_pb = QPushButton("Save camera settings")
        self.load_ias_settings_pb = QPushButton("Load image analysis set.")
        self.save_ias_settings_pb = QPushButton("Save image analysis set.")

        layout = QGridLayout(self)
        layout.addWidget(QLabel("Add channel:"), 0, 0)
        layout.addWidget(self.new_channel, 0, 1, 1, 4)
        layout.addWidget(self.channels_list, 1, 0, 1, 6)
        layout.addWidget(self.remove_channel_pb, 2, 0, 1, 3)
        layout.addWidget(self.clear_list_pb, 2, 3, 1, 3)
        layout.addWidget(self.load_list_pb, 3, 0, 1, 3)
        layout.addWidget(self.save_list_pb, 3, 3, 1, 3)
        screen_layout.addWidget(self.mock_image_cb, 0, 0, 1, 1)
        screen_label = QLabel("Screen station:")
        screen_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        screen_layout.addWidget(screen_label, 0, 1, 1, 1)
        screen_layout.addWidget(self.screen_station, 0, 2, 1, 2)
        screen_layout.addWidget(self.load_camera_settings_pb, 1, 0, 1, 2)
        screen_layout.addWidget(self.save_camera_settings_pb, 1, 2, 1, 2)
        screen_layout.addWidget(self.load_ias_settings_pb, 2, 0, 1, 2)
        screen_layout.addWidget(self.save_ias_settings_pb, 2, 2, 1, 2)
        layout.addWidget(screen_groupbox, 4, 0, 2, 6)

        self.new_channel.returnPressed.connect(self.add_sensor_channel)
        self.remove_channel_pb.pressed.connect(self.remove_channel)
        self.clear_list_pb.clicked.connect(self.channels_list.clear)
        self.load_list_pb.clicked.connect(self.load_list)
        self.save_list_pb.clicked.connect(self.save_list)
        self.load_ias_settings_pb.clicked.connect(self.load_ias_settings)
        self.save_ias_settings_pb.clicked.connect(self.save_ias_settings)
        self.load_camera_settings_pb.clicked.connect(self.load_camera_settings)
        self.save_camera_settings_pb.clicked.connect(self.save_camera_settings)

    def add_sensor_channel(self):
        try:
            pydoocs.read(self.new_channel.text())
        except Exception as err:
            print(err)
            QMessageBox.information(self, "Sensor list INFO", "Sensor channel already included or not available!!!",
                                    QMessageBox.Ok)
        #else:
        self.channels_list.addItem(self.new_channel.text())
        self.new_channel.clear()

    def remove_channel(self):
        selected = self.channels_list.selectedItems()
        if not selected: return
        for item in selected:
            self.channels_list.takeItem(self.channels_list.row(item))

    def parse(self):
        channels = [self.channels_list.item(i).text() for i in range(self.channels_list.count())]
        screen = self.screen_station.currentText()
        if not screen is 'None':
            channels.append('FLASH.DIAG/CAMERA/' + screen + '/SPECTRUM.X.TD')
            channels.append('FLASH.DIAG/CAMERA/' + screen + '/SPECTRUM.Y.TD')
            if not self.mock_image_cb.isChecked():
                channels.append('FLASH.DIAG/CAMERA/' + screen + '/IMAGE_EXT_ZMQ')
        return channels

    def load_list(self):
        dlg = QFileDialog(caption='Load sensor list file', directory='./templates')
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_():
            fname_fullpath = dlg.selectedFiles()[0]
            with open(fname_fullpath, 'r') as jf:
                config = json.load(jf)
            if 'data_channels' in config:
                for sensor in config['data_channels']:
                    self.channels_list.addItem(sensor)
                    if 'FLASH.DIAG/CAMERA/' in sensor:
                        screen = sensor.split('/')[2]
                        if screen in [self.screen_station.itemText(i) for i in range(self.screen_station.count())]:
                            self.screen_station.setCurrentText(screen)
                        if 'IMAGE_EXT' in sensor.split('/')[3]:
                            self.mock_image_cb.setChecked(False)

    def save_list(self):
        filename = QFileDialog.getSaveFileName(caption='Save current sensor list', directory='./templates')[0]
        if filename:
            if os.path.isfile(filename):
                with open(filename, 'r') as jf:
                    conf = json.load(jf)
                conf['data_channels'] = self.parse()
            else:
                conf = {'data_channels': self.parse()}
            with open(filename, 'w') as jf:
                json.dump(conf, jf, indent=4)

    def load_ias_settings(self):
        a = 1

    def save_ias_settings(self):
        if self.screen_station.currentText() == 'None':
            QMessageBox.warning(self, 'Scan tool WARNING!', 'No screen station selected yet!!!')
            return

        filename = QFileDialog.getSaveFileName(caption='Save current image analysis server settings',
                                               directory='./templates')[0]
        """
        if filename:
            if self.scan.ias:
                settings = self.scan.ias.settings['data']
                channels = [data_struct['miscellaneous']['channel'] for data_struct in settings]
                props = [data_struct['data'] for data_struct in settings]
                ias_settings = {channel: (prop if type(prop) != np.ndarray
                                          else list(prop)) for channel, prop in zip(channels, props)}
                if os.path.isfile(filename):
                    with open(filename, 'r') as jf:
                        config = json.load(jf)
                    if 'device_settings' in config:
                        if 'image_analysis' in config['device_settings']:
                            config['device_settings']['image_analysis'].update(
                                {self.screen_station.currentText(): ias_settings})
                        else:
                            config['device_settings'].update({'image_analysis':
                                                                  {self.screen_station.currentText(): ias_settings}})
                    else:
                        config.update({'device_settings': {'image_analysis':
                                                               {self.screen_station.currentText(): ias_settings}}})
                else:
                    config = {'device_settings': {'image_analysis':
                                                               {self.screen_station.currentText(): ias_settings}}}
                with open(filename, 'w') as jf:
                    json.dump(config, jf, indent=8)
            else:
                QMessageBox.warning(self, 'Scan tool WARNING!', 'No image analysis server in use!!!')
                return
        """

    def load_camera_settings(self):
        b = 1

    def save_camera_settings(self):
        if self.screen_station.currentText() == 'None':
            QMessageBox.warning(self, 'Scan tool WARNING!', 'No screen station selected yet!!!')
            return

        filename = QFileDialog.getSaveFileName(caption='Save current image analysis server settings',
                                               directory='./templates')[0]
        """
        if filename:
            if self.scan.camera:
                settings = self.scan.camera.settings['data']
                channels = [data_struct['miscellaneous']['channel'] for data_struct in settings]
                props = [data_struct['data'] for data_struct in settings]
                ias_settings = {channel: (prop if type(prop) != np.ndarray
                                          else list(prop)) for channel, prop in zip(channels, props)}
                if os.path.isfile(filename):
                    with open(filename, 'r') as jf:
                        config = json.load(jf)
                    if 'device_settings' in config:
                        if 'camera' in config['device_settings']:
                            config['device_settings']['camera'].update(
                                {self.screen_station.currentText(): ias_settings})
                        else:
                            config['device_settings'].update(
                                {'camera': {self.screen_station.currentText(): ias_settings}})
                    else:
                        config.update({'device_settings':
                                           {'camera': {self.screen_station.currentText(): ias_settings}}})
                else:
                    config = {'device_settings': {'camera':
                                                      {self.screen_station.currentText(): ias_settings}}}
                with open(filename, 'w') as jf:
                    json.dump(config, jf, indent=8)
            else:
                raise IOError
        """

    def change_sensor_background(self):
        self.channels_list.setStyleSheet('background-color: #FBFFB7')

    def restore_sensor_background(self):
        self.channels_list.setStyleSheet('background-color: #FFFFFF')


class Plot(QWidget):

    def __init__(self, parent, scan):
        super().__init__(parent)
        self.scan = scan
        self.setMaximumSize(550, 550)
        self.s1 = pg.ScatterPlotItem(size=5, pen=pg.mkPen((0, 100, 200)), brush=None)
        self.plot_window = pg.GraphicsLayoutWidget()
        self.plot = self.plot_window.addPlot(0, 0, 1)
        self.plot.setMaximumSize(500, 500)
        self.plot.showGrid(x=True, y=True)
        self.plot.getAxis('bottom').setLabel(text='ActuatorGroup target_value')
        self.plot.getAxis('left').setLabel(text='Sensor target_value')
        self.plot.addItem(self.s1)
        layout = QHBoxLayout()
        layout.addWidget(self.plot_window)
        self.setLayout(layout)


class Gui(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle('Scan tool - python!')
        self.setMinimumSize(550, 1130)

        self.config_box = ConfigBox(parent=self)
        self.actuator_box = ActuatorBox(parent=self)
        self.sensor_box = SensorBox(parent=self)
        #self.plot = Plot(self, scan)
        self.scan = None
        self._scan_thread = None

        layout = QGridLayout(self)
        layout.addWidget(self.config_box, 0, 0)
        layout.addWidget(self.actuator_box, 1, 0)
        layout.addWidget(self.sensor_box, 2, 0)
        #layout.addWidget(self.plot, 0, 1, 2, 1)

        self.config_box.start_scan_pb.pressed.connect(self.init_scan)
        self.config_box.abort_scan_pb.pressed.connect(self.abort_scan)
        #self.config_box.initialize_scan_pb.pressed.connect(self.actuator_box.init_actuators)

        #self.scan.require_action.connect(self.require_action_dlg)
        #self.scan.done.connect(self.unblock)

    @pyqtSlot(str)
    def request_action(self, message: str):
        action = QMessageBox.question(self, "Scan tool", message, QMessageBox.Abort | QMessageBox.Ok)
        if action == 1024:
            print('do it')
        elif action == 262144:
            print('abort it')

    def init_scan(self):

        action = QMessageBox.question(self, "Scan tool", "Now it's serious: do you want to mess up FLASH?!",
                                      QMessageBox.Abort | QMessageBox.Ok)
        if action == 1024:
            config = {'scan_params': self.config_box.parse(),
                      'actuator': self.actuator_box.parse(),
                      'sensor': self.sensor_box.parse()}
            try:
                self.scan = SimpleScan(config=config, parent=self)
                self._scan_thread = Thread(target=self.scan.run, daemon=True)
                self._scan_thread.start()
                #self.scan.threaded_start()
            except Exception as err:
                QMessageBox.warning(self, 'Scan tool WARNING!', 'The scan could not be initialized!!!\n{}'.format(err))
            else:
                self.config_box.block()
                self.actuator_box.setEnabled(False)
                self.sensor_box.setEnabled(False)
        elif action == 262144:
            self.config_box.unblock()
            self.actuator_box.setEnabled(True)
            self.sensor_box.setEnabled(True)

    def abort_scan(self):
        print('abort scan')
        self.config_box.unblock()
        self.actuator_box.setEnabled(True)
        self.sensor_box.setEnabled(True)

    def unblock(self):
        self.config_box.unblock()
        self.actuator_box.setEnabled(True)
        self.sensor_box.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    myapp = Gui(None)
    ssFile = './stylesheet_white.css'
    with open(ssFile, "r") as fh:
        myapp.setStyleSheet(fh.read())
    myapp.move(200, 100)
    myapp.show()
    sys.exit(app.exec_())
