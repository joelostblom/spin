#!/usr/bin/env python

"""
################################################################################
#                                                                              #
# spin                                                                         #
#                                                                              #
################################################################################
#                                                                              #
# LICENCE INFORMATION                                                          #
#                                                                              #
# The program spin provides an interface for control of the usage modes of     #
# laptop-tablet and similar computer interface devices.                        #
#                                                                              #
# copyright (C) 2013 William Breaden Madden                                    #
#                                                                              #
# This software is released under the terms of the GNU General Public License  #
# version 3 (GPLv3).                                                           #
#                                                                              #
# This program is free software: you can redistribute it and/or modify it      #
# under the terms of the GNU General Public License as published by the Free   #
# Software Foundation, either version 3 of the License, or (at your option)    #
# any later version.                                                           #
#                                                                              #
# This program is distributed in the hope that it will be useful, but WITHOUT  #
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or        #
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for     #
# more details.                                                                #
#                                                                              #
# For a copy of the GNU General Public License, see                            #
# <http://www.gnu.org/licenses/>.                                              #
#                                                                              #
################################################################################

Usage:
    spin.py [options]

Options:
    -h,--help                 display help message
    --version                 display version and exit
    --gui                     GUI mode for debugging
    --debugpassive            display commands without executing
    -m,--mode                 toggle between laptop and tablet/tent mode
    -r,--rotation-lock        toggle rotation lock on/off
    --daemon                  run in this mode in the background
"""

name    = "spin"
version = "2015-04-30T0256Z"

import imp
import urllib

# TODO! Remove this, the module being smuggled in is available in Ubuntu 15.10
def smuggle(
    moduleName = None,
    URL        = None
    ):
    if moduleName is None:
        moduleName = URL
    try:
        module = __import__(moduleName)
        return(module)
    except:
        try:
            moduleString = urllib.urlopen(URL).read()
            module = imp.new_module("module")
            exec moduleString in module.__dict__
            return(module)
        except: 
            raise(
                Exception(
                    "module {moduleName} import error".format(
                        moduleName = moduleName
                    )
                )
            )
            sys.exit()

import os
import sys
import signal
import glob
import subprocess
import socket
import time
import logging
from   PyQt4 import QtCore
from multiprocessing import Process, Queue
from numpy import (array, dot)
from numpy.linalg import norm

SPIN_SOCKET = '/tmp/yoga_spin.socket'

# TODO! Remove this. Package is included in Ubuntu 15.10...or replace with other
docopt = smuggle(
    moduleName = "docopt",
    URL = "https://rawgit.com/docopt/docopt/master/docopt.py"
)

