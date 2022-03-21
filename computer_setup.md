# Introduction
(TL;DR: The core of this guide explains how to set up Vara FM in Wine with a native Pat on Debian 11).

This guide was written as part of a project to build a Winlink/VARA FM monitoring node for the [Seattle Auxiliary Communications Service](https://www.seattleacs.org/). The intent of the project is to have a system that will connect to each of ACS's nodes and verify connectivity. The system will run Debian Linux, with VARA FM running in Wine connected to a native Pat (open source Winlink client). There will also be setup for rigctld for rig control.

This guide originally started out as notes for a full system build, including the OS install. However, I realized the most interesting part is the Pat and VARA FM setup, so I've moved everything else to appendices for sharing.

Note that as of the last update time of this guide (2021-11-14, unless I update it and forget to fix this sentence), the VARA support for Pat is "close to done" but not merged - we'll be building a fork to include it, but hopefully this will be merged into mainline soon - track the status of [this pull request](https://github.com/la5nta/pat/pull/280).


# Install PAT and do basic setup
Before we start dealing with the VARA integration, let's make sure that Pat is set up and working.

## Install
* Go to https://getpat.io
* Click the download links to get redirected to GitHub (as of 2021-11-07)
* Download the \*.deb that matches your platform with wget. (Ex: `wget https://github.com/la5nta/pat/releases/download/v0.12.0/pat_0.12.0_linux_amd64.deb`)
* Install the deb: `sudo dpkg -i pat_0.12.0_linux_amd64.deb` (Replace with your filename - likely a different version)

## Basic Setup
We'll configure Pat and make sure it's working with telnet now, and then come back with the VARA setup later. This assumes you've used Winlink before and have an account/password setup. If you don't, read the linked guide more carefully to do the initial setup. 

We are following https://github.com/la5nta/pat/wiki/The-command-line-interface

* Set your editor with `sudo update-alternatives --config editor`. I like Vim, but you do you.
* Run `pat configure` and modify the JSON
  * Set the mycall, secure_login_password and locator attributes to the correct values 
  * Leave the connect_aliases block and delete everything else. Make sure to delete the trailing comma from the last block.

Your config should look like this, replacing "YOURCALL", "YOURPASSWORD" and "YOURGRIDSQUARE" with the appropriate values. I used the 6-digit maidenhead grid for mine, 4 probably works too. Leave the "{mycall}" alone in the connect_aliases section, Pat will replace that automatically.

```
{
  "mycall": "YOURCALL",
  "secure_login_password": "YOURPASSWORD",
  "auxiliary_addresses": [],
  "locator": "YOURGRIDSQUARE",
  "service_codes": [
    "PUBLIC"
  ],
  "http_addr": "localhost:8080",
  "motd": [
    "Open source Winlink client - getpat.io"
  ],
  "connect_aliases": {
    "telnet": "telnet://{mycall}:CMSTelnet@cms.winlink.org:8772/wl2k"
  }
}

```
## Send a test email
Draft the message

* Run `pat compose`
* Hit enter for From:
* Type in your email address for To
* Hit Enter for Cc
* Hit "N" for P2P Only
* Subject: Test Email (or whatever you want)
* Press Enter
* Type a test message and save/close the editor
* Press Enter for Attachment

You should see "Message posted"

Send via Telnet

* Run `pat connect telnet`
* You should see logs indicating your message was sent
* Make sure it was received to your email correctly.

# Install Wine and VARA
Thanks to K6ETA, OE7DRT and KD7DK for their notes. I tried to minimize the setup to the smallest possible that works on Debian 11.

Via a graphical terminal (in VNC or your desktop setup), run these commands. IMPORTANT: They will not work if you try to run in a non-graphical environment (normal SSH session).

```
# Install Wine. Note that we MUST install the 32-bit wine so we can use VARA.
sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install wine32 wine winetricks exe-thumbnailer

# Set up the wine install. If you already have one, you probably want to add an export WINEPREFIX=<some other path> to set up a dedicated install
export WINEARCH=win32
winetricks -q win7 vb6run sound=alsa
```

(Note that some instructions you'll find tell you to run the winetricks dotnet35sp1 and vcrun2015. These appear to be needed for RMS Express but are not needed for VARA FM by itself.)

Download the VARA setup from https://rosmodem.wordpress.com/. Put the setup zip in your homedir (or adjust instructions accordingly

Unzip: `unzip VARA\ FM\ v4.1.4\ Setup.zip`

We appear to need to replace pdh.dll. This seems to be common. You can get a compatible version from K6ETA or OE7DRT's websites.
```
wget https://oe7drt.com/assets/files/pdh.dll.zip
unzip pdh.dll.zip
mv pdh.dll .wine/drive_c/windows/system32/pdh.dll
```

Now we're ready to install VARA:

```
wine VARA\ FM\ setup\ \(Run\ as\ Administrator\).exe 
```

If you leave the "Run My Program" checkbox checked at the end, VARA should start up.


# Set Up VARA
If you didn't do this earlier, ensure your user has permissions to access the serial port.  `sudo usermod -a -G dialout $USER`. Note that you will have to log out (or restart the VNC server) and then log back in again after you run this. 

Before you run VARA, figure out which serial ports are which with `ls -alF ~/.wine/dosdevices/`. You will see a number of lines that end in things like `com1 -> /dev/ttyS0`. Figure out the ones for your radio. If you set up the aliases above but don't see your own rig, `ls -alF /dev/<YOURRIG>` should tell you what the final destination is, which should match above. (TODO: Repoint symlink explicitly).

Now, run VARA:

`wine .wine/drive_c/VARA\ FM/VARAFM.exe `

Set it up just like in windows:
* Under Settings -> VARA Setup, put in your call and license key (if you have one)
* Under Settings -> Sound Card, select your sound card. Most USB soundcards (including Signalink, Digirig and both my ICOM rigs) look something like "USB Audio Codec".
* Under Settings -> PTT, set up your rig. For now, I'm using CAT control, setting it up with an ICOM 705 rig on the correct com port. The default serial speed is 1200, though this is changable in the 705's menu.

Now, test it out. Go back to Settings -> Sound Card, and hit "Ping". Tune your rig to a VARA Node near you (You can find one on the map at https://winlink.org/RMSChannels). Insert the station's call in the first box, and tune your rig to the appropriate frequency. Hit the power plug, and if you're lucky, you'll see a connection with S/N reports on both sides. You can now close that dialog and hit the "Auto Tune" button to adjust your levels.

If this doesn't work - you're own your own to debug, since this worked for me. Drop me a note with any suggested fixes!

## Switch to PulseAudio if needed (Only if you do not see your audio input in VARA)
On my original test system, this worked as-is. However on my laptop, the ALSA device for my rig did not show up in Wine. I have not debugged this further yet. One thing I want to test is if the device frees up/is exposed if I deselect it as the default in Pulse, which I had not done as of the test.

While some guides say that PulseAudio breaks VARA, it worked for me just fine. Here's how:
* Switch wine to use Pulse: `winetricks sound=pulse`
* Start VARA
* Run the Pulse Mixer: `pavucontrol`
* In the pulse mixer, on the "Output Devices" tab, make sure your normal speakers and NOT your rig are selected as default with the green checkbox.
* In the pulse mixer, on the "Input Devices" tab, make sure your normal microphone/input and NOT your rig are selected as default with the green checkbox.
* In the pulse mixer, on the Playback tab, find VARAFM.exe, and select the output device to your rig in the drop down box on the right. Make sure nothing else is using this output device.
* In the pulse mixer, on the Recording tab, find VARAFM.exe, and select the input device from your rig in the drop down box on the right.

Repeat the test above and make sure VARA is working)


# Set Up Pat to work with VARA
## Build and install the custom Pat with VARA support
At the time of writing (November 2021), there is active development to get Pat working with VARA, but it's not been integrated into the main release. This is probably going to happen soon. Until then, the state of the art is from Chris, K0SWE. We're going to use his fork of the Pat repo to build a custom deb and install it on top of the one we already have. This is likely to be mooted/out of date soon - track the status of [this pull request](https://github.com/la5nta/pat/pull/280).

Install build tools: `sudo apt install git build-essential debhelper libax25-dev`

We need to install a newer go from Debian Backports as well as make it the system go.

Set up Backports by adding this to /etc/apt/sources.list
```
# Backports
deb http://deb.debian.org/debian bullseye-backports main
deb-src http://deb.debian.org/debian bullseye-backports main

```

and then install it and point the system go at the new version:
```
sudo apt update
sudo apt install golang-1.16
# We need to point go at this version
sudo update-alternatives --install /usr/bin/go go /usr/lib/go-1.16/bin/go 50 --slave /usr/bin/gofmt gofmt /usr/lib/go-1.16/bin/gofmt
```

Now we can actually build the Pat fork/branch with VARA support.

Clone the repo: `git clone https://github.com/xylo04/pat.git`
Checkout the right branch:
```
cd pat
git checkout vara
```

Build and install
```
dpkg-buildpackage -d -us -uc
cd ..
sudo dpkg -i pat_0.12.0_amd64.deb
```

We should now be ready to go. Hopefully this step goes away soon.

## Configure
Set up the configuration: Run `pat configure` and add this to your config file:
```
  "vara": {
    "host": "localhost",
    "cmdPort": 8300,
    "dataPort": 8301
  }
```

This goes after the connect_aliases block, make sure to add the commas appropriately.

## Try it out

Make sure VARA-FM is running in your VNC session, your rig is tuned to the node, then run `pat connect vara:///<RMS NODE CALL>`.

If everything is working, you should be able to use Pat to send and receive like normal.

(I found that my original test system with a very old Atom CPU could not complete a session. I believe this was just insufficient CPU to do all of the VARA decoding. I was able to install on my laptop and work successfully there). 


# Appendix 1: Initial OS Setup for the remote monitoring system
## Install Debian 11.1 and configure networking
This is primarily left as an exercise to the reader. Some notes to get you started:
* I did a standard netinst USB install
* I did not install a GUI - just SSH server and base system. I then added VNC support as noted below. This is because this system is intended for headless operation. If you're doing this on a normal system, just add the graphical environment of your choice and skip the VNC below.
* If you are planing on running this in a stand-alone manner, I highly recommend against an encrypted disk

## Give your user access to the serial ports
You'll also want to ensure your user has access to the serial port: `sudo usermod -a -G dialout $USER`


## Ensure you can SSH into the thing
(If you're planning on operating headless/remotely, this is important. If not, feel free to skip this step)

* I added the non-free repositories and installed the appropriate wifi hardware firmware and network-manager to set up my wifi. If you aren't familiar with Debian, you can do this during the install instead. (I installed over ethernet)
* I used my router to give it a static DHCP mapping so that while it does DHCP, it always lands at the same IP. 
* I copied over my ssh public key for passwordless SSH

## Set up VNC for remote/headless operations.

I'm building this system to be used headless since it's for a dedicated project. If you're setting up normally (with a keyboard/mouse/monitor), you don't need this.

There are many different guides and instructions online; I followed https://atetux.com/how-to-install-tigervnc-on-debian-11 because it looked simpler than a couple others I looked at and I don't have a strong preference.

* Install xfce (Or the WM/DE of your choice) and tigervnc: `sudo apt install xfce4 xfce4-goodies dbus-x11 tigervnc-standalone-server`
* Set your password for VNC: `vncpasswd`
* Startup file: Create ~/.vnc/xstartup as follows:
```
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec /bin/sh /etc/xdg/xfce4/xinitrc
```
* Make executable `chmod +x ~/.vnc/xstartup`
* Run the server: `vncserver -localhost no`

(TODO: On Startup) (I don't care about this for now)


# Appendix 2: Set up consistent aliases for rig hardware devices

Your radio will generally present as two seperate devices to Linux that you'll need to interact with: an Audio Device (USB soundcard) and a CAT control interface. This may be native (more modern radios that plug in directly via USB) or you may be using a signalink or similar and a dedicated CAT cable with a UART inside. Or, you may not be using CAT at all and doing VOX-based PTT (or letting the Signalink or similar do so for you). 

While it isn't strictly neccessary, it's a good idea to use udev to set up consistent /dev/... paths for these devices. This solves the "Which COM port is it again?" problem - your radio is always /dev/ttyUSB FIXME TODO.

The instructions below are for the ICOM IC-705; your rig may be different.

## CAT Control (Serial Terminal)
These instructions assume your CAT control is via a USB-Serial interface, whether in the radio, in your interface cable or as a standalone USB-to-serial adapter.

The instructions on this can vary wildly depending on the radio used. For modern ICOM radios (7300, 9700, 705), https://www.florian-wolters.de/posts/ic705-serial-device-symlinks/ is the best guide I found. I'll happily take pull requests for links for other radios. 

(TODO: Generic UART Instructions here)

I set up my IC-705 to use /dev/ttyIC705a (CAT) and /dev/ttyIC705b (PTT). Whatever you set up, note it for later.

 
