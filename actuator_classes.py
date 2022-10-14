#!/usr/bin/env python3

from concurrent.futures import ThreadPoolExecutor
import numpy as np
import re
import time
from threading import Thread, Event, Lock, Timer

try:
    import pydoocs
    from hlc_util import Error
except Exception as err:
    print(err)
    pass


def bunch_train_part(facility: str = 'FLASH', beamline: str = 'FLASH3'):
    if facility == 'FLASH':
        if beamline == 'FLASH1':
            destination_target = 4
        elif beamline == 'FLASH2':
            destination_target = 2
        elif beamline == 'FLASH3':
            destination_target = 8
        else:
            raise Error('bunch_train_part function error: beamline not implemented!!!')
        for i in range(3):
            destination = pydoocs.read('FLASH.DIAG/TIMER/FLASHCPUTIME1.0/DESTINATION_SELECT.' + str(i + 1))['data']
            if destination == destination_target:
                return int(i + 1)
    else:
        raise Error('bunch_train_part function error: beamline not implemented!!!')


class Laser(object):

    TIMEOUT = 3

    def __init__(self, facility: str = 'FLASH', beamline: str = 'FLASH3', inhibit: bool = False):
        self.facility = facility
        self.beamline = beamline
        self._inhibit = inhibit
        self.check_args()
        self.base_addr = 'FLASH.DIAG/LASER.CONTROL/LASER' + str(self.which_laser)
        self.timer = Timer(interval=self.TIMEOUT, function=self.timeout)
        self._timeout = False

    def check_args(self):
        if self.facility == 'FLASH':
            if not self.beamline in ['FLASH1', 'FLASH2', 'FLASH3']:
                raise Error("block_laser function ERROR: facility not known!")
        else:
            raise Error('Laser class error: beamline not implemented!!!')

    @property
    def inhibit(self):
        return self._inhibit

    @inhibit.setter
    def inhibit(self, inhibit: bool):
        self._inhibit = inhibit

    @property
    def which_laser(self):
            btp = bunch_train_part(facility=self.facility, beamline=self.beamline)
            return int(pydoocs.read('FLASH.DIAG/TIMER/FLASHCPUTIME1.0/LASER_SELECT.' + str(btp))['data'])

    @property
    def rep_rate(self):
        laser = self.which_laser
        if laser == 1:
            event = 7
        elif laser == 2:
            event = 30
        divider = int(pydoocs.read('FLASH.DIAG/TIMER/FLASHCPUTIME1.0/EVENT' + str(event))['data'][3])
        if divider == 8:
            rep_rate = 1.0
        elif divider == 4:
            rep_rate = 2.0
        elif divider == 2:
            rep_rate = 5.0
        elif divider == 1 or divider == 0:
            rep_rate = 10.0
        return rep_rate

    @property
    def block(self):
        if not self.inhibit:
            try:
                self.timer.cancel()
            except:
                pass
            block_addr = '/'.join([self.base_addr, 'BLOCK_LASER'])
            is_blocked = bool(pydoocs.read(block_addr)['data'])
            if is_blocked: return
            else:
                try:
                    self.timer.start()
                except:
                    pass
                pydoocs.write(block_addr, 1)
                while not self._timeout:
                    is_blocked = bool(pydoocs.read(block_addr)['data'])
                    if not is_blocked: time.sleep(0.1)
                    else:
                        self.timer.cancel()
                        return
                raise Error('Laser class: TIMEOUT!!!')
        else:
            pass

    @property
    def unblock(self):
        if not self.inhibit:
            block_addr = '/'.join([self.base_addr, 'BLOCK_LASER'])
            is_blocked = bool(pydoocs.read(block_addr)['data'])
            if not is_blocked: return
            else:
                try:
                    self.timer.start()
                except:
                    pass
                pydoocs.write(block_addr, 0)
                while not self._timeout:
                    is_blocked = bool(pydoocs.read(block_addr)['data'])
                    if is_blocked: time.sleep(0.1)
                    else:
                        self.timer.cancel()
                        return
                raise Error('Laser class: TIMEOUT!!!')
        else:
            pass

    def timeout(self):
        self._timeout = True


