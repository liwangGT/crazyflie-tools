#!/usr/bin/env python2


############################ CLIENT OPTIONS ##########################################
# this is for testing
#TXRX_FREQUENCY = 1000.0

STARTUP_NANOKONTROL = True
USE_DRAKE_CONTROLLER = True

SE_LISTEN_TO_VICON = True
SE_VICON_CHANNEL = 'cf2_pete1'
SE_PUBLISH_TO_LCM = True
SE_USE_RPYDOT = True
SE_USE_EKF = True
SE_USE_UKF = False
SE_DELAY_COMP = False

CTRL_INPUT_TYPE = 'omegasqu'
CTRL_LISTEN_TO_LCM = True
CTRL_LISTEN_TO_EXTRA_INPUT = True
CTRL_PUBLISH_TO_LCM = True

CTRL_USE_POSITION_CONTROL = True
######################################################################################


import struct
import array
import usb
import os
import time
from threading import Thread, Lock, Event

import cflib
from cflib.crazyflie import Crazyflie
from cflib.crtp.crtpstack import CRTPPacket, CRTPPort

import nanokontrol
from estimation import StateEstimator
from controller import Controller

import lcm
from crazyflie_t import crazyflie_imu_t

# Crazyradio options
ACK_ENABLE = 0x10
SET_RADIO_ARC = 0x06
SET_DATA_RATE = 0x03


