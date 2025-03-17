from asyncio import InvalidStateError
from enum import Enum
import logging
import time
import numpy
import serial


class Tait():
    # Number of times to attempt to write a serial command to the tait.
    TAIT_WRITE_TRIES = 10

    # The radio can be in several different modes, but we're most concerned with Computer-Controlled Data Interface 
    # (CCDI) and Computer-Controlled Radio (CCR) modes.
    #
    # CCDI is the "normal"-ish mode, we can basically change channels, fetch bits, etc.
    # CCR is the "advanced" mode where we bypass basically all of the onboard logic and directly set all of the VFO 
    # options.
    # 
    # The radio should start up in CCDI mode. Rather than tracking state as we go (and risking the radio getting 
    # out-of-sync with our view), we just always check the mode before each command and transition to the correct mode.
    class Mode(Enum):
        CCDI = 1
        CCR = 2
        UNKNOWN = 99

    '''Bandwidth settings for CCR mode'''
    class Bandwidth(Enum):
        NARROWBAND = 1
        MEDIUMBAND = 2
        WIDEBAND = 3

    '''Power Level settings for CCR mode'''
    class PowerLevel(Enum):
        # 7.8.13
        VERY_LOW = 1
        LOW = 2
        MEDIUM = 3
        HIGH = 4

    def __init__(self, port, speed):
        # TODO: Tune timeout - think of it as how long we wait for the thing to complete
        self.sp = serial.Serial(port, speed, timeout=2, inter_byte_timeout=0.2)
        self.mode = Tait.Mode.UNKNOWN
        self.retries = 0


    '''Uses CCDI mode to set to a pre-determined channel (requires preprogramming)'''
    def set_channel(self, channel):
        #TODO: Use send_tait_cmd instead
        self.enter_ccdi_mode()

        # Ensure type
        channel = int(channel)
        # Ensure in range
        assert channel >= 0
        assert channel <= 999

        # The channel number is sent as ASCII string numbers, NOT HEX
        chan_num_str = format(channel, 'd')

        # "GO_TO_CHANNEL"
        ret = self.send_tait_cmd("g", chan_num_str)
        # Look for an error coming back. Success should just be ".", an  error should be something like 
        # ".eXXXXXXXX". In the future we can actually parse these and recognize a bad command vs a bad channel ID, but
        # for now just throw and let the user look it up.
        if (len(ret) > 1):
            raise RuntimeError('Tait radio threw error: ', ret)
        logging.info("Changed to channel " + str(channel))

    '''Returns the cached current mode'''
    def get_current_mode(self):
        if self.mode == Tait.Mode.UNKNOWN:
            return self.get_current_mode_radio()
        return self.mode

    '''Returns the current mode of the radio by querying it and inferring'''
    def get_current_mode_radio(self):
        # Flush the buffer from previous state
        self.sp._reset_input_buffer()
        # Assume CCDI Mode, send a query
        ret = self.send_tait_cmd('q', '')
        if (ret.startswith(b"-")):
            self.mode = Tait.Mode.CCR
        elif ret.startswith(b".m08"):
            self.mode =  Tait.Mode.CCDI
        else:
            raise InvalidStateError("Unknown response to status command: " + str(ret))
        logging.debug(f"get_current_mode_radio: mode {self.mode}")
        return self.mode


    '''Transitions from CCDI mode to CCR mode'''
    def enter_ccr_mode(self):
        logging.debug("enter_ccr_mode()")
        current_mode = self.get_current_mode()
        if (current_mode == Tait.Mode.CCR):
            logging.debug("enter_ccr_mode() - no action")
            return
        elif (current_mode == Tait.Mode.CCDI):
            # Clear the buffer - we've seen extraneous .'s
            logging.debug("enter_ccr_mode() - sending transition command")
            self.sp._reset_input_buffer()
            self.sp.write(bytes("f0200D8\r", "utf-8")) # See 7.5.1 of the Hardware Developer’s Kit Application Manual
            ret = self.sp.read_until(b"\r")
            if (ret != bytes(".M01R00\r", "utf-8")): # 7.5.3
                raise InvalidStateError("The radio returned an invalid response when entering CCR: " + str(ret))
            self.mode = Tait.Mode.CCR
            return

    '''Go to CCDI mode (exit CCR mode). This is basically a reboot of the radio. No-op if we're already in CCDI 
    to avoid changing channels unexpectedly.'''
    def enter_ccdi_mode(self):
        current_mode = self.get_current_mode()
        if (current_mode == Tait.Mode.CCDI):
            logging.debug(f"enter_ccdi_mode() - no action")
            return
        logging.debug(f"enter_ccdi_mode() - resetting radio")
        self.sp.write(b"^\r")
        # Wait for the radio to reboot
        time.sleep(5)
        # Reset the mode flag
        self.mode = self.Mode.UNKNOWN
        logging.debug("enter_ccdi_mode() - mode UNKNOWN")
        return

    '''Hamlib compatible simplex frequency set wrapper'''
    def set_freq(self, vfo, frequency):
        self.tune_radio(frequency)

    '''No-op open method to duck-type the usage of hamlib'''
    def open(self):
        return

    '''No-op open method to duck-type the usage of hamlib'''
    def close(self):
        return
        

    '''Short-cut to tune the radio to a given simplex freq'''
    def tune_radio(self, freq):
        self.mode = Tait.Mode.UNKNOWN
        self.ccr_set_rx_freq(freq)
        self.ccr_set_tx_freq(freq)
        #self.ccr_bandwidth(Tait.Bandwidth.WIDEBAND)
        self.ccr_set_powerlevel(Tait.PowerLevel.LOW)
    
    '''Set the RX frequency to freq, in hertz'''
    def ccr_set_rx_freq(self, freq):
        logging.info(f"Tuning to RX frequency {freq} in CCR mode")
        self.enter_ccr_mode()
        # "Go to Receive Frequency" (7.8.2)
        # The frequency is sent as ASCII string numbers, NOT HEX
        freq_str = format(freq, 'd')
        assert len(freq_str) >= 8 and len(freq_str) <= 9 # Per 7.8.2
        ret = self.send_tait_cmd("R", freq_str)
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting rx freq: " + str(ret))

    '''Set the TX frequency to freq, in hertz'''
    def ccr_set_tx_freq(self, freq):
        logging.info(f"Tuning to TX frequency {freq} in CCR mode")
        self.enter_ccr_mode()
        # "Load Transmit Frequency" (7.8.3)
        # The frequency is sent as ASCII string numbers, NOT HEX
        freq_str = format(freq, 'd')
        assert len(freq_str) >= 8 and len(freq_str) <= 9 # Per 7.8.3
        ret = self.send_tait_cmd("T", freq_str)
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting rx freq: " + str(ret))
    
    '''Set the bandwidth. bandwidth must be a Tait.Bandwidth enum value'''
    def ccr_set_bandwidth(self, bandwidth):
        logging.info(f"Setting bandwidth to {bandwidth} in CCR mode")
        assert type(bandwidth) == Tait.Bandwidth
        # 7.8.14  - Bandwidth is sent as a decimal number 1-3
        arg_str = str(bandwidth.value)
        assert len(arg_str) == 1
        ret = self.send_tait_cmd("H", arg_str)
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting bandwidth: " + str(ret))

    '''Set the power level. power must be a Tait.Bandwidth enum value'''
    def ccr_set_powerlevel(self, power):
        logging.info(f"Setting power level to {power} in CCR mode")
        assert type(power) == Tait.PowerLevel
        # 7.8.13 - Power is sent as a decimal number 1-4
        arg_str = str(power.value)
        assert len(arg_str) == 1
        ret = self.send_tait_cmd("P", arg_str)
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting power level: " + str(ret))

    '''
    Sets the Transmit CTCSS tone. Set 0 to disable.
    The valid range is 67Hz to 254.1 Hz in 0.1 hz increments or 0 to disable
    '''
    def ccr_set_tx_ctcss(self, ctcss_tone_freq_hz):
        assert ctcss_tone_freq_hz == 0 or (ctcss_tone_freq_hz >= 67 and ctcss_tone_freq_hz <= 254.1)
        # We set this to how many 10th's of hz we want as a 4 digit string. So, we need to multiply by 10 and then take
        #  the int value to truncate anything more fine-grained than 0.1hz. Then we convert back to string and lpad to 
        # 4 chars (7.8.6)
        arg_str = str(int(ctcss_tone_freq_hz * 10)).zfill(4)
        assert len(arg_str) == 4
        ret = self.send_tait_cmd("B", arg_str)
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting TX CTCSS tone: " + str(ret))


    '''
    Sets the Recieve CTCSS tone. Set 0 to disable. If set, mutes audio unless tone is present
    The valid range is 67Hz to 254.1 Hz in 0.1 hz increments or 0 to disable
    '''
    def ccr_set_rx_ctcss(self, ctcss_tone_freq_hz):
        assert ctcss_tone_freq_hz == 0 or (ctcss_tone_freq_hz >= 67 and ctcss_tone_freq_hz <= 254.1)
        # We set this to how many 10th's of hz we want as a 4 digit string. So, we need to multiply by 10 and then take
        #  the int value to truncate anything more fine-grained than 0.1hz. Then we convert back to string and lpad to 
        # 4 chars (7.8.5)
        arg_str = str(int(ctcss_tone_freq_hz * 10)).zfill(4)
        assert len(arg_str) == 4
        ret = self.send_tait_cmd("A", arg_str)
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting RX CTCSS tone: " + str(ret))



    '''
    Query radio with Query Radio Pulse (manual 7.8.15). Radio will respond QssPCC if the radio has
    a minimum configuration (having received a 'set receive frequency', or QssDCC if the radio is
    still at its default (startup) configuration.
    '''
    def ccr_query_radio_pulse(self):
        ret = self.send_tait_cmd("Q", "P")
        # Make sure we have an ack
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error on Pulse query: " + str(ret))



    '''
    Send raw commands to the radio. Assumes the arg is a string (you must convert in advance).

    At least one of the author's Tait radios has a nasty habit of not responding sometimes. So, we're going to do retries.

    '''    
    def send_tait_cmd(self, cmd, arg_str):

        # Start with the cmd
        msg = str(cmd)
        assert len(msg) == 1
        # Append the size of the argument in hex format
        msg += format(len(arg_str), '02X')
        # Now append argument string
        msg += arg_str
        # Now append the checksum
        msg += self.checksum(msg)
        # We need a \r
        msg += '\r'

        for i in range(self.TAIT_WRITE_TRIES):
            logging.debug(f"send_tait_cmd(): msg: {msg}\n")
            # Check for spurious input
            if self.sp.in_waiting:
                nchars = self.sp.in_waiting
                logging.debug(f"send_tait_cmd(): pending input ({nchars} chars)!")
                ret = self.sp.read(size=nchars)
                logging.debug(f"send_tait_cmd(): pending input was '{str(ret)}'")
            # Send
            self.sp.write(bytes(msg, "utf-8"))
            # Return the response back to the caller
            ret = self.sp.read_until(b"\r")

            # The most common failure mode we've seen is on the SACS UHF Tait:
            #  A command will be sent and we will not get any reply back.
            #  If we retry the command, we get a checksum error, but it will work on the third try.
            #  This probbaly indicates some sort of corruption on send (the newline doesn't make it through?)
            #  or internal to the radio.
            # TODO FIXME: let's only retry on specific errors (eg, checksum errors) and pass the rest upstream
            if ret != b'' and (self.mode != self.Mode.CCR or str(ret).startswith("b'+")):
                if i > 0:
                    logging.debug(f"send_tait_cmd(): succeeded after {i} retries")
                logging.debug(f"send_tait_cmd(): returning '{str(ret)}'")
                return ret
            if self.mode == self.Mode.CCR and str(ret).startswith("b'.m08"):
                # This is a sign we are in CDDI mode when we want to be in CCR mode. 
                logging.debug(f"send_tait_cmd(): CDDI mode detected, unsolicited message '{str(ret)}'")
                # drain any other pending data and retry
                ret = self.sp.read_until(b"\r")
                logging.debug(f"send_tait_cmd(): drained '{str(ret)}'")
                raise InvalidStateError(f"The radio is in CDDI mode instead of CCR mode.")
            logging.debug(f"send_tait_cmd(): bad response '{str(ret)}', retrying")
            self.retries += 1
            self.sp.reset_input_buffer()
            time.sleep(0.5)

        raise InvalidStateError(f"The radio failed to respond after {str(self.TAIT_WRITE_TRIES)} tries.")

    @staticmethod
    def checksum(cmd):
        total = 0
        for c in cmd:
            total += ord(c)
        checksum = numpy.uint8(total)
        return format(~checksum+1, '02X')
