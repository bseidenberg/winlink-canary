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


### unhealthy_threshold
** We treat a node as unhealthy if it failed `unhealthy_threshold` probes out of the last `health_window_size` probes we did.

_Type:_ Integer

_Required:_ no

_Default:_ 3



## Rig Control
    "rig_port": "/dev/ttyACM0",
    "rig_model": "RIG_MODEL_IC705",


## Monitored Node Configuration

# Sample Configuration
```
{
    "our_call": "WY2K",
    "sender": "ACS-WL",
    "mailbox_base_path": "/home/astronut/.local/share/pat/mailbox/",
    "pat_bin_path": "/usr/bin/pat",
    "fetch_sleep_seconds": 2,
    "fetch_retry_interval_seconds": 30,
    "fetch_retries_count": 3,
    "health_window_size": 5,
    "unhealthy_threshold": 3,
    "rig_port": "/dev/ttyACM0",
    "rig_model": "RIG_MODEL_IC705",
    "nodes": [
        {"name": "Beacon Hill #1", "frequency": 430.800, "peer": "W7ACS-10"},
        {"name": "Beacon Hill #2", "frequency": 439.800, "peer": "W7ACS-10"},
        {"name": "Capitol Hill #1", "frequency": 430.950, "peer": "W7ACS-10"},
        {"name": "Capitol Hill #2", "frequency": 439.950, "peer":"W7ACS-10"},
        {"name": "Magnolia", "frequency": 430.875, "peer":"W7ACS-10"},
        {"name": "Northwest","frequency": 431.000, "peer":"W7ACS-10"}
    ]
}
```