from asyncio import InvalidStateError
import serial, numpy, logging, time
from enum import Enum

class Tait():

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
        self.sp = serial.Serial(port, speed, timeout=0.5)


    '''Uses CCDI mode to set to a pre-determined channel (requires preprogramming)'''
    def set_channel(self, channel):
        #TODO: Use send_tait_cmd instead
        self.enter_ccdi_mode()

        # Ensure type
        channel = int(channel)
        # Ensure in range
        assert channel >= 0
        assert channel <= 999

        # "GO_TO_CHANNEL"
        msg = ("g")
        # The channel number is sent as ASCII string numbers, NOT HEX
        chan_num_str = format(channel, 'd')
        # Append the size of the argument in hex format
        msg += format(len(chan_num_str), '02X')
        # Now append the channel number in decimal format
        msg += chan_num_str
        # Now append the checksum
        msg += self.checksum(msg)
        # We need a \r
        msg += '\r'
        
        # Send
        self.sp.write(bytes(msg, "utf-8"))

        # Look for an error coming back. Success should just be ".", an  error should be something like 
        # ".eXXXXXXXX". In the future we can actually parse these and recognize a bad command vs a bad channel ID, but
        # for now just throw and let the user look it up.
        ret = self.sp.read(20)
        if (len(ret) > 1):
            raise RuntimeError('Tait radio threw error: ', ret)
        
        logging.info("Changed to channel " + str(channel))

    '''Returns the current mode of the radio by querying it and inferring'''
    def get_current_mode(self):
        # Flush the buffer from previous state
        self.sp.read(100000)
        # Assume CCDI Mode, send a query
        self.sp.write(bytes("q002F\r", "utf-8"))
        ret = self.sp.read(20)
        if (ret.startswith(b"-")):
            return Tait.Mode.CCR
        elif ret.startswith(b".m08"):
            return Tait.Mode.CCDI
        else:
            raise InvalidStateError("Unknown response to status command: " + str(ret))


    '''Transitions from CCDI mode to CCR mode'''
    def enter_ccr_mode(self):
        current_mode = self.get_current_mode()
        if (current_mode == Tait.Mode.CCR):
            return
        elif (current_mode == Tait.Mode.CCDI):
            self.sp.write(bytes("f0200D8\r", "utf-8")) # See 7.5.1 of the Hardware Developer’s Kit Application Manual
            ret = self.sp.read(20)
            if (ret != bytes(".M01R00\r", "utf-8")): # 7.5.3
                raise InvalidStateError("The radio returned an invalid response when entering CCR: " + str(ret))
            return

    '''Go to CCDI mode (exit CCR mode). This is basically a reboot of the radio. No-op if we're already in CCDI 
    to avoid changing channels unexpectedly.'''
    def enter_ccdi_mode(self):
        current_mode = self.get_current_mode()
        if (current_mode == Tait.Mode.CCDI):
            return
        self.sp.write(b"^\r")
        # Wait for the radio to reboot
        time.sleep(5)
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
        self.ccr_set_rx_freq(freq)
        self.ccr_set_tx_freq(freq)
        #self.ccr_bandwidth(Tait.Bandwidth.WIDEBAND)
        #self.ccr_power(Tait.PowerLevel.HIGH)
    
    '''Set the RX frequency to freq, in hertz'''
    def ccr_set_rx_freq(self, freq):
        self.enter_ccr_mode()
        logging.info(f"Tuning to RX frequency {freq} in CCR mode")
        # "Go to Receive Frequency" (7.8.2)
        # The frequency is sent as ASCII string numbers, NOT HEX
        freq_str = format(freq, 'd')
        assert len(freq_str) >= 8 and len(freq_str) <= 9 # Per 7.8.2
        self.send_tait_cmd("R", freq_str)

        # Make sure we have an ack
        ret = self.sp.read(20)
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting rx freq: " + str(ret))

    '''Set the TX frequency to freq, in hertz'''
    def ccr_set_tx_freq(self, freq):
        self.enter_ccr_mode()
        logging.info(f"Tuning to TX frequency {freq} in CCR mode")
        # "Load Transmit Frequency" (7.8.3)
        # The frequency is sent as ASCII string numbers, NOT HEX
        freq_str = format(freq, 'd')
        assert len(freq_str) >= 8 and len(freq_str) <= 9 # Per 7.8.3
        self.send_tait_cmd("T", freq_str)

        # Make sure we have an ack
        ret = self.sp.read(20)
        if not ret.startswith(b"+"):
            raise InvalidStateError("The radio returned an error setting rx freq: " + str(ret))



    '''Send raw commands to the radio. Assumes the arg is a string (you must convert in advance)'''    
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
        # Send
        self.sp.write(bytes(msg, "utf-8"))
        # Checking response is up to the function  

    @staticmethod
    def checksum(cmd):
        total = 0
        for c in cmd:
            total += ord(c)
        checksum = numpy.uint8(total)
        return format(~checksum+1, '02X') 
    

