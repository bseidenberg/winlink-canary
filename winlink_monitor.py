# Winlink/VARA node monitor
#
# This program is designed to act as a canary (health monitor) for the SeattleACS Winlink/VARA nodes. 
# It is designed to use Pat to periodically send messages through them, then verify the messages were readable through
# a telnet (internet) connection to Winlink CMS. 
#
# Copyright (C) 2021-2022 Benjamin Seidenberg, WY2K
#
# Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
#
#
# Current status: The script is currently in DRAFT status. While parts of it are tested, it is not yet ready for a 
# "first release"
#  * The program is currently designed to work with my IC-705, which I'm using for testing/development. A cheaper
#    target radio is intended for real use.
#  * We've discovered a set of conditions that allow us to completely crash the stable release of LinPBQ, which ACS
#    uses to run the nodes. The author has fixed the crash in the latest beta release, but the session still dies.
#    This appears to be triggered if there is a pending email in CMS for download, and you connect with Pat to our 
#    LinPBQ nodes via VARA in "Send-Only" mode. It seems to not matter whether or not there's actually a message to send
#    in the outbox or not.
#  * The overall flow and logic for health checking needs to be rewritten. Right now, we don't have the ability to 
#    detect and record errors on send, which seem to be far more problematic than messages vanishing between send
#    and recieve (which the original logic was written to detect). We should wrap each node in a seperate send/recieve
#    cycle, rather than sending all, then recieving all. 
#  * There is currently no notification mechanism for failures. This will get written once the rest of everything is
#    working.

import sys
import uuid
import time
import logging
import os
from collections import namedtuple, deque
from subprocess import run
import Hamlib

Node = namedtuple("Node", ["name", "frequency", "peer"])
Probe = namedtuple("Probe", ["id", "timestamp"])

# ----- CONFIGURATION HERE -------
NODES = [
    ## NOTE: Currently disabling all but Magnolia as we've found a pattern that crashes the nodes! 
    #        Magnolia is patched, the rest aren't
    # FIXME: Patch/Uncomment
    #Node("Beacon Hill #1", 430.800, "W7ACS-10"),
    #Node("Beacon Hill #2", 439.800, "W7ACS-10"),
    #Node("Capitol Hill #1", 430.950, "W7ACS-10"),
    #Node("Capitol Hill #2", 439.950, "W7ACS-10"),
    Node("Magnolia", 430.875, "W7ACS-10"),
    #Node("Northwest", 431.000, "W7ACS-10")
]

# Time to wait before trying to fetch the probes
FETCH_SLEEP = 2

# How many runs we look back at for determining health
WINDOW_SIZE = 5

# How many of the last ${WINDOW_SIZE} runs that failed we treat as unhealthy.
UNHEALTHY_THRESHOLD = 3

# Our Call
CALLSIGN = 'WY2K'

# Sender - It seems like WinLink supresses the message if the envelope header is the recipient
SENDER = 'ACS-WL' # FIXME DO NOT LIKE

# Mailbox location. 
MAILBOX_BASE = f"/home/astronut/.local/share/pat/mailbox/{CALLSIGN}"

# Path to the pat binary
PAT = '/usr/bin/pat'

# Instantiate Hamlib. This is effectively config as it's tunable.
# We do not use rigctld because we want to open/close the serial port to allow VARA to share it
# and VARA does not support rigctld 

# Rig Model
RIG = Hamlib.Rig(rig_model=Hamlib.RIG_MODEL_IC705)

# Serial port
RIG.set_conf("rig_pathname", "/dev/ttyACM0")


# ------ END CONFIGURATION -------

#  Map of node -> fixed size queue (ring buffer) containing 0 (healthy) or 1 (unhealthy) for each probe
PROBE_HISTORY = {}
HEALTH_STATE = {}

def setup():
    # FIXME
    logging.basicConfig(level=logging.DEBUG)


    
    # Check VARA's health
    pass
    # Initiate PROBE_HISTORY and HEALTH_STATE
    for node in NODES:
        PROBE_HISTORY[node] = deque(maxlen=WINDOW_SIZE)
        HEALTH_STATE[node] = 'PENDING'


