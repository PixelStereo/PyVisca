#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
This file contains the Camera class that represent a camera device
You don't have to create this class by yourself as it is done for each device
that answers to a broadcast message.

"""

from pyviscam.convert import hex_to_int, i2v, scale
from pyviscam.pan_tilt_utils import degree_to_visca, visca_to_degree
from pyviscam.constants import queries, answers, high_res_params, very_high_res_params

from pyviscam import debug


class Camera(object):
    """
    create a visca camera
    """
    def __init__(self, parent):
        """the constructor"""
        self.serial = parent.serial
        self.parent = parent
        self._pan_speed = 0x05
        self._tilt_speed = 0x05
        if debug:
            print("new visca camera")

    def _send_packet(self, data, recipient=1):
        """
        according to the documentation:

        |------packet (3-16 bytes)---------|

         header     message      terminator
         (1 byte)  (1-14 bytes)  (1 byte)

        | X | X . . . . .  . . . . . X | X |

        header:                  terminator:
        1 s2 s1 s0 0 r2 r1 r0     0xff

        with r,s = recipient, sender msb first

        for broadcast the header is 0x88!

        we use -1 as recipient to send a broadcast!

        """
        # we are the controller with id=0
        sender = 0
        if recipient == -1:
            # broadcast
            rbits = 0x8
        else:
            # the recipient (address = 3 bits)
            rbits = recipient & 0b111
        sbits = (sender & 0b111)<<4
        header = 0b10000000 | sbits | rbits
        terminator = 0xff
        packet = chr(header)+data+chr(terminator)
        self.serial.mutex.acquire()
        self.serial._write_packet(packet)
        reply = self.serial.recv_packet()
        if reply:
            if reply[-1:] != '\xff':
                if debug:
                    print("ERROR 41 - received packet not terminated correctly: %s" % reply.encode('hex'))
                reply = None
            self.serial.mutex.release()
            return reply
        else:
            return None

    def _cmd_cam_alt(self, subcmd):
        """
        shortcut to send command with alternative prefix
        """
        prefix = '\x01\x06'
        self._cmd_cam(subcmd, prefix)

    def _cmd_cam(self, subcmd, prefix='\x01\x04'):
        """
        Send a command to the camera and return the answer
        The camera answer first an acceptation of the command, and then a completion
        If the command cannot be send or is not a valide command
        => the camera will answers an error code
        """
        packet = prefix + subcmd
        reply = self._send_packet(packet)
        if reply == '\x90'+'\x41'+'\xFF':
            if debug == 4:
                print('-----------ACK 1-------------------')
            reply = self.serial.recv_packet()
            if reply == '\x90'+'\x51'+'\xFF':
                if debug == 4:
                    print('--------COMPLETION 1---------------')
                return True
        elif reply == '\x90'+'\x42'+'\xFF':
            if debug == 4:
                print('-----------ACK 2-------------------')
            reply = self.serial.recv_packet()
            if reply == '\x90'+'\x52'+'\xFF':
                if debug == 4:
                    print('--------COMPLETION 2---------------')
                return True
        elif reply == '\x90'+'\x60'+'\x02'+'\xFF':
            if debug:
                print('--------Syntax Error------------')
            return False
        elif reply == '\x90'+'\x61'+'\x41'+'\xFF':
            if debug:
                print('-----------ERROR 1 (not in this mode)------------')
            return False
        elif reply == '\x90'+'\x62'+'\x41'+'\xFF':
            if debug:
                print('-----------ERROR 2 (not in this mode)------------')
            return False

    def _come_back(self, query):
        """
        Send a query and wait for (ack + completion + answer)
            :Accepts a visca query (hexadeciaml)
            :Return a visca answer if ack and completion (hexadeciaml)
        """
        # send the query and wait for feedback
        reply = self._send_packet(query)
        if reply == '\x90'+'\x60'+'\x03'+'\xFF':
            if debug:
                print('-------- FULL BUFFER ---------------')
            # buffer is full, send it again
            self._come_back(query)
        elif reply.startswith('\x90'+'\x50'):
            if debug == 4:
                print('-------- QUERY COMPLETION ---------------')
            # We know this is a valid query request, please send it back
            return reply
        elif reply == '\x90'+'\x60'+'\x02'+'\xFF':
            if debug:
                print('-------- QUERY SYNTAX ERROR ---------------')
            return False

    def _query(self, function=None):
        """
        Query method needs a parameter as argument
            :Return False if no parameter is provided
            :Return False if parameter provided does not exist
            :Return
        """
        if not function:
            # maybe we could dump all functions if no function value is present
            # or maybe add a 'all' function?
            return False
        if debug == 4:
            print('QUERY', function)
        if function == 'pan' or function == 'tilt':
            # pan and tilt are separate properties.
            # If we want to automatically query all properties, we must catch it here
            function = 'pan_tilt'
        # transform the property into its code (located in the __init__file of the package)
        if function in queries:
            subcmd = queries.get(function)
        else:
            if debug:
                # there is no code for this function
                dbg = 'ERROR 42 - function {function} has not yet been implemented'
                print(dbg.format(function=function))
            return False
        # query starts with '\x09'
        query = '\x09' + subcmd
        if debug == 4:
            dbg = 'send {function} query : {query}'
            print(dbg.format(function=function, query=query.encode('hex')))
        # wait for the reply
        reply = self._come_back(query)
        if reply == None:
            return self._query(function)
        if reply:
            if debug == 4:
                dbg = 'receive reply : {function} is {reply}'
                print(dbg.format(function=function, reply=reply.encode('hex')))
            # remove 2 first packets and the last terminator
            # FIX ME : We must remove the first hex number elsewhere if we use multiples camera
            reply = reply[2:-1].encode('hex')
            # transform to a list of int
            # FIX ME : found a nicer solution please, it's ugly !!
            def hex_unpack(value, listt, size=2):
                part = value[:size]
                value = value[size:]
                listt.append(part)
                if value:
                    hex_unpack(value, listt)
                    return listt
            if len(reply) > 2:
                # it's a long answer, convert it to a list
                reply = hex_unpack(reply, [])
            else:
                # it's a single value, just convert it to a valid base 10 integer
                reply = int(reply, 16)
            if function in high_res_params:
                # parameter value is coded on 2 hexa numbers
                reply = hex_to_int(reply)
            elif function in very_high_res_params:
                # parameter value is coded on 4 hexa numbers
                reply = hex_to_int(reply)
            # Check if the function has a special value to be translated
            if function in answers:
                # translate visca code to real life value
                if reply in answers[function]:
                    reply = answers[function][reply]
            elif function == 'NR' or function == 'gamma' or function == 'chromasuppress':
                reply = reply
            elif function == 'color_gain' or function == 'color_hue':
                reply = int(reply[3], 16)
                reply = str(scale(reply, 0, 14, 60, 200))
                if function == 'color_gain':
                    reply = reply + '%'
                else:
                    reply = reply + '°'
            elif function == 'pan_tilt':
                pan = reply[0:4]
                tilt = reply[4:8]
                pan = hex_to_int(pan)
                tilt = hex_to_int(tilt)
                pan = visca_to_degree(pan, 'pan')
                tilt = visca_to_degree(tilt, 'tilt')
                reply = [pan, tilt]
            else:
                if debug == 4:
                    print('FIX ME : is it normal that :', function, 'has no translation??' )
            if debug:
                dbg = '{function} is {reply}'
                print(dbg.format(function=function, reply=reply))
            return reply

    # ----------------------------------------------------
    # ---------------------- POWER -----------------------
    # ----------------------------------------------------
    @property
    def power(self):
        """
        State of the power (0/1)
        """
        return self._query('power')
    @power.setter
    def power(self, state):
        if debug:
            print('power', state)
        if state:
            subcmd = '\x00\x02'
        else:
            subcmd = '\x00\x03'
        return self._cmd_cam(subcmd)

    @property
    def power_auto(self):
        """
        Return the state of the power_auto param
        time = minutes without command until standby
        0: disable
        0xffff: 65535 minutes (approximatly 45 days)
        """
        return self._query('power_auto')
    @power.setter
    def power_auto(self, time):
        subcmd = '\x40' + i2v(time)
        if debug:
            print('power_auto', time)
        return self._cmd_cam(subcmd)

    # ----------------------------------------------------
    # ---------------------- ZOOM ------------------------
    # ----------------------------------------------------
    def zoom_stop(self):
        """
        Stop the zoom movement
        """
        if debug:
            print('zoom_stop')
        subcmd = "\x07\x00"
        return self._cmd_cam(subcmd)

    def zoom_tele(self, speed=3):
        """
        Zoom In
            :speed is from 0 to 7 (default=3)
        """
        if speed == 3:
            subcmd = "\x07\x02"
        else:
            sbyte = 0x20 + (speed&0b111)
            subcmd = "\x07" + chr(sbyte)
        if debug:
            print('zoom_tele', speed)
        return self._cmd_cam(subcmd)

    def zoom_wide(self, speed=3):
        """
        Zoom Out
            :speed is from 0 to 7 (default=3)
        """
        if speed == 3:
            subcmd = "\x07\x03"
        else:
            sbyte = 0x30 + (speed&0b111)
            subcmd = "\x07" + chr(sbyte)
        if debug:
            print('zoom_wide', speed)
        return self._cmd_cam(subcmd)

    @property
    def zoom(self):
        """
        Return the actual value of the zoom
        optical: 0..4000
        digital: 4000..7000 (1x - 4x)
        """
        return self._query('zoom')
    @zoom.setter
    def zoom(self, value):
        if debug:
            print('zoom', value)
        subcmd = "\x47" + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def zoom_digital(self):
        return self._query('zoom_digital')
    @zoom_digital.setter
    def zoom_digital(self, state):
        """
        Digital zoom ON/OFF
        """
        if debug:
            print('zoom_digital', state)
        if state:
            subcmd = "\x06\x02"
        else:
            subcmd = "\x06\x03"
        return self._cmd_cam(subcmd)

    # ----------------------------------------------------
    # ---------------------- FOCUS -----------------------
    # ----------------------------------------------------
    def focus_stop(self):
        if debug:
            print('focus_stop')
        subcmd = "\x08\x00"
        return self._cmd_cam(subcmd)

    def focus_far(self, speed=3):
        """
        Focus In with speed = 0..7
        default is 3
        """
        if speed == 3:
            subcmd = "\x08\x03"
        else:
            sbyte = 0x30 + (speed&0b111)
            subcmd = "\x08" + chr(sbyte)
        if debug:
            print('focus_far', speed)
        return self._cmd_cam(subcmd)

    def focus_near(self, speed=3):
        """
        Focus Out with speed = 0..7
        default = 3
        """
        if speed == 3:
            subcmd = "\x08\x02"
        else:
            sbyte = 0x20 + (speed&0b111)
            subcmd = "\x08" + chr(sbyte)
        if debug:
            print('focus_near', speed)
        return self._cmd_cam(subcmd)

    @property
    def focus(self):
        """
        focus to value
        optical: 0..4000
        digital: 4000..7000 (1x - 4x)
        """
        return self._query('focus')

    @focus.setter
    def focus(self, value):
        if debug:
            print('focus', value)
        subcmd = "\x48" + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def focus_auto(self):
        """
        AF ON/OFF
        """
        return self._query('focus_auto')
    @focus_auto.setter
    def focus_auto(self, state):
        if debug:
            print('focus_auto', state)
        if state:
            return self._cmd_cam("\x38\x02")
        else:
            return self._cmd_cam("\x38\x03")

    def focus_trigger(self):
        """
        One Push AF Trigger
        """
        if debug:
            print('focus_trigger')
        return self._cmd_cam("\x18\x01")

    def focus_infinity(self):
        """
        Forced infinity
        """
        if debug:
            print('focus_infinity')
        return self._cmd_cam("\x18\x02")

    @property
    def focus_nearlimit(self):
        return self._query('focus_nearlimit')
    @focus_nearlimit.setter
    def focus_nearlimit(self, value):
        """
        Can be set in a range from 1000 (∞) to F000 (10 mm)
        """
        if debug:
            print('focus_nearlimit', value)
        subcmd = "\x28" + i2v(value)
        return self._cmd_cam(subcmd)

    def focus_auto_sensitivity(self, state):
        """
        AF Sensitivity High/Low
        'normal or low'
        """
        if debug:
            print('focus_auto_sensitivity', state)
        if state == 'normal':
            return self._cmd_cam("\x58\x02")
        elif state == 'low':
            return self._cmd_cam("\x58\x03")

    def focus_auto_mode(self, state):
        """
        AF Movement Mode
            :state = normal / interval / zoom trigger / active-interval
        """
        if debug:
            print('focus_movement_mode', state)
        if state == 'normal':
            subcmd = "\x57\x00"
        elif state == 'interval':
            subcmd = "\x57\x01"
        elif state == 'zoom_trigger':
            subcmd = "\x57\x02"
        if 'subcmd' in locals():
        	return self._cmd_cam(subcmd)
        else:
        	return False

    def focus_auto_active(self, value):
        """
        pq: Movement Time, rs: Interval
        """
        if debug:
            print('focus_auto_active', value)
            print('this function has never been tested')
        subcmd = "\x27" + i2v(value)
        return self._cmd_cam(subcmd)

    def focus_ir(self, state):
        """
        FOCUS IR compensation data switching
        0/1
        """
        if debug:
            print('IR', state)
        if state:
            subcmd = "\x11" + "\x00"
        else:
            subcmd = "\x11" + "\x01"
        return self._cmd_cam(subcmd)

    def zoom_focus(self, zoom, focus):
        """
        Zoom & Focus in the same command
        """
        print('Needs to be done')

    # ----------------------------------------------------
    # ---------------- WHITE BALANCE ---------------------
    # ----------------------------------------------------
    @property
    def WB(self):
        return self._query('WB')
    @WB.setter
    def WB(self, mode):
        if debug:
            print('WB', mode)
        if mode == 'auto':
            subcmd = '\x00'
        elif mode == 'indoor':
            subcmd = '\x01'
        elif mode == 'outdoor':
            subcmd = '\x02'
        elif mode == 'trigger':
            subcmd = '\x03'
        elif mode == 'manual':
            subcmd = '\x05'
        if 'subcmd' in locals():
        	prefix = '\x35'
        	subcmd = prefix + subcmd
        	return self._cmd_cam(subcmd)
        else:
        	return False

    def WB_trigger(self):
        return self._cmd_cam('\x10\x05')

    @property
    def RGain(self):
        return self._query('RGain')
    @RGain.setter
    def RGain(self, value):
        """
        Manual Control of R Gain
            :0..255 set the red gain
        """
        if debug:
            print('RGain', value)
        subcmd = "\x43" + i2v(value)
        return self._cmd_cam(subcmd)

    def RGain_reset(self):
        """
        Reset the Red Gain
        """
        return self._cmd_cam('\x03\x00')

    @property
    def BGain(self):
        return self._query('BGain')
    @BGain.setter
    def BGain(self, value):
        """
        Manual Control of B Gain
            :0..255 set the blue gain
        """
        if debug:
            print('BGain', value)
        subcmd = "\x44" + i2v(value)
        return self._cmd_cam(subcmd)

    def BGain_reset(self):
        """
        Reset the Blue Gain
        """
        return self._cmd_cam('\x04\x00')

    # ----------------------------------------------------
    # ----------------------  EXPOSURE -------------------
    # ----------------------------------------------------
    @property
    def AE(self):
        """
        define exposure mode :
            :auto = Automatic Exposure mode
            :manual = Manual Control mode
            :shutter = Shutter Priority Automatic Exposure mode
            :iris = Iris Priority Automatic Exposure mode
            :bright = Bright Mode (Manual control)
            Bright can be set only in Full Auto mode or Shutter Priority mode.
        """
        return self._query('AE')
    @AE.setter
    def AE(self, mode):
        if debug:
            print('AE', mode)
        if mode == 'auto':
            subcmd = "\x39\x00"
        elif mode == 'shutter':
            subcmd = "\x39\x0A"
        elif mode == 'manual':
            subcmd = "\x39\x03"
        elif mode == 'iris':
            subcmd = "\x39\x0B"
        elif mode == 'bright':
            subcmd = "\x39\x0D"
        if 'subcmd' in locals():
        	return self._cmd_cam(subcmd)
        else:
        	return False

    @property
    def slowshutter(self):
        """
        Auto Slow Shutter ON/OFF
        """
        return self._query('slowshutter')
    @slowshutter.setter
    def slowshutter(self, state):
        if debug:
            print('slowshutter', state)
        if state:
            subcmd = "\x5A\x02"
        else:
            subcmd = "\x5A\x03"
        return self._cmd_cam(subcmd)

    @property
    def shutter(self):
        return self._query('shutter')
    @shutter.setter
    def shutter(self, value):
        """
        Set shutter speed
        """
        if debug:
            print('shutter', value)
        subcmd = '\x4A' + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def iris(self):
        return self._query('iris')
    @iris.setter
    def iris(self, value):
        """
        Set iris aperture
        """
        if debug:
            print('iris', value)
        subcmd = '\x4B' + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def gain(self):
        """
        Set Gain in dB
        """
        return self._query('gain')
    @gain.setter
    def gain(self, value):
        if debug:
            print('gain', value)
        subcmd = '\x4C' + i2v(value)
        return self._cmd_cam(subcmd)

    def gain_limit(self, value):
        """
        AE Gain Limit (4-F)
        """
        if debug:
            print('gain_limit', value)
        subcmd = '\x2C' + value
        return self._cmd_cam(subcmd)

    @property
    def bright(self):
        """
        Set brightness
        """
        return self._query('bright')
    @bright.setter
    def bright(self, value):
        if debug:
            print('bright', value)
        subcmd = '\x4D\x00\x00' + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def expo_compensation(self):
        """
        exposure compensation on/off
        """
        return self._query('expo_compensation')
    @expo_compensation.setter
    def expo_compensation(self, state):
        if debug:
            print('expo_compensation', state)
        if state:
            subcmd = "\x3E\x02"
        else:
            subcmd = "\x3E\x03"
        return self._cmd_cam(subcmd)

    @property
    def expo_compensation_amount(self):
        """
        exposure compensation amount
        """
        return self._query('expo_compensation_amount')
    @expo_compensation_amount.setter
    def expo_compensation_amount(self, value):
        if debug:
            print('expo_compensation_amount', value)
        subcmd = '\x4E\x00\x00' + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def backlight(self):
        return self._query('backlight')
    @backlight.setter
    def backlight(self, state):
        if debug:
            print('backlight', state)
        if state:
            subcmd = "\x33\x02"
        else:
            subcmd = "\x33\x03"
        return self._cmd_cam(subcmd)

    @property
    def WD(self):
        """
        Wide Dynamic ON/OFF
        """
        return self._query('WD')
    @WD.setter
    def WD(self, state):
        if debug:
            print('WD', state)
        if state:
            subcmd = "\x3D\x02"
        else:
            subcmd = "\x3D\x03"
        return self._cmd_cam(subcmd)

    # todo : implement WD params

    @property
    def aperture(self):
        """
        Set aperture
        0 means no enhancement
        0 to 15
        """
        return self._query('aperture')
    @aperture.setter
    def aperture(self, value):
        if debug:
            print('aperture', value)
        subcmd = '\x42' + i2v(value)
        return self._cmd_cam(subcmd)

    @property
    def HR(self):
        """
        High-Resolution Mode ON/OFF
        :return:         True if successful, False if not
        :type state:      types.BooleanType
        :rtype:         types.BooleanType
        """
        return self._query('HR')
    @HR.setter
    def HR(self, state):
        if debug:
            print('HR', state)
        if state:
            subcmd = "\x52\x02"
        else:
            subcmd = "\x52\x03"
        return self._cmd_cam(subcmd)

    @property
    def NR(self):
        """
        Noise Reduction
            :0 is OFF
             :level 1..5
        """
        return self._query('NR')
    @NR.setter
    def NR(self, value):
        if debug:
            print('NR', value)
        subcmd = "\x53" + chr(value)
        return self._cmd_cam(subcmd)

    @property
    def gamma(self):
        """
        Gamma setting
            0: Standard
            1: Straight gamma
            2: S-curve - Low
            3: S-curve - Mid
            4: S-curve - High
        :return:         True if successful, False if not
        :type value:      types.IntType
        :rtype:         types.BooleanType
        """
        return self._query('gamma')
    @gamma.setter
    def gamma(self, value):
        if debug:
            print('gamma', value)
        subcmd = '\x5B' + chr(value)
        return self._cmd_cam(subcmd)

    @property
    def high_sensitivity(self):
        """
        High-Sensitivity Mode ON/OFF
        """
        return self._query('high_sensitivity')
    @high_sensitivity.setter
    def high_sensitivity(self, state):
        if debug:
            print('high_sensitivity', state)
        if state:
            subcmd = "\x5E\x02"
        else:
            subcmd = "\x5E\x03"
        return self._cmd_cam(subcmd)

    @property
    def FX(self):
        """
        Picture Effect Setting
            :normal / negart / BW
        """
        return self._query('FX')
    @FX.setter
    def FX(self, mode):
        if debug:
            print('FX', mode)
        if mode == 'Normal':
            subcmd = "\x63" + "\x00"
        if mode == 'NegArt':
            subcmd = "\x63" + "\x02"
        if mode == 'B&W':
            subcmd = "\x63" + "\x04"
        if 'subcmd' in locals():
        	return self._cmd_cam(subcmd)
        else:
        	return False

    @property
    def IR(self):
        """
        Infrared Mode ON/OFF
        """
        return self._query('IR')
    @IR.setter
    def IR(self, state):
        if debug:
            print('IR', state)
        if state:
            subcmd = "\x01" + "\x02"
        else:
            subcmd = "\x01" + "\x03"
        return self._cmd_cam(subcmd)

    @property
    def IR_auto(self):
        """
        Auto dark-field mode On/Off
        """
        return self._query('IR_auto')
    @IR_auto.setter
    def IR_auto(self, state):
        if debug:
            print('IR_auto', state)
        if state:
            subcmd = "\x51" + "\x02"
        else:
            subcmd = "\x51" + "\x03"
        return self._cmd_cam(subcmd)

    @property
    def IR_auto_threshold(self):
        """
        ICR ON → OFF Threshold Level
            :0..15
        """
        return self._query('IR_auto_threshold')
    @IR_auto_threshold.setter
    def IR_auto_threshold(self, level):
        if debug:
            print('IR_auto_threshold', level)
        subcmd = '\x21\x00\x00' + i2v(value)
        return self._cmd_cam(subcmd)

    # ----------- MEMORY -------------
    def _memory(self, func, num):
        if debug:
            print('memory', func, num)
        if num > 5:
            num = 5
        if func < 0 or func > 2:
            return False
        if debug:
            print("memory")
        num = int(num)
        subcmd = "\x3f" + chr(func) + chr(0b0111 & num)
        return self._cmd_cam(subcmd)

    def memory_reset(self, num):
        return self._memory(0x00, num)

    def memory_set(self, num):
        return self._memory(0x01, num)

    def memory_recall(self, num):
        return self._memory(0x02, num)

    # todo id_write

    @property
    def chromasuppress(self):
        """
        pp: Chroma Suppress setting level
        00: OFF
        1 to 3: ON (3 levels)
        Effect increases as the level number increases.
        """
        return self._query('chromasuppress')
    @chromasuppress.setter
    def chromasuppress(self, level):
        if debug:
            print('chromasuppress', level)
        subcmd = "\x5F" + chr(level)
        return self._cmd_cam(subcmd)

    @property
    def color_gain(self):
        """
        Color Gain setting 0h (60%) to Eh (200%)
        """
        return self._query('color_gain')
    @color_gain.setter
    def color_gain(self, value):
        if debug:
            print('color_gain', value)
        subcmd = "\x49\x00\x00\x00" + value
        return self._cmd_cam(subcmd)


    @property
    def color_hue(self):
        """
        Color Hue setting 0h (− 14 degrees) to Eh (+14 degrees)
        """
        return self._query('color_hue')
    @color_hue.setter
    def color_hue(self, value):
        if debug:
            print('color_hue', value)
        subcmd = "\x4F\x00\x00\x00" + value
        return self._cmd_cam(subcmd)

    # ----------------------------------------------------
    # ------------------ SYSTEM --------------------------
    # ----------------------------------------------------
    def menu_off(self):
        """
        Turns off the menu screen
        """
        if debug:
            print('menu_off')
        subcmd = '\x06' + '\x03'
        return self._cmd_cam_alt(subcmd)

    @property
    def video(self):
        """
        Return the state of the video (resolution + frequency)
        720:50
        """
        return self._query('video_next')
        print('need reboot')
    @video.setter
    def video(self, resfreq):
        if debug:
            print('video', resfreq)
        if resfreq == '1080PsF29.97':
            subcmd = "\x35" + "\x00" + "\x00"
        elif resfreq == '1080p29.97':
            subcmd = "\x35" + "\x00" + "\x01"
        elif resfreq == '720p59.94':
            subcmd = "\x35" + "\x00" + "\x02"
        elif resfreq == '720p29.97':
            subcmd = "\x35" + "\x00" + "\x03"
        elif resfreq == 'NTSC':
            subcmd = "\x35" + "\x00" + "\x04"
        elif resfreq == '1080PsF25':
            subcmd = "\x35" + "\x00" + "\x08"
        elif resfreq == '720p50':
            subcmd = "\x35" + "\x00" + "\x09"
        elif resfreq == '720p25':
            subcmd = "\x35" + "\x00" + "\x0A"
        elif resfreq == '1080i50':
            subcmd = "\x35" + "\x00" + "\x0B"
        elif resfreq == 'PAL':
            subcmd = "\x35" + "\x00" + "\x0C"
        if 'subcmd' in locals():
            print('need reboot')
            return self._cmd_cam_alt(subcmd)
        else:
            return False

    @property
    def IR_receive(self):
        """
        IR(remote commander) receive ON/OFF
        """
        return self._query('IR_receive')
    @IR_receive.setter
    def IR_receive(self, state):
        if debug:
            print('IR_receive', state)
        if state:
            subcmd = "\x02"
        else:
            subcmd = "\x03"
            prefix = '\x01\x06\x08'
        return self._cmd_cam(subcmd, prefix)

    # ----------- INFO DISPLAY-------------
    @property
    def info_display(self):
        """
        ON/OFF of the Operation status display
        of One Push Trigger of CAM_Memory and CAM_WB
        """
        return self._query('info_display')
    @info_display.setter
    def info_display(self, state):
        if debug:
            print('info_display', state)
        if state:
            subcmd = '\x02'
        else:
            subcmd = '\x03'
        prefix = '\x01\x7E\x01\x18'
        return self._cmd_cam(subcmd, prefix)

    # ----------------------------------------------------
    # ----------------------  PAN TILT -------------------
    # ----------------------------------------------------

    # FIX ME : Pan/Tilt Status Code List

    def _cmd_ptd(self, lr, ud):
        """
        simple shortcut to send _cmd_cam with pan_tilt_speed
        """
        subcmd = '\x01'+chr(self.pan_speed)+chr(self.tilt_speed)+chr(lr)+chr(ud)
        return self._cmd_cam_alt(subcmd)

    @property
    def pan_speed(self):
        return self._pan_speed
    @pan_speed.setter
    def pan_speed(self, speed):
        self._pan_speed = speed

    @property
    def tilt_speed(self):
        return self._tilt_speed
    @tilt_speed.setter
    def tilt_speed(self, speed):
        self._tilt_speed = speed

    def up(self):
        if debug:
            print('up')
        return self._cmd_ptd(0x03, 0x01)

    def down(self):
        if debug:
            print('down')
        return self._cmd_ptd(0x03, 0x02)

    def left(self):
        if debug:
            print('left')
        return self._cmd_ptd(0x01, 0x03)

    def right(self):
        if debug:
            print('right')
        return self._cmd_ptd(0x02, 0x03)

    def upleft(self):
        if debug:
            print('upleft')
        return self._cmd_ptd(0x01, 0x01)

    def upright(self):
        if debug:
            print('upright')
        return self._cmd_ptd(0x02, 0x01)

    def downleft(self):
        if debug:
            print('downleft')
        return self._cmd_ptd(0x01, 0x02)

    def downright(self):
        if debug:
            print('downright')
        return self._cmd_ptd(0x02, 0x02)

    def stop(self):
        if debug:
            print('stop')
        return self._cmd_ptd(0x03, 0x03)

    @property
    def pan(self):
        """
        pan
            :between -170 & 170
        """
        return self._query('pan_tilt')[0]
    @pan.setter
    def pan(self, pan):
        if debug:
            print('pan', pan)
        pan = degree_to_visca(pan, 'pan')
        pan = i2v(pan)
        tilt = degree_to_visca(self.tilt, 'tilt')
        tilt = i2v(tilt)
        subcmd = '\x02' + chr(self.pan_speed) + chr(self.tilt_speed) + pan + tilt
        self._cmd_cam_alt(subcmd)

    @property
    def tilt(self):
        """
        tilt
            :between -20 & 90 if flip == False
            :between -20 & 90 if flip == True
            : default flip is False
        """
        return self._query('pan_tilt')[1]
    @tilt.setter
    def tilt(self, tilt):
        if debug:
            print('tilt', tilt)
        pan = degree_to_visca(self.pan, 'pan')
        pan = i2v(pan)
        tilt = degree_to_visca(tilt, 'tilt')
        tilt = i2v(tilt)
        subcmd = '\x02' + chr(self.pan_speed) + chr(self.tilt_speed) + pan + tilt
        self._cmd_cam_alt(subcmd)

    def home(self):
        if debug:
            print('home')
        subcmd = '\x04'
        return self._cmd_cam_alt(subcmd)

    def reset(self):
        if debug:
            print('reset')
        subcmd = '\x05'
        return self._cmd_cam_alt(subcmd)
