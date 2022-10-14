#!/usr/bin/env python3

from datetime import datetime
from functools import reduce
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat, count
import json
import logging
import numpy as np
from queue import Queue, Empty, Full
import re
import sys
import time
from threading import Thread, Event, Lock, Timer

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

try:
    import pydoocs
    from hlc_util import Error
except Exception as err:
    print(err)
    pass

from data_classes import Buffer, FLASHDataStruct
from actuator_classes import Laser, Actuator, ActuatorGroup


class SimpleScan(object):

    flag = None
    stop_event = Event()

    def __init__(self, config: dict = None, parent=None):
        self.parent = parent
        self.facility = None
        self.beamline = None
        self.laser = None
        self.actuator = None
        self.setpoint_values = None
        self.scan_steps = None
        self.data_channels = None
        self.data_buffer = None
        self.background_buffer = None
        self.take_background = False
        self.mode = None
        self.sequence = None
        self.dfile = None
        self.step_counter = None
        self.load_config(config=config)

    def load_config(self, config: dict):
        # actuator
        actuators = [Actuator(**params, stop_event=self.stop_event) for params in config['actuator']]
        if len(actuators) > 1:
            self.actuator = ActuatorGroup(actuators=actuators)
            values = [act['values'] for act in config['actuator']]
            self.setpoint_values = iter([[lst[i] for lst in values] for i in range(len(values[0]))])
            self.scan_steps = len(values[0])
        else:
            self.actuator = actuators[0]
            values = config['actuator'][0]['values']
            self.setpoint_values = iter(values)
            self.scan_steps = len(values)

        # data channels:
        self.data_channels = config['sensor']
        for params in config['actuator']:
            self.data_channels += [params[key] for key in ['address_sp', 'address_rbv']]

        # scan params:
        scan_params = config['scan_params']
        self.mode = bool(scan_params['mode'])
        samples = int(scan_params['samples'])
        self.data_buffer = Buffer(channels=self.data_channels,
                                  size=samples,
                                  stop_event=self.stop_event)
        background_samples = int(scan_params['background_samples'])
        if background_samples > 0:
            self.take_background = True
            self.background_buffer = Buffer(channels=self.data_channels,
                                            size=background_samples,
                                            stop_event=self.stop_event)
        if 'facility' in scan_params: self.facility = scan_params['facility']
        else: self.facility = 'FLASH'
        if 'beamline' in scan_params: self.beamline = scan_params['beamline']
        else: self.beamline = 'FLASH3'
        self.laser = Laser(facility=self.facility, beamline=self.beamline,
                           inhibit=np.invert(bool(scan_params['act_laser'])))
        file_tag = (str(scan_params['file_tag']) + '_' if 'file_tag' in scan_params else '')
        dfilename = file_tag + datetime.now().replace(microsecond=0).isoformat() + '.h5'
        if bool(scan_params['save']):
            self.dfile = FLASHDataStruct(filename=dfilename, shape=(self.scan_steps, samples),
                                         facility=self.facility, beamline=self.beamline)
        else: self.dfile = None

    def next_step(self):
        try:
            flag = next(self.sequence)
            print('Next step: {}'.format(flag))
            self.flag = flag
        except StopIteration:
            self.flag = None

    def init_scan(self):
        print('Initializing scan...')
        self.stop_event.clear()
        self.step_counter = -1
        self.sequence = iter((['set'] if self.mode != 'manual' else [])
                             + (['background'] if self.take_background else [])
                             + reduce(lambda x, y: x + y,
                                      repeat((['pause'] if self.mode != 'automatic' else [])
                                             + ['collect', 'process']
                                             + (['set'] if self.mode != 'manual' else []),
                                             self.scan_steps))[:-1])
        self.laser.block
        self.next_step()

    def set_actuator(self):
        print('Setting new values...')
        try:
            self.laser.block
            value = next(self.setpoint_values)
        except StopIteration:
            print('No more values!!!')
            self.flag = None
        else:
            self.actuator.set_value(target_value=value)
            self.step_counter += 1
            self.laser.unblock
            self.next_step()

    def collect_background(self):
        print('Taking background...')
        self.laser.block
        self.background_buffer.poll()
        while not self.background_buffer.queue.empty():
            data = self.background_buffer.queue.get()
            if not self.dfile is None: self.dfile.dump(data_struct=data, grp_name='background')
        self.next_step()

    def collect_data(self):
        print('Polling data...')
        self.laser.unblock
        self.data_buffer.poll()
        self.laser.block
        self.next_step()

    def process_data(self):
        print('Processing data...')
        i = 0
        while not self.data_buffer.queue.empty():
            data = self.data_buffer.queue.get()
            if not self.dfile is None: self.dfile.dump(data_struct=data, idx=(self.step_counter, i))
            i += 1
        self.next_step()

    def request_action(self):
        print('Requesting action...')
        if not self.parent is None:
            action = self.parent.request_action(message='Do something and press OK.')
            if action:
                time.sleep(0.5)
            else:
                time.sleep(0.5)
            print('action {}'.format(action))
        else:
            wait = True
            while wait:
                proceed = input('\nProceed with data taking [y/n]:')
                if proceed.lower()[0] == 'y':
                    wait = False
                elif proceed.lower()[0] == 'n':
                    wait = False
                    self.abort()
                else:
                    print('Option not available...')
        self.next_step()

    def run(self):
        self.init_scan()
        while self.flag and not self.stop_event.is_set():
            if self.flag == 'set': self.set_actuator()
            elif self.flag == 'background': self.collect_background()
            elif self.flag == 'pause': self.request_action()
            elif self.flag == 'collect': self.collect_data()
            elif self.flag == 'process': self.process_data()
            else: return
        print('Scan finished!')
        return

    def threaded_start(self):
        thread = Thread(target=self.run, daemon=True)
        thread.start()

    def abort(self):
        print('Aborting...')
        self.stop_event.set()
