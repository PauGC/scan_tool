#!/usr/bin/env python3

import collections
from copy import deepcopy
from datetime import datetime
import h5py
import numpy as np
import os
from queue import Queue
import sys
from threading import Thread, Event, Timer
import time


try:
    import pydoocs
    import pydaq
    from hlc_util import Error
except Exception as err:
    print(err)
    pass

from actuator_classes import bunch_train_part


def flatten(d, parent_key='', sep='.'):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def get_size(obj, seen=None):
    """
    Recursively finds size of objects.
    Taken from: https://goshippo.com/blog/measure-real-size-any-python-object/
    """
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, '__dict__'):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size


def current_macropulse(facility: str = 'FLASH'):
    if facility == 'FLASH':
        return int(pydoocs.read('FLASH.DIAG/TIMER/FLASHCPUTIME1.0/MACRO_PULSE_NUMBER')['data'][0])
    if facility == 'XFEL_SIM':
        return int(pydoocs.read('XFEL_SIM.DIAG/TIMER/TIME1/MACRO_PULSE_NUMBER')['data'][0])


class Buffer(Thread):

    TIMEOUT = 3
    MAX_MACRO_DELAY = 20

    def __init__(self, channels: list, size: int, sync: bool = False, stop_event: Event = None,
                 facility: str = 'FLASH', beamline: str = 'FLASH3'):
        super().__init__()
        self.channels = channels
        self._size = size
        self._sync = sync
        self.stop_event = stop_event
        self.facility = facility
        self.beamline = beamline
        self.queue = Queue(maxsize=size)
        self.hist = np.zeros(self.MAX_MACRO_DELAY)
        self.hist_count = 0
        self.buffer = {}
        self.timer = Timer(interval=self.TIMEOUT, function=self.timeout)
        self._timeout = False
        self.init_event()

    def init_event(self):
        if self.stop_event is None:
            self.stop_event = Event()
            self.stop_event.clear()
        else:
            pass

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, size):
        self._size = size
        self.queue.maxsize = size

    @property
    def sync(self):
        return self._sync

    @sync.setter
    def sync(self, sync: bool):
        self._sync = sync

    @property
    def rep_rate(self):
        btp = bunch_train_part(facility=self.facility, beamline=self.beamline)
        laser = int(pydoocs.read('FLASH.DIAG/TIMER/FLASHCPUTIME1.0/LASER_SELECT.' + str(btp))['data'])
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

    def parse_channels(self):
        cycle_out = []
        m_curr = current_macropulse(facility=self.facility)
        for addr in self.channels:
            try:
                data_struct = pydoocs.read(addr)
            except:
                self.channels = list(filter((addr).__ne__, self.channels))
            else:
                if data_struct['macropulse'] == 0:
                    data_struct['macropulse'] = m_curr
                data_struct['miscellaneous'].update({'channel': addr})
                cycle_out.append(data_struct)
        return np.array(cycle_out)

    #def poll(self):
    def run(self):
        self.parse_channels()
        if not self.channels:
            raise Exception('Buffer class ERROR: no channels given!!!')
        if self.sync:
            self.hist_count = 0
            while not self.stop_event.is_set() and not self.queue.full() and not self._timeout:
                try:
                    self.timer.start()
                    self._timeout = False
                except:
                    pass
                m_curr = current_macropulse(facility=self.facility)
                parsed_data = self.parse_channels()
                parsed_macropulses = np.array([data['macropulse'] for data in parsed_data])
                unique_macropulses = set(parsed_macropulses)
                for m in unique_macropulses:
                    if m < m_curr - self.MAX_MACRO_DELAY:
                        try:
                            del self.buffer[m]
                            continue
                        except:
                            continue
                    elif m in self.hist:
                        try:
                            del self.buffer[m]
                            continue
                        except:
                            continue
                    elif m in self.buffer.keys():
                        self.buffer[m] += list(parsed_data[np.where(parsed_macropulses == m)[0]])
                    else:
                        self.buffer.update({m: list(parsed_data[np.where(parsed_macropulses == m)[0]])})
                    unique_addrs, idxs_addrs = np.unique([data['miscellaneous']['channel'] for data in self.buffer[m]],
                                                         return_index=True)
                    if unique_addrs.size == len(self.channels):
                        data_m = np.array(self.buffer[m])[idxs_addrs]
                        data_struct = {'data': data_m,
                                       'macropulse': m,
                                       'miscellaneous': {'synchronous': 1,
                                                         'samples': 1},
                                       'timestamp': time.time(),
                                       'type': 'A_DICT'}
                        self.queue.put(data_struct)
                        print(data_struct['macropulse'])
                        try:
                            del self.buffer[m]
                        except:
                            continue
                        self.hist_count += 1
                        self.hist[self.hist_count % self.MAX_MACRO_DELAY] = m
                        self.timer.cancel()
                time.sleep(0.05)
        else:
            m_old = 0
            while not self.stop_event.is_set() and not self.queue.full() and not self._timeout:
                try:
                    self.timer.start()
                    self._timeout = False
                except:
                    pass
                wait = True
                while wait:
                    m_curr = current_macropulse()
                    if m_curr != m_old:
                        timestamp = time.time()
                        parsed_addrs = self.parse_channels()
                        data_struct = {'data': parsed_addrs,
                                       'macropulse': m_curr,
                                       'miscellaneous': {'synchronous': 0},
                                       'timestamp': timestamp,
                                       'type': 'A_DICT'}
                        self.queue.put(data_struct)
                        print(data_struct['macropulse'])
                        m_old = m_curr
                        wait = False
                        self.timer.cancel()
                    else:
                        time.sleep(1 / self.rep_rate)
        return

    def get(self):
        if not self.queue.empty():
            return self.queue.get()
        else: return {}

    def timeout(self):
        self._timeout = True