class Daemon(QtCore.QObject):

    def __init__(self, options = None):
        super(Daemon, self).__init__()
        # Capture SIGINT
        signal.signal(signal.SIGINT, self.signal_handler)
        # Check if spin is running.
        if os.path.exists(SPIN_SOCKET):
            log.error("Only one instance of Yoga Spin Daemon can be run at a time")
            sys.exit()
        # Handle debug option
        self.options = options
        log.info("initiate {name}".format(name = name))
        # Audit the inputs available.
        self.deviceNames = get_inputs()
        if options["--debugpassive"] is True:
            log.info("device names: {deviceNames}".format(
                deviceNames = self.deviceNames
            ))
        # Set default laptop mode
        self.mode = "laptop"
        self.orientation = "normal"
        self.locked = True
        # Engage stylus proximity control
        self.stylus_proximity_control_switch(status = "on")
        # Start a queue for reading screen rotation from the accelerometer
        self.accelerometerStatus = "on"
        self.accelQueue = Queue()
        self.accelTimer = QtCore.QTimer()
        self.accelTimer.timeout.connect(self.acceleration_listen)
        self.accelTimer.start(100)
        self.acceleration_control_switch(status = "on")
        # Listen for commands through a socket
        if os.path.exists(SPIN_SOCKET):
            os.remove(SPIN_SOCKET)
        self.spin_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.spin_socket.setblocking(0)
        self.spin_socket.bind(SPIN_SOCKET)
        self.spin_timer = QtCore.QTimer()
        self.spin_timer.timeout.connect(self.socket_listen)
        self.spin_timer.start(105)

    def signal_handler(self, signal, frame):
        log.info('You pressed Ctrl+C!')
        self.close_event('bla')
        sys.exit(0)


    def close_event(self, event):
        log.info("terminate {name}".format(name = name))
        if self.mode == "tablet":
            self.engage_mode("laptop")
        self.stylus_proximity_control_switch(status = "off")
        self.acceleration_control_switch(status = "off")
        try:
            os.remove(SPIN_SOCKET)
        except:
            pass


    def display_orientation(
        self,
        orientation = None
        ):
        if orientation in ["left", "right", "inverted", "normal"]:
            log.info("change display to {orientation}".format(
                orientation = orientation
            ))
            engage_command(
                "xrandr -o {orientation}".format(
                    orientation = orientation
                )
            )
            # TODO! Hack to reset calibration.
            engage_command("xsetwacom --set 10 ResetArea")
        else:
            log.error(
                "unknown display orientation \"{orientation}\" "
                "requested".format(
                    orientation = orientation
                )
            )
            sys.exit()

    def touchscreen_orientation(
        self,
        orientation = None
        ):
        if "touchscreen" in self.deviceNames:
            coordinateTransformationMatrix = {
                "left":     "0 -1 1 1 0 0 0 0 1",
                "right":    "0 1 0 -1 0 1 0 0 1",
                "inverted": "-1 0 1 0 -1 1 0 0 1",
                "normal":   "1 0 0 0 1 0 0 0 1"
            }
            # Waiting for the touchscreen to reconnect, after the screen rotates.
            while not self.is_touchscreen_alive():
                time.sleep(0.5)
            if coordinateTransformationMatrix.has_key(orientation):
                log.info("change touchscreen to {orientation}".format(
                    orientation = orientation
                ))
                engage_command(
                    "xinput set-prop \"{deviceName}\" \"Coordinate "
                    "Transformation Matrix\" "
                    "{matrix}".format(
                        deviceName = self.deviceNames["touchscreen"],
                        matrix = coordinateTransformationMatrix[orientation]
                    )
                )
            else:
                log.error(
                    "unknown touchscreen orientation \"{orientation}\""
                    " requested".format(
                        orientation = orientation
                    )
                )
                sys.exit()
        else:
            log.debug("touchscreen orientation unchanged")

    def touchscreen_switch(
        self,
        status = None
        ):
        if "touchscreen" in self.deviceNames:
            xinputStatus = {
                "on":  "enable",
                "off": "disable"
            }
            while not self.is_touchscreen_alive():
                time.sleep(0.5)
            if xinputStatus.has_key(status):
                log.info("change touchscreen to {status}".format(
                    status = status
                ))
                engage_command(
                    "xinput {status} \"{deviceName}\"".format(
                        status = xinputStatus[status],
                        deviceName = self.deviceNames["touchscreen"]
                    )
                )
            else:
                _message = "unknown touchscreen status \"{status}\" " +\
                           "requested"
                log.error(
                    _message.format(
                        status = status
                    )
                )
                sys.exit()
        else:
            log.debug("touchscreen status unchanged")

    
    def touchpad_switch(
        self,
        status = None
        ):
        if "touchpad" in self.deviceNames:
            xinputStatus = {
                "on":  "enable",
                "off": "disable"
            }
            if xinputStatus.has_key(status):
                log.info("change touchpad to {status}".format(
                    status = status
                ))
                engage_command(
                    "xinput {status} \"{deviceName}\"".format(
                        status = xinputStatus[status],
                        deviceName = self.deviceNames["touchpad"]
                    )
                )
            else:
                _message = "unknown touchpad status \"{status}\" " +\
                           "requested"
                log.error(
                    _message.format(
                        status = status
                    )
                )
                sys.exit()
        else:
            log.debug("touchpad status unchanged")


    def nipple_switch(
        self,
        status = None
        ):
        if "nipple" in self.deviceNames:
            xinputStatus = {
                "on":  "enable",
                "off": "disable"
            }
            if xinputStatus.has_key(status):
                log.info("change nipple to {status}".format(
                    status = status
                ))
                engage_command(
                    "xinput {status} \"{deviceName}\"".format(
                        status = xinputStatus[status],
                        deviceName = self.deviceNames["nipple"]
                    )
                )
            else:
                _message = "unknown nipple status \"{status}\" " +\
                           "requested"
                log.error(
                    _message.format(
                        status = status
                    )
                )
                sys.exit()
        else:
            log.debug("nipple status unchanged")


    def stylus_proximity_control(
        self
        ):
        self.previousStylusProximityStatus = None
        while True:
            stylusProximityCommand = "xinput query-state " + \
                                     "\"Wacom ISDv4 EC Pen stylus\" | " + \
                                     "grep Proximity | cut -d \" \" -f3 | " + \
                                     " cut -d \"=\" -f2"
            self.stylusProximityStatus = subprocess.check_output(
                stylusProximityCommand,
                shell = True
            ).lower().rstrip()
            if \
                (self.stylusProximityStatus == "out") and \
                (self.previousStylusProximityStatus != "out"):
                log.info("stylus inactive")
                self.touchscreen_switch(status = "on")
            elif \
                (self.stylusProximityStatus == "in") and \
                (self.previousStylusProximityStatus != "in"):
                log.info("stylus active")
                self.touchscreen_switch(status = "off")
            self.previousStylusProximityStatus = self.stylusProximityStatus
            time.sleep(0.15)


    def stylus_proximity_control_switch(
        self,
        status = None
        ):
        if status == "on":
            log.info("change stylus proximity control to on")
            self.processStylusProximityControl = Process(
                target = self.stylus_proximity_control
            )
            self.processStylusProximityControl.start()
        elif status == "off":
            log.info("change stylus proximity control to off")
            self.processStylusProximityControl.terminate()
        else:
            log.error(
                "unknown stylus proximity control status \"{status}\" "
                "requested".format(
                    status = status
                )
            )
            sys.exit()


    def socket_listen(self):
        try:
            command = self.spin_socket.recv(1024)
            if command:
                self.engage_mode(command)
        except:
            pass


    def acceleration_listen(self):
        if self.accelQueue.empty():
            return
        orientation = self.accelQueue.get()
        if not self.locked:
            self.engage_mode(orientation)


    def acceleration_control_switch(
        self,
        status = None
        ):
        if status == "on":
            log.info("change acceleration control to on")
            self.processAccelerationControl = Process(
                target = acceleration_sensor,
                args = (self.accelQueue, self.orientation)
            )
            self.processAccelerationControl.start()
            self.accelerometerStatus = "on"
        elif status == "off":
            log.info("change acceleration control to off")
            # TODO! Check if process exists, before terminating it.
            if hasattr(self, 'processAccelerationControl'):
                pass
            #self.processAccelerationControl.terminate()
            self.accelerometerStatus = "off"
        else:
            log.error(
                "unknown acceleration control status \"{status}\" "
                "requested".format(
                    status = status
                )
            )
            sys.exit()

    
    def engage_mode(self, mode = None):
        log.info("engage mode {mode}".format(mode = mode))
        if mode == "toggle":
            if self.mode == "laptop":
                mode = "tablet"
            else:
                mode = "laptop"
            self.mode = mode
        if mode == "tablet":
            print(" *** TABLET ***")
            self.nipple_switch(status = "off") 
            self.touchpad_switch(status = "off")
            self.locked = False
            os.system('notify-send "Tablet Mode"')
        elif mode == "laptop":
            print(" *** LAPTOP ***")
            self.locked = True
            self.touchpad_switch(status = "on")
            self.nipple_switch(status = "on")
            self.display_orientation(orientation = "normal")
            self.touchscreen_orientation(orientation = "normal")
            os.system('notify-send "Laptop Mode"')
        elif mode in ["left", "right", "inverted", "normal"]:
            self.display_orientation(orientation = mode)
            self.touchscreen_orientation(orientation = mode)
        elif mode == "togglelock":
            if self.locked is True:
                self.locked = False
                log.info("Rotation lock disabled")
                os.system('notify-send "Rotation Lock Disabled"')
            else:
                self.locked = True
                log.info("Rotation lock enabled")
                os.system('notify-send "Rotation Lock Enabled"')
        else:
            log.error(
                "unknown mode \"{mode}\" requested".format(
                    mode = mode
                )
            )
            sys.exit()
        time.sleep(2)  # Switching modes too fast seems to cause trobule


    def is_touchscreen_alive(self):
        ''' Check if the touchscreen is responding '''
        log.info("waiting for touchscreen to respond")
        status = os.system('xinput list | grep -q "{touchscreen}"'.format(touchscreen = self.deviceNames["touchscreen"]))
        if status == 0:
            return True
        else:
            return False
        

