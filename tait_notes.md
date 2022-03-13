# Notes on Programming/Controlling the Tait TM8100 Data Radio

I was given a Tait 8105 that covers the 2 meter band for testing. The plan for this project is to ultimately use one for the 70 cm band. The radio had previously been set up by a fellow club member, so I do not have notes on scratch programming or interface cables. The radio was given to me with an RA-25 digital interface pre-connected and a serial interface on the front port.

Note that there are some special wiring concerns for the radio. I was given mine with cables already included but see [here](http://tarpn.net/t/builder/tait_tm8105_notes/builders_radios_tait8105.html) for more information.

## PTT
Vara FM under Wine does not trigger the CM 108 GPIO pin for PTT. There is some discussion about this issue [here](https://github.com/WheezyE/Winelink/issues/10) and in other places. This is potentially going to be fixed in the future.

For my purposes, I was able to use Pat and Hamlib to control the PTT. This was done by running rigctld with just PTT:
```
sudo rigctld  -p /dev/hidraw2 -P CM108  -C ptt_bitnum=2 -t <PORT>
```

(Ensuring the /dev/hidraw\* device has a programmatic name and setting up permissions so it doesn't have to run as root are left as an udev-rule-writing exercise to the user I'll get to Soon(tm)).

(Note: At one point, I found during my experimentation I found that hamlib enabling PTT disabled my laptop's keyboard until I unplugged it; this may or may not be an issue with the final setup. This was resolvable with `xinput disable <id>` (where `<id>` was the id number that showed up for the CM108 when I ran xinput with no arguments).)

Then, I tell Pat about it by adding these sections to the config file:
```
  "vara": {
    "host": "localhost",
    "cmdPort": 8300,
    "dataPort": 8301,
    "ptt_ctrl": true,
    "rig": "ptt_rig"
  },
  "hamlib_rigs": {
    "ptt_rig": {"address": "localhost:<PORT>", "network": "tcp"}
  }
```

Things were happy after that.

## Computer Control
### Serial Comms
For my radio, I had to change the serial port for command mode and re-program the radio. (I have no idea what the default is). This is done in the programming software under Data -> Serial Communications -> Data Port. I had to change it to "Front Mic" as that's where I had the adapter plugged in. This is going to be very dependent on your exact setup.

Once I changed this, I found that the command mode tended to interfere with programming mode. (Once the radio booted into command mode, it wouldn't respond to programming commands). However, the radio will be in programming mode for some period after startup before changing to command mode. I found the best way to handle this was to start an operation (read/interrogate/write) on the computer with the radio depowered, then power the radio as soon as the operation started, and then they got in sync.

Once this was done, I was able to interact with the radio using a serial terminal (gtkterm) and via pyserial from the ipython interactive shell.

### Command Checksums
There are two modes for the radio. Computer Controlled Data Interface (CCDI) is basic control - changing channels primarily. (See the TM8100 Computer Controlled Data Interface (CCDI) Protocol Manual). Computer Controlled Radio (CCR) mode allows (and requires) configuring all aspects of the radio directly from the computer. (See section 7 of the 3DK Hardware Developer’s Kit Application Manual).

Both modes are built around textual serial protocols. Numbers are sent as ASCII hex digits, etc. Both require a checksum sent with each message, and share the same checksum function. This function is documented in section 4.3 of the TM8100 Computer Controlled Data Interface (CCDI) Protocol Manual and 7.4.2 of the Hardware Developer’s Kit Application Manual.

A python implementation for the checksum function is below:
```
def checksum(cmd):
    total = 0
    for c in cmd:
         total += ord(c)
    checksum = numpy.uint8(total)
    return format(~checksum+1, '02X') 
```

### Go to Channel command
I was able to implement the GO_TO_CHANNEL command as described in the manual. The implementation is in the tait.py file in this repository. 