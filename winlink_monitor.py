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
#  * Logging needs to be cleaned up - and we need to figure out how to handle our output, pat's output, etc.
#  * It's currently way too aggressive. It sends a message, sleeps 30 seconds, then downloads it from the internet, 
#    then immediately moves to the next channel. The message send time is ~60s, so it's on-air ~66% of the time (and 
#    more TX than RX). This will hog the channels. We need to put in way more sleep.
#  * There is currently no notification mechanism for failures. This will get written once the rest of everything is
#    working.

import re
import sys
import uuid
import time
import logging
import os
import json
from collections import namedtuple, deque
from subprocess import run, CalledProcessError
import Hamlib
from tait import Tait

Node = namedtuple("Node", ["name", "frequency", "peer"])
Probe = namedtuple("Probe", ["id", "timestamp"])
NODES = []

# ----- CONFIGURATION HERE -------
# NODES = [
#     Node("Beacon Hill #1", 430.800, "W7ACS-10"),
#     Node("Beacon Hill #2", 439.800, "W7ACS-10"),
#     Node("Capitol Hill #1", 430.950, "W7ACS-10"),
#     Node("Capitol Hill #2", 439.950, "W7ACS-10"),
#     Node("Magnolia", 430.875, "W7ACS-10"),
#     Node("Northwest", 431.000, "W7ACS-10")
# ]
# ------ END CONFIGURATION -------

#  Map of node -> fixed size queue (ring buffer) containing 0 (healthy) or 1 (unhealthy) for each probe
PROBE_HISTORY = {}
HEALTH_STATE = {}

def load_config(config_file):
    config = json.load(open(config_file, 'r'))

    # Time to wait (seconds) between sending a probe and checking for it. There's then exponential backoff for the retries.
    global FETCH_RETRY_INTERVAL
    FETCH_RETRY_INTERVAL = int(config.get("fetch_retry_interval_seconds", 30))

    # Number of times to retry looking for a probe. (There's exponential backoff between them - see interval, above)
    global FETCH_RETRIES_COUNT
    FETCH_RETRIES_COUNT = int(config.get("fetch_retries_count", 3))

    # How many runs we look back at for determining health
    global WINDOW_SIZE 
    WINDOW_SIZE = int(config.get("health_window_size", 5))

    # How many of the last ${WINDOW_SIZE} runs that failed we treat as unhealthy.
    global UNHEALTHY_THRESHOLD
    UNHEALTHY_THRESHOLD = int(config.get("unhealthy_threshold", 3))

    # Our Call
    global CALLSIGN
    # TODO: I don't like our_call
    try:
        CALLSIGN = config['our_call']
    except KeyError:
        sys.stderr.write("ERROR: Missing our_call in config!\n")
        sys.exit(1)

    # Sender - It seems like WinLink supresses the message if the envelope header is the recipient
    global SENDER
    try:
        SENDER = config['sender']
    except KeyError:
        sys.stderr.write("ERROR: Missing sender in config!\n")
        sys.exit(1)

    # Mailbox location. 
    global MAILBOX_BASE
    # Note: The default is a.) linux-specific and b.) assumes pat > 0.12.
    #       The latter assumption should be fine since vara support also assumes this.
    #       The former assumption really should do more XDG lookups but eh (future TODO)
    MAILBOX_BASE = config.get(
        'mailbox_base_path', 
        f"{os.environ['HOME']}/.local/share/pat/mailbox/{CALLSIGN}")

    # Path to the pat binary
    global PAT
    PAT = config.get("pat_bin_path", "pat")

    # Rig serial port path
    global RIG_PORT_PATH
    try:
        RIG_PORT_PATH = config['rig_port']
    except KeyError:
        sys.stderr.write("ERROR: Missing rig_port in config!\n")
        sys.exit(1)

    global RIG_MODEL
    try:
        model_str = config['rig_model']
        if (model_str == "TAIT"):
            # Skip Hamlib
            RIG_MODEL = "TAIT"
        else:
        # Sigh: There is (as of writing) exactly one constant that has a single lower-case letter
            if not re.match(r"^RIG_MODEL_[A-Za-z0-9_]+$", model_str):
                sys.stderr.write("ERROR: Invalid format for rig_model in config! See documentation for help.\n")
                sys.exit(1)
            # This is ugly, but this is the best way to do it
            RIG_MODEL = eval(f"Hamlib.{model_str}")
    except KeyError:
        sys.stderr.write("ERROR: Missing rig_model in config!\n")
        sys.exit(1)
    except AttributeError:
        sys.stderr.write(f"ERROR: Could not find model {model_str} in Hamlib. See documentation for help.\n")
        sys.exit(1)

    
    # Nodes
    # TODO: This is tricky - add better error messaging 
    global NODES
    for nodeobj in config.get("nodes", []):
        node = Node(nodeobj["name"], nodeobj["frequency"], nodeobj["peer"])
        NODES.append(node)




# This is used for debugging but it's useful enough to leave here
def dump_config():
    print("FETCH_RETRY_INTERVAL: " + str(FETCH_RETRY_INTERVAL))
    print("FETCH_RETRIES_COUNT: " + str(FETCH_RETRIES_COUNT))
    print("WINDOW_SIZE : " + str(WINDOW_SIZE))
    print("UNHEALTHY_THRESHOLD: " + str(UNHEALTHY_THRESHOLD))
    print("CALLSIGN: " + CALLSIGN)
    print("SENDER: " + SENDER)
    print("MAILBOX_BASE: " + MAILBOX_BASE)
    print("PAT: " + PAT)
    print("NODES: " + str(NODES))
    print("RIG_PORT: " + RIG_PORT_PATH)
    print("RIG_MODEL: " + str(RIG_MODEL))