def get_inputs():
    log.info("audit inputs")
    inputDevices = subprocess.Popen(
        ["xinput", "--list"],
        stdin = subprocess.PIPE,
        stdout = subprocess.PIPE,
        stderr = subprocess.PIPE
    ).communicate()[0]
    devicesAndKeyphrases = {
        "touchscreen": ["SYNAPTICS Synaptics Touch Digitizer V04",
                        "ELAN Touchscreen"],
        "touchpad":    ["PS/2 Synaptics TouchPad",
                        "SynPS/2 Synaptics TouchPad"],
        "nipple":      ["TPPS/2 IBM TrackPoint"],
        "stylus":      ["Wacom ISDv4 EC Pen stylus"]
    }
    deviceNames = {}
    for device, keyphrases in devicesAndKeyphrases.iteritems():
        for keyphrase in keyphrases:
            if keyphrase in inputDevices:
                deviceNames[device] = keyphrase
    for device, keyphrases in devicesAndKeyphrases.iteritems():
        if device in deviceNames:
            log.info("input {device} detected as \"{deviceName}\"".format(
                device     = device,
                deviceName = deviceNames[device]
            ))
        else:
            log.info("input {device} not detected".format(
                device = device
            ))
    return(deviceNames)

def engage_command(
    command = None
    ):
    if options["--debugpassive"] is True:
        log.info("command: {command}".format(
            command = command
        ))
    else:
        os.system(command)

def mean_list(lists = None):
    return([sum(element)/len(element) for element in zip(*lists)])

def acceleration_sensor(accelQueue, old_orientation="normal"):
    while True:
        # Get the mean of recent acceleration vectors.
        numberOfMeasurements = 6
        measurements = []
        for measurement in range(0, numberOfMeasurements):
            time.sleep(0.25)
            measurements.append(AccelerationVector())
        stableAcceleration = mean_list(lists = measurements)
        log.info("stable acceleration vector: {vector}".format(
            vector = stableAcceleration
        ))
        # Using numpy to compare rotation vectors.
        stable = array((stableAcceleration[0], stableAcceleration[1], stableAcceleration[2]))
        normal = array((0.0, -1, 0))
        right = array((-1.0, 0, 0))
        inverted = array((0.0, 1, 0))
        left = array((1.0, 0, 0))
        d = {
            "normal": dot(stable, normal) / norm(stable) / norm(normal),
            "inverted": dot(stable, inverted) / norm(stable) / norm(inverted),
            "left": dot(stable, left) / norm(stable) / norm(left),
            "right": dot(stable, right) / norm(stable) / norm(right)
        }
        orientation = max(d, key=d.get)
        if old_orientation != orientation:
            old_orientation = orientation
            accelQueue.put(orientation)
        time.sleep(0.15)


class AccelerationVector(list):

    def __init__(self):
        list.__init__(self)  
        # Access the IIO interface to the accelerometer.
        devicesDirectories = glob.glob("/sys/bus/iio/devices/iio:device*")
        for directory in devicesDirectories:
            if "accel_3d" in open(os.path.join(directory, "name")).read():
                self.accelerometerDirectory = directory
        self.accelerometerScaleFileFullPath =\
            self.accelerometerDirectory + "/" + "in_accel_scale"
        self.accelerometerAxisxFileFullPath =\
            self.accelerometerDirectory + "/" + "in_accel_x_raw"
        self.accelerometerAxisyFileFullPath =\
            self.accelerometerDirectory + "/" + "in_accel_y_raw"
        self.accelerometerAxiszFileFullPath =\
            self.accelerometerDirectory + "/" + "in_accel_z_raw"
        self.accelerometerScaleFile = open(self.accelerometerScaleFileFullPath)
        self.accelerometerAxisxFile = open(self.accelerometerAxisxFileFullPath)
        self.accelerometerAxisyFile = open(self.accelerometerAxisyFileFullPath)
        self.accelerometerAxiszFile = open(self.accelerometerAxiszFileFullPath)
        # Access the scale.
        self.scale = float(self.accelerometerScaleFile.read())
        # Initialise the vector.
        self.extend([0, 0, 0])
        self.update()

    def update(self):
        # Access the acceleration.
        self.accelerometerAxisxFile.seek(0)
        self.accelerometerAxisyFile.seek(0)
        self.accelerometerAxiszFile.seek(0)
        acceleration_x = float(self.accelerometerAxisxFile.read()) * self.scale
        acceleration_y = float(self.accelerometerAxisyFile.read()) * self.scale
        acceleration_z = float(self.accelerometerAxiszFile.read()) * self.scale
        # Update the vector.
        self[0] = acceleration_x
        self[1] = acceleration_y
        self[2] = acceleration_z

    def __repr__(self):
        self.update()
        return(list.__repr__(self))


def send_command(command):
    if os.path.exists(SPIN_SOCKET):
        command_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            command_socket.connect(SPIN_SOCKET)
            command_socket.send(command)
            log.info("Connected to socket")
        except:
            log.info("Failed to send mode change to the spin daemon")
    else:
        log.error("Socket does not exist. Is the spin deamon running.")


def main(options):

    # logging
    global log
    log        = logging.getLogger()
    logHandler = logging.StreamHandler()
    log.addHandler(logHandler)
    logHandler.setFormatter(logging.Formatter("%(message)s"))
    log.level  = logging.INFO

    # TODO! Option parser acceps half options, like --sett.  Replace it.
    if options["--mode"]:
        log.info("Toggle between tablet and laptop mode")
        send_command("toggle")
    elif options["--rotation-lock"]:
        log.info("Toggle the rotation lock on/off")
        send_command("togglelock")
    elif options["--daemon"]:
        log.info("Starting Yoga Spin background daemon")
        app = QtCore.QCoreApplication(sys.argv)
        daemon = Daemon(options)
        sys.exit(app.exec_())
    else:
        log.info("No options passed. Doing nothing")
        pass

if __name__ == "__main__":
    options = docopt.docopt(__doc__)
    if options["--version"]:
        print(version)
        exit()
    main(options)