'''
This is the main logic loop for the canary. We invoke this from inside a loop - each invocation is a step.

Each step does the following:
* Composes and sends a probe to each node we're monitoring. The probe has a subject with a tracked UUID.
* Sleeps for FETCH_SLEEP minutes
* Connects to the Winlink system over the internet via Telnet and fetches all pending probes
* Adds an entry to each node's health buffer for either healthy or unhealthy 

'''
def run_loop_step():
    pending_probes = {}

    # Send a probe to each node
    # TODO - Shuffle
    for node in NODES:
        pending_probes[node] = send_probe(node)

    # Sleep for N minutes
    print(f"PLACEHOLDER: Would sleep {FETCH_SLEEP} minutes")
    time.sleep(60 * FETCH_SLEEP)

    # Fetch all of the recieved probes
    rxd_probe_ids = fetch_all()
    print("DEBUG: Recieved ids: " + ', '.join(rxd_probe_ids))

    # Do the health check logic.
    for node in NODES:
        # Handle the current probe for the node
        probe = pending_probes[node]
        if probe.id in rxd_probe_ids:
            logging.info(f"Successfully retrieved probe {probe.id} which was sent to {node.name} at {probe.timestamp}")
            rxd_probe_ids.discard(probe.id)
            PROBE_HISTORY[node].append(0)
        else:
            logging.warning(f"Failed to retrieve probe {probe.id} which was sent to {node.name} at {probe.timestamp}")
            PROBE_HISTORY[node].append(1)
    
    # Calculate the new health state
    global HEALTH_STATE
    new_health_state = calculate_health_state(PROBE_HISTORY)

    # Handle the diff (Including reporting)
    diff_and_report_health_state(HEALTH_STATE, new_health_state)

    # Save the state
    HEALTH_STATE = new_health_state

    # Remove 
    clear_inbox()
    

def send_probe(node):
    probe = Probe(str(uuid.uuid4()), time.time())
    # Assert the outbox is empty
    if len(os.listdir(MAILBOX_BASE + "/out")) > 0:
        raise RuntimeError("Outbox is non-empty - We don't handle this yet")
    
    logging.info(f"Composing {probe.id} to {node.name} at {probe.timestamp}")
    body = f"Canary message sent to {node.name} on {node.frequency} at {probe.timestamp}".encode()
    run([PAT, 'compose', '-s', probe.id, CALLSIGN, '-r', SENDER], input=body).check_returncode()
    logging.info(f"Composed. Changing frequency to {node.frequency}..")
    # Change frequency - we open and close to avoid fighting with VARA on the serial port
    RIG.open()
    RIG.set_freq(Hamlib.RIG_VFO_CURR, int(node.frequency * 1e6))
    RIG.close()
    run([PAT, '-s', 'connect', f'vara:///{node.peer}'])

    logging.info(f"Sent!")

    # FIXME REMOVE
    time.sleep(1)

    return probe


def fetch_all():
    download_mail_via_telnet()
    return find_all_ids()

def download_mail_via_telnet():
    # Run pat over telnet to download all of our pending messages
    run([PAT, 'connect', 'telnet']).check_returncode()

def find_all_ids():
    # Basically grep Subject: $MAILBOX_DIR/* | cut -d : -f 2
    # (OK... I just shelled out instead of writing it natively - exactly that)
    output = run(f'grep -h Subject {MAILBOX_BASE}/in/* | cut -d : -f 2', shell=True, capture_output=True).stdout
    return set(map(str.strip, output.decode('utf-8').splitlines()))


def calculate_health_state(probe_history):
    state = {}
    for (node, history) in probe_history.items():
        if len(history) < WINDOW_SIZE:
            state[node] = 'PENDING'
            continue
        failed = sum(history)
        if (failed >= UNHEALTHY_THRESHOLD):
            state[node] = 'UNHEALTHY'
        else:
            state[node] = 'HEALTHY'
    return state


def diff_and_report_health_state(old, new):
    for (node, health) in new.items():
        if (old[node] != health):
            # TODO - Real reporting
            logging.info(f"STATE CHANGE: {node.name} transitioned {old[node]} -> {health}")
            

def clear_inbox():
    run(f'rm {MAILBOX_BASE}/in/*', shell=True).check_returncode()


if __name__ == "__main__":
    setup()
    # FIXME
    #while True:
    for i in range(10):
        run_loop_step()
