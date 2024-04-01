# Winlink Canary Configuration File Syntax

The Winlink Canary takes a JSON configuration file as the first argument to the program. While this document breaks the keys into logical sections, the actual configuration file is flat (other than the nodes array).

## Winlink/PAT Configuration
### pat_call
**The callsign we are using to connect to the winlink network.**

_Type:_ String

_Required:_ Yes

This callsign is what is used to connect to the winlink network. It is expected that the Pat config "telnet" will fetch messages for `rx_aux_call` using this call (so they end up in the mailbox for `pat_call`). Note that we will NOT fetch messages destined for `pat_call` directly, so long as
we're running pat >= 0.15.1.
 
(It's also assumed this is the over-the-air callsign but I don't actually think anything depends on this assumption.)

### rx_aux_call
***The callsign used as the recipient of our test messages.***

_Type:_ String

_Required:_ Yes (TODO: FIXME)

This callsign is used as the recipient of our health probes. It is recommended that this is a tactical call sign different from pat_call. This must be set up in the `auxiliary_addresses` section of the pat config.

With pat >= 0.15.1, we will ONLY fetch the auxillary address mail and not the pat_call mail.


### sender
**The email address or Winlink call that test messages are sent from**

_Type:_ String

_Required:_ No

This is the envelope header sender for the winlink message. There is no authenticaiton for this value. If unset, we default to pat_call.

**_Important Note:_** This value must be different than rx_ax_call because Winlink will drop messages addressed to the sender. 

### pat_bin_path
**The path to the pat binary.**

_Type:_ String

_Required:_ No

This should be the path to the pat binary (ex: `/usr/bin/pat`). 

If not specified, we simply invoke "pat" and rely on it being contained in the `PATH`.

### mailbox_base_path
**Path to the pat mailbox**

_Type:_ String

_Required:_ no

_Default:_ `$HOME/.local/share/pat/mailbox/`

(Dev TODO: Can we take a pat config and read this out instead?)

## Canary Tuning/Timing Settings
### fetch_retry_interval_seconds
**Initial time to wait between sending a probe and trying to retrieve it.**
_Type:_ Integer

_Required:_ no

_Default:_ 30

After we send a probe via RF, how long to wait before trying to fetch it via telnet. If it doesn't show up, we do exponential backoff and keep trying up to `fetch_retries_count` times.

### fetch_retries_count
**Number of times to retry looking for a probe.**
_Type:_ Integer

_Required:_ no

_Default:_ 3

Note that there's exponential backoff between each retry for a given probe.

### health_window_size
**How many runs we look back in time to decide whether a node is healthy**
_Type:_ Integer

_Required:_ no

_Default:_ 5

Note that you must have at least this many runs before a health state can be generated.


### next_pass_delay
**How long to wait between passes over a set nodes**
_Type:_ Integer

_Required:_ no

_Default:_ 3600

Its important that we don't hog the channel.  There is a tradeoff between minimizing channel use and detection time for broken nodes.  Should probably be O(hours).


### unhealthy_threshold
** We treat a node as unhealthy if it failed `unhealthy_threshold` probes out of the last `health_window_size` probes we did.

_Type:_ Integer

_Required:_ no

_Default:_ 3


### dedicated_mailbox
** If the mailbox is dedicated to this function, we will be more cavalier with mailbox cleanup.

_Type:_ Boolean

_Required:_ no

_Default:_ False

__How to handle the outbox:__
  - _True_: if the mailbox being used is dedicated to this funciton, then we can
    assume anything we find in the outbox at the start of a pass is left over
    from an aborted run, and remove it.
  - _False_: if the mailbox being used is shared with a real user, then if we find
    any mail there, be extra cautious and abort until the user clears the mail.


## Rig Control
** Currently, only TAIT 8100 ("TAIT") is supported but the goal is to support HamLib library radios.**

### rig_port
**Full pathname to rig control device**

_Type:_ String

_Required:_ yes

_Default:_ none

### rig_port
**Serial port speed for rig_port**

_Type:_ Integer

_Required:_ yes

_Default:_ none

This needs to be a supported speed, typically 9600.

### rig_model
**Name of the device as expected by HamLib or "TAIT"**

_Type:_ String

_Required:_ yes

_Default:_ none

## Monitored Node Configuration

## Reporting and Monitoring
### syslog_enabled
**Whether to log node health information (only) to syslog**

_Type_: Boolean

_Required:_ no

_Default:_ False

### http_address
**The address to listen on for new web connections

_Type:_ String

_Required:_ no

_Default:_ 127.0.0.1

### http_port
**The port to listen on for new web connections

_Type:_ Integer

_Required:_ no

_Default:_ 8080

### use_https
**The port to listen on for new web connections

_Type:_ Boolean

_Required:_ no

_Default:_ False

### https_key_file
**If using HTTPS, this specifies where the private key file is located

_Type:_ String

_Required:_ no

_Default:_ ./key.pem

### https_key_file
**If using HTTPS, this specifies where the certificate file is located

_Type:_ String

_Required:_ no

_Default:_ ./cert.pem

The webserver is provided principally to allow polling of the winlink_monitor for its
current status and the status of the monitored nodes.  The output is formatted json and
intended for easy parsing by other programs or administrators tracking issues.  The use
of HTTPS instead of HTTP is optional and the server will only support one of the protocols at a time.


# Sample Configuration

The options are discussed above.  **nodes** is a list of dictionaries that specify
the Winlink gateway's to be monitored.  The information includes:
 - name - human friendly name for the node
 - frequency - the frequency in megahertz of the winlink gateway
 - peer - the ssid of the winlink gateway


```
{
    "our_call": "WY2K",
    "sender": "ACS-WL",
    "pat_call": "W7ACS-1",
    "rx_aux_call": "ACS-WLCPWT",
    "mailbox_base_path": "/home/astronut/.local/share/pat/mailbox/",
    #"dedicated_mailbox": "True",
    "pat_bin_path": "/usr/bin/pat",
    "fetch_sleep_seconds": 2,
    "fetch_retry_interval_seconds": 30,
    "fetch_retries_count": 3,
    "health_window_size": 5,
    "unhealthy_threshold": 3,
    "rig_port": "/dev/ttyACM0",
    "rig_port_speed": "9600",
    "rig_model": "RIG_MODEL_IC705",
    # Example for TAIT
    #"rig_port": "/dev/ttyUSB_TAIT_UHF",
    #"rig_port_speed": "9600",
    #"rig_model": "TAIT",
    "syslog_enabled", "True",
    "nodes": [
        {"name": "Beacon Hill #1",  "frequency": 430.800, "peer": "W7ACS-10"},
        {"name": "Beacon Hill #2",  "frequency": 439.800, "peer": "W7ACS-11"},
        {"name": "First Hill #1",   "frequency": 430.850, "peer": "W7ACS-12"},
        {"name": "First Hill #2",   "frequency": 440.850, "peer": "W7ACS-13"},
        {"name": "Capitol Park #1", "frequency": 430.950, "peer": "W7ACS-14"},
        {"name": "Capitol Park #2", "frequency": 439.950, "peer": "W7ACS-15"},
        {"name": "Magnolia", "frequency": 430.875, "peer":"W7ACS-9"}
    ],
}
```