class FLASHDataStruct(object):
    def __init__(self, filename: str, shape: tuple = None,
                 facility: str = 'FLASH', beamline: str = 'FL3',
                 DAQ_experiment: str = 'flashfwd', DAQ_run: int = 0,
                 comment: str = 'None', script_name: str = 'None'):

        self._h5file = None
        self._h5filename = filename
        self.shape = shape

        if os.path.isfile(self._h5filename):
            if not h5py.is_hdf5(self._h5filename):
                raise ValueError('Not a HDF5 file!!!')
        else:
            attrs = {'facility': facility,
                     'beamline': beamline,
                     'DAQ_experiment': DAQ_experiment,
                     'DAQ_run': DAQ_run,
                     'comment': comment,
                     'script_name': script_name}
            with h5py.File(self._h5filename, 'w') as h5:
                for k, v in attrs.items():
                    print(k, v)
                    h5.attrs[k] = v
                h5.require_group('DATA')
                h5.require_group('BACKGROUND')
                h5.require_group('_REFERENCE')
                h5.require_group('METADATA')
                h5.require_group('ANALYSIS')
                h5.require_group('DEVICE_SETTINGS')
                h5.require_group('MACHINE_SNAPSHOT')

    def __enter__(self):
        self._h5file = h5py.File(self._h5filename, 'a')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._h5file.attrs['timestamp_stop'] = datetime.now().replace(microsecond=0).isoformat()
        self._h5file.close()

    @property
    def get_keys(self):
        with h5py.File(self._h5filename, 'a') as h5:
            print("Keys: %s" % list(h5.keys()))
            return list(h5.keys())

    @property
    def get_tree(self):
        with h5py.File(self._h5filename, 'a') as h5:
            h5.visit(lambda name: print(name))

    def dump(self, data_struct: dict, idx: tuple = None, grp_name: str = 'DATA'):
        with h5py.File(self._h5filename, 'a') as h5:
            grp = h5.require_group(grp_name.upper())
            if idx and not self.shape is None:
                for data in data_struct['data']:
                    channel = data['miscellaneous']['channel']
                    if not channel in grp:
                        if isinstance(data['data'], int) or isinstance(data['data'], float):
                            dset = grp.create_dataset(name=channel, shape=self.shape, fillvalue=np.nan)
                        elif isinstance(data['data'], np.ndarray):
                            dset = grp.create_dataset(name=channel, shape=self.shape + data['data'].shape,
                                                      fillvalue=np.nan)
                    else:
                        dset = grp[channel]
                    dset[idx] = data['data']
                    del data['data']
                    data_attrs = flatten(data)
                    if dset.attrs:
                        macros = deepcopy(dset.attrs['macropulse'])
                        macros[idx] = data_attrs['macropulse']
                        timestamps = deepcopy(dset.attrs['timestamp'])
                        timestamps[idx] = data_attrs['timestamp']
                        dset.attrs['macropulse'] = macros
                        dset.attrs['timestamp'] = timestamps
                    else:
                        macros = np.zeros(self.shape)
                        macros[idx] = data_attrs['macropulse']
                        del data_attrs['macropulse']
                        dset.attrs['macropulse'] = macros
                        timestamps = np.zeros(self.shape)
                        timestamps[idx] = data_attrs['timestamp']
                        del data_attrs['timestamp']
                        dset.attrs['timestamp'] = timestamps
                        for k, v in data_attrs.items():
                            dset.attrs[k] = v
            else:
                for data in data_struct['data']:
                    channel = data['miscellaneous']['channel']
                    data = flatten(data)
                    if not channel in grp:
                        if isinstance(data['data'], int) or isinstance(data['data'], float):
                            dset = grp.create_dataset(name=channel, data=np.array([data['data']]),
                                                      maxshape=(None,),
                                                      fillvalue=np.nan)
                            dset.attrs['macropulse'] = np.array([data['macropulse']])
                            dset.attrs['timestamp'] = np.array([data['timestamp']])
                            del data['data'], data['macropulse'], data['timestamp']
                        elif isinstance(data['data'], np.ndarray):
                            dset = grp.create_dataset(name=channel,
                                                      data=np.array([data['data']]),
                                                      maxshape=(None,) + data['data'].shape,
                                                      fillvalue=np.nan)
                            dset.attrs['macropulse'] = np.array([data['macropulse']])
                            dset.attrs['timestamp'] = np.array([data['timestamp']])
                            del data['data'], data['macropulse'], data['timestamp']
                        for k, v in data.items():
                            dset.attrs[k] = v
                    else:
                        dset = grp[channel]
                        curr_idx = dset.shape[0]
                        new_size = tuple([curr_idx + 1]) + (data['data'].shape if type(data['data']) == np.ndarray else ())
                        dset.resize(new_size)
                        dset[curr_idx] = data['data']
                        dset.attrs['macropulse'] = np.append(dset.attrs['macropulse'], data['macropulse'])
                        dset.attrs['timestamp'] = np.append(dset.attrs['timestamp'], data['timestamp'])

    def dump_settings(self, data_struct: dict, key: str = None):
        channels = [data['miscellaneous']['channel'] for data in data_struct['data']]
        with h5py.File(self._h5filename, 'a') as h5:
            if key:
                grp = h5.require_group('DEVICE_SETTINGS/' + key.upper())
            else:
                grp = h5.require_group('DEVICE_SETTINGS/')
            for i, channel in enumerate(channels):
                data = flatten(data_struct['data'][i])
                try:
                    dset = grp.create_dataset(name=channel, data=data['data'])
                except Exception as err:
                    print('{}: {}'.format(channel, err))
                else:
                    for key in set(data.keys()) - set(['data']):
                        try:
                            dset.attrs[key] = data[key]
                        except Exception as err:
                            print('{}: {}'.format(key, err))
            del data_struct['data']
            attrs = flatten(data_struct)
            for key in attrs.keys():
                try:
                    grp.attrs[key] = attrs[key]
                except Exception as err:
                    print('{}: {}'.format(key, err))

    def machine_snapshot(self):
        return