def setup():
    # FIXME
    logging.basicConfig(level=logging.DEBUG)
    
    # Check VARA's health
    pass # TODO

    # Initiate PROBE_HISTORY and HEALTH_STATE
    for node in NODES:
        PROBE_HISTORY[node] = deque(maxlen=WINDOW_SIZE)
        HEALTH_STATE[node] = 'PENDING'

    # Instantiate Hamlib. 
    # Note that we do not use rigctld because we want to open/close the serial port to allow VARA to share it and VARA
    # does not support rigctld 
    global RIG
    if (RIG_MODEL == "TAIT"):
        # TODO: Serial Speed via config
        RIG = Tait(RIG_PORT_PATH, 9600)
    else:
        Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE) # Disable the very, very verbose logging that hamlib does by default
        RIG = Hamlib.Rig(rig_model=RIG_MODEL)
        RIG.set_conf("rig_pathname", RIG_PORT_PATH)    



'''
This is the main logic loop for the canary. We invoke this from inside a loop - each invocation is a step.

Each step does the following:
* For each node, sends a probe over RF then polls over the internet to ensure it's recieved.
* Adds an entry to each node's health buffer for either healthy or unhealthy
* Checks the state of the buffer to calculate whether a node is HEALTHY, UNHEALTHY or PENDING (insufficient data)
* Determines which nodes changed states in this pass, and reports the change
'''
def run_loop_step():
    # Check the health of each node, and append it to the node's circular buffer of health status
    for node in NODES:
        success = check_health(node)
        if success:
            PROBE_HISTORY[node].append(0)
        else:
            PROBE_HISTORY[node].append(1)
    
    # Calculate the new health state
    new_health_state = calculate_health_state()

    # Handle the diff (Including reporting)
    global HEALTH_STATE
    diff_and_report_health_state(HEALTH_STATE, new_health_state)

    # Save the state
    HEALTH_STATE = new_health_state

    # Clean up
    clear_inbox()

'''
Checks the health of a node. Returns True for healthy, False for unhealthy
'''
def check_health(node):
    assert_outbox_empty()
    try: 
        pending_probe = send_probe(node)
        assert_outbox_empty
    except (RuntimeError, CalledProcessError):
        logging.error(f"Failed to transmit probe to node {node.name}!")
        # Cleanup non-empty outbox
        clear_outbox()
        return False

    return poll_for_probe(pending_probe)
    

def send_probe(node):
    probe = Probe(str(uuid.uuid4()), time.time())
    
    logging.info(f"Composing {probe.id} to {node.name} at {probe.timestamp}")
    body = f"Canary message sent to {node.name} on {node.frequency} at {probe.timestamp}".encode()
    run([PAT, 'compose', '-s', probe.id, CALLSIGN, '-r', SENDER], input=body).check_returncode()
    logging.info(f"Composed. Changing frequency to {node.frequency}..")
    # Change frequency - we open and close the RIG handle to avoid fighting with VARA on the serial port
    RIG.open()
    RIG.set_freq(Hamlib.RIG_VFO_CURR, int(node.frequency * 1e6))
    RIG.close()
    run([PAT, '-s', 'connect', f'vara:///{node.peer}']).check_returncode()

    logging.info(f"Sent!")

    return probe

def poll_for_probe(probe):
    sleep_int = FETCH_RETRY_INTERVAL
    for i in range(FETCH_RETRIES_COUNT):
        logging.info(f"Try {i+1} to fetch probe {probe.id}. Will sleep {sleep_int} seconds first...")
        # Sleep first to give the remote system time to handle the sent mail
        time.sleep(sleep_int)

        # Fetch pending mail
        rxd_probe_ids = fetch_all()

        # Check for our probe
        if probe.id in rxd_probe_ids:
            logging.info("Probe found!")
            return True
        
        # Exponential Backoff
        logging.info("Probe not found, sleeping...")
        sleep_int = 2*sleep_int
    
    logging.info(f"Giving up on probe {probe.id}")
    return False

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


def calculate_health_state():
    state = {}
    for (node, history) in PROBE_HISTORY.items():
        logging.info(f"Probe History for {node.name}\t{history_string(history)}")
        if len(history) < WINDOW_SIZE:
            state[node] = 'PENDING'
            continue
        failed = sum(history)
        if (failed >= UNHEALTHY_THRESHOLD):
            state[node] = 'UNHEALTHY'
        else:
            state[node] = 'HEALTHY'
    return state

def history_string(history):
    ret = ""
    for item in history:
        if item == 0:
            ret += "+"
        else:
            ret += "-"
    return ret



def diff_and_report_health_state(old, new):
    for (node, health) in new.items():
        if (old[node] != health):
            # TODO - Real reporting
            logging.info(f"STATE CHANGE: {node.name} transitioned {old[node]} -> {health}")
            

def clear_inbox():
    # No .check_returncode because we may not have any (on failure)
    run(f'rm {MAILBOX_BASE}/in/*', shell=True)

def clear_outbox():
    run(f'rm {MAILBOX_BASE}/out/*', shell=True).check_returncode()

def assert_outbox_empty():
    # Assert the outbox is empty
    if len(os.listdir(MAILBOX_BASE + "/out")) > 0:
        raise RuntimeError("Outbox is non-empty - We don't handle this yet")
    


# MAIN

if __name__ == "__main__":
    load_config(sys.argv[1])
    #dump_config()
    #sys.exit(0)


    setup()
    # FIXME
    #while True:
    for i in range(10):
        run_loop_step()
