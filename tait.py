import serial, numpy, logging

class Tait():
    def __init__(self, port, speed):
        # TODO: Tune timeout - think of it as how long we wait for the thing to complete
        self.sp = serial.Serial(port, speed, timeout=0.5)


    def set_channel(self, channel):
        # Flush the buffer from previous state
        self.sp.read(100000)

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
        ret = ser = self.sp.read(20)
        if (len(ret) > 1):
            raise RuntimeError('Tait radio threw error: ', ret)
        
        logging.info("Changed to channel " + str(channel))

    @staticmethod
    def checksum(cmd):
        total = 0
        for c in cmd:
            total += ord(c)
        checksum = numpy.uint8(total)
        return format(~checksum+1, '02X') 
    