class DAQ_dump(object):
    def __init__(self, fname: str, start_time: str, stop_time: str, channels: list,
                 exp: str='flashfwd', ddir: str='/daq_data/flashfwd/EXP', local: bool = True):
        self._h5filename = fname
        self.start_time = start_time
        self.stop_time = stop_time
        self.channels = channels
        self.exp = exp
        self.ddir = ddir
        self.local = local
        self.check_daq()
        if os.path.isfile(self._h5filename):
            if not h5py.is_hdf5(self._h5filename):
                raise ValueError('Not a HDF5 file!!!')
        else:
            with h5py.File(self._h5filename, 'w') as h5:
                print('File {} created successfully!'.format(self._h5filename))

    def check_daq(self):
        try:
            pydaq.connect(start=self.start_time, stop=self.stop_time, chans=self.channels,
                          exp=self.exp, ddir=self.ddir, local=self.local)
        except pydaq.PyDaqException as err:
            print('Something wrong with daqconnect... exiting')
            print(err)
            raise KeyError
        else:
            pydaq.disconnect()

    def poll(self):
        try:
            pydaq.connect(start=self.start_time, stop=self.stop_time, chans=self.channels,
                          exp=self.exp, ddir=self.ddir, local=self.local)
        except pydaq.PyDaqException as err:
            print('Something wrong with daqconnect... exiting')
            print(err)
            raise KeyError
        stop = False
        loop_count = 0
        count = 0
        emptycount = 0
        if self.local:  # fast channels
            with h5py.File(self._h5filename, 'a') as h5:
                print('File open!')
                while not stop and (emptycount < 10000):
                    loop_count += 1
                    print('Loop count: {}'.format(loop_count))
                    try:
                        channels = pydaq.getdata()
                        if not channels:
                            time.sleep(0.001)
                            emptycount += 1
                            continue
                        if channels is None:
                            break
                        for chan_list in channels:
                            for subchan in chan_list:
                                dtype = subchan['type']
                                macropulse = subchan['macropulse']
                                if dtype == 'IMAGE':
                                    daq_name = subchan['miscellaneous']['daqname'].strip('/')
                                    prop = 'IMAGE_EXT_ZMQ'
                                    data = deepcopy(subchan['data'])
                                    del subchan['data'] 
                                elif dtype == 'A_USTR':
                                    daq_name = '/'.join(subchan['miscellaneous']['daqname'].split('/')[:-1])
                                    prop = subchan['miscellaneous']['daqname'].split('/')[-1]
                                    data = deepcopy(subchan['data'][0][1])
                                    del subchan['data']
                                elif 'comment' in subchan['miscellaneous']:
                                    prop = subchan['miscellaneous']['comment'].strip('/')
                                    data = deepcopy(subchan['data'])
                                    del subchan['data'] 
                                else:
                                    print('Data structure not understood yet...')
                                    stop = True
                                    pydaq.disconnect()
                                    break
                                grp_name = '/'.join([daq_name, prop])
                                print(grp_name, macropulse)
                                grp = h5.require_group(name=grp_name)
                                if not str(macropulse) in grp:
                                    attrs = flatten(subchan)
                                    dset = grp.create_dataset(data=data, name=str(macropulse))
                                    for k, v in attrs.items():
                                        dset.attrs[k] = v
                                else:
                                    continue
                    except Exception as err:
                        print('Something wrong ... stopping %s'%str(err))
                        stop = True
                        pydaq.disconnect()
            pydaq.disconnect()
        elif not self.local:  # slow channels
            with h5py.File(self._h5filename, 'a') as h5:
                while not stop and (emptycount < 100000):
                    try:
                        result = pydaq.getdata()
                        if result:
                            print('data found!')
                            for data_struct in result:
                                daq_name = data_struct['miscellaneous']['daqname']
                                macropulse = data_struct['macropulse']
                                print(daq_name, macropulse)
                                grp = h5.require_group(daq_name)
                                if not str(macropulse) in grp:
                                    data = data_struct['data'][0][1]
                                    del data_struct['data']
                                    attrs = flatten(data_struct)
                                    dset = grp.create_dataset(data=data, name=str(macropulse))
                                    for k, v in attrs.items():
                                        dset.attrs[k] = v
                                else:
                                    continue
                        else:
                            print('empty count')
                            time.sleep(0.001)
                            emptycount += 1
                            continue
                    except Exception as err:
                        print('Something wrong ... stopping %s' % str(err))
                        stop = True
                        pydaq.disconnect()
            pydaq.disconnect()