class Actuator(Thread):

    busy = False
    TIMEOUT = 60

    def __init__(self, address_sp: str, address_rbv: str, stop_event: Event = None, **kwargs):
        super().__init__()
        self.address_sp = address_sp
        self.address_rbv = address_rbv
        self.target_value = None
        self.atype = 'generic'
        self.stop_event = stop_event
        self.init_event()
        self.check_args()
        self.timer = Timer(interval=self.TIMEOUT, function=self.timeout)
        self._timeout = False

    def init_event(self):
        if self.stop_event is None:
            self.stop_event = Event()
            self.stop_event.clear()
        else:
            pass

    def check_args(self):
        try:
            pydoocs.read(self.address_sp)
        except Exception as err:
            print('SimpleActuator class error: {}'.format(err))
            raise err
        else:
            if re.match(r'FLASH\.MAGNETS/MAGNET\.ML/([A-Z0-9])+/[A-Z]+\.SP', self.address_sp):
                self.atype = 'magnet'
                if not bool(pydoocs.read("/".join(self.address_sp.split('/')[:-1] + ['PS_ON']))['data']):
                    raise Exception('SimpleActuator class error: magnet is off!!!')
        try:
            pydoocs.read(self.address_rbv)
        except Exception as err:
            print('SimpleActuator class error: {}'.format(err))
            raise err

    def set_value(self, target_value):
        self.target_value = target_value
        try:
            self.timer.start()
        except:
            pass
        try:
            pydoocs.write(self.address_sp, self.target_value)
        except Exception as err:
            print('SimpleActuator class error: {}'.format(err))
            raise err
        else:
            self.run()

    def run(self):
        self.busy = True
        if self.atype == 'magnet':
            time.sleep(1.0)
            addr_idle = "/".join(self.address_sp.split('/')[:-1] + ['PS_IDLE'])
            wait = True
            while wait and not self.stop_event.is_set() and not self._timeout:
                current_value = pydoocs.read(self.address_rbv)['data']
                if not -0.05 < current_value - self.target_value < 0.05:
                    print('{}: {:.3f}'.format(self.address_rbv, current_value - self.target_value))
                    time.sleep(0.5)
                    continue
                elif not bool(pydoocs.read(addr_idle)['data']):
                    print('Polwende...')
                    time.sleep(0.5)
                    continue
                else:
                    time.sleep(0.5)
                    wait = False
                    self.timer.cancel()
                    print('Ready!')
        else:
            ring_buffer_data, ring_buffer_fit = np.zeros(10), np.zeros(10)
            counter_data, counter_fit = 0, 0
            timestamp_old = 0.0
            while True:
                wait = True
                while wait:
                    data = pydoocs.read(self.address_rbv)
                    if data['timestamp'] != timestamp_old:
                        if counter_data < 10:
                            ring_buffer_data[counter_data] = data['data']
                        else:
                            ring_buffer_data[counter_data % 10] = data['data']
                        wait = False
                        timestamp_old = data['timestamp']
                        counter_data += 1
                    else:
                        time.sleep(0.05)
                if counter_data < 2:
                    continue
                elif 1 < counter_data < 10:
                    fit = np.polyfit(np.arange(counter_data), ring_buffer_data[:counter_data], 1)
                    ring_buffer_fit[counter_fit] = fit[0]
                    counter_fit += 1
                    avg = np.average(ring_buffer_fit[:counter_fit])
                    print('{}: {:.3f}'.format(self.address_rbv, data['data'] - self.target_value))
                else:
                    fit = np.polyfit(np.arange(10), ring_buffer_data, 1)
                    ring_buffer_fit[counter_fit % 10] = fit[0]
                    counter_fit += 1
                    avg = np.average(ring_buffer_fit)
                    print('{}: {:.3f}'.format(self.address_rbv, data['data'] - self.target_value))
                if abs(avg) < 1e-2:
                    print('Ready!')
                    self.timer.cancel()
                    break
        self.busy = False
        return

    def timeout(self):
        self._timeout = True


class ActuatorGroup(Thread):

    def __init__(self, actuators: list):
        super().__init__()
        self.actuators = actuators

    def set_value(self, target_value: list):
        if len(target_value) != len(self.actuators):
            raise ValueError
        with ThreadPoolExecutor(max_workers=len(self.actuators)) as executor:
            for act, value in zip(self.actuators, target_value):
                executor.submit(act.set_value, target_value=value)
        self.run()

    def run(self):
        wait = True
        while wait:
            busy = [act.busy for act in self.actuators]
            if np.any(busy):
                time.sleep(0.1)
            else:
                wait = False
        return