class SimpleClient:

    def __init__(self, link_uri):        
        self._cf = Crazyflie()
        self._cf.connected.add_callback(self._connected)
        self._cf.disconnected.add_callback(self._disconnected)
        self._cf.connection_failed.add_callback(self._connection_failed)
        self._cf.connection_lost.add_callback(self._connection_lost)
        self._cf.open_link(link_uri)
        print "Connecting to %s" % link_uri

    def _connected(self, link_uri):
        # stoping the regular crtp link        
        self._cf.link.device_flag.clear()
        self._dev_handle = self._cf.link.cradio.handle
        self._send_vendor_setup(SET_RADIO_ARC, 0, 0, ())

        self._use_drake_controller = USE_DRAKE_CONTROLLER
        self._use_pos_control = CTRL_USE_POSITION_CONTROL

        # state estimator
        self._state_estimator = StateEstimator(listen_to_vicon=SE_LISTEN_TO_VICON,
                                               vicon_channel=SE_VICON_CHANNEL,
                                               publish_to_lcm=SE_PUBLISH_TO_LCM,
                                               use_rpydot=SE_USE_RPYDOT,
                                               use_ekf=SE_USE_EKF,
                                               use_ukf=SE_USE_UKF,
                                               delay_comp=SE_DELAY_COMP)

        # controller
        self._control_input_updated_flag = Event()
        self._controller = Controller(control_input_type=CTRL_INPUT_TYPE,
                                      listen_to_lcm=CTRL_LISTEN_TO_LCM,
                                      control_input_updated_flag=self._control_input_updated_flag,
                                      listen_to_extra_input=CTRL_LISTEN_TO_EXTRA_INPUT,
                                      publish_to_lcm=CTRL_PUBLISH_TO_LCM,
                                      pos_control=CTRL_USE_POSITION_CONTROL)
        
        # Transmitter thread (handles all comm with the crazyflie)
        Thread(target=self._transmitter_thread).start()

        if STARTUP_NANOKONTROL:
            Thread(target=nanokontrol.main).start()

    def _connection_failed(self, link_uri, msg):
        print "Connection to %s failed: %s" % (link_uri, msg)

    def _connection_lost(self, link_uri, msg):
        print "Connection to %s lost: %s" % (link_uri, msg)

    def _disconnected(self, link_uri):
        print "Disconnected from %s" % link_uri

    def _transmitter_thread(self):
        sensor_request_pk = CRTPPacket()
        sensor_request_pk.port = CRTPPort.SENSORS
        control_input_pk = CRTPPacket()
        control_input_pk.port = CRTPPort.OFFBOARDCTRL

        vicon_yaw = 0.0
        if SE_LISTEN_TO_VICON:
            use_vicon_yaw = 1
        else:
            use_vicon_yaw = 0
        
        imu_lc = lcm.LCM()

        while True:
            #t0 = time.time()

            sensor_request_pk.data = struct.pack('<fi',vicon_yaw,use_vicon_yaw)
            sensor_request_dataout = self._pk_to_dataout(sensor_request_pk)

            datain = self._write_read_usb(sensor_request_dataout)
            sensor_packet = self._datain_to_pk(datain)
            if not sensor_packet:
                continue
            try:
                imu_reading = struct.unpack('<7f',sensor_packet.data)
            except:
                continue

            self._state_estimator.add_imu_reading(imu_reading)

            # msg = crazyflie_imu_t()
            # msg.omegax = imu_reading[0]
            # msg.omegay = imu_reading[1]
            # msg.omegaz = imu_reading[2]
            # msg.alphax = imu_reading[3]
            # msg.alphay = imu_reading[4]
            # msg.alphaz = imu_reading[5]
            # imu_lc.publish('crazyflie_imu', msg.encode())

            self._control_input_updated_flag.clear()
            xhat = self._state_estimator.get_xhat()
            vicon_yaw = xhat[5]
            if self._use_drake_controller:
                # wait for Drake to give us the control input
                self._control_input_updated_flag.wait(0.005)

            control_input = self._controller.get_control_input(xhat=xhat)
            if self._use_pos_control:
                control_input_pk.data = struct.pack('<7f',*control_input)
            else:
                control_input_pk.data = struct.pack('<5fi',*control_input)
            control_input_dataout = self._pk_to_dataout(control_input_pk) 
            self._write_usb(control_input_dataout)

            if not(self._use_pos_control):
                # TODO: position control could still update the state
                #       estimator about the last input sent
                self._state_estimator.add_input(control_input[0:4])

            #tf = time.time()
            #time.sleep(max(0.0,(1.0/TXRX_FREQUENCY)-float(tf-t0)))

    def _pk_to_dataout(self,pk):
        dataOut = array.array('B')
        dataOut.append(pk.header)
        for X in pk.data:
            if type(X) == int:
                dataOut.append(X)
            else:
                dataOut.append(ord(X))
        return dataOut

    def _datain_to_pk(self,dataIn):
        if dataIn != None:
            if dataIn[0] != 0:
                data = dataIn[1:]
                if (len(data) > 0):
                    packet = CRTPPacket(data[0], list(data[1:]))
                    return packet

    def _write_usb(self, dataout):
        try:
            self._dev_handle.write(endpoint=1, data=dataout, timeout=0)
        except usb.USBError:
            pass

    def _write_read_usb(self, dataout):
        datain = None
        try:
            self._dev_handle.write(endpoint=1, data=dataout, timeout=0)
            datain = self._dev_handle.read(0x81, 64, timeout=5)
        except usb.USBError:
            pass
        return datain

    def _send_vendor_setup(self, request, value, index, data):
        self._dev_handle.ctrl_transfer(usb.TYPE_VENDOR, request, wValue=value,
                                        wIndex=index, timeout=1000, data_or_wLength=data)


if __name__ == '__main__':
    
    if SE_USE_UKF:
        raise Exception('The UKF is not functional yet. Please use the EKF.')

    cflib.crtp.init_drivers(enable_debug_driver=False)
    print "Scanning interfaces for Crazyflies..."
    available = cflib.crtp.scan_interfaces()
    print "Crazyflies found:"
    for i in available:
        print i[0]

    if len(available) > 0:
        client = SimpleClient('radio://0/80/250K')
        #client = SimpleClient(available[0][0]) 
    else:
        print "No Crazyflies found, cannot run the client"
