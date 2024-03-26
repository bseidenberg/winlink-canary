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
#  * There is currently no notification mechanism for failures. This will get written once the rest of everything is
#    working.

import argparse
import json
import logging
import os
import pprint
import re
import sys
import syslog
import time
import uuid
from collections import namedtuple, deque
from subprocess import run, CalledProcessError
import Hamlib
from tait import Tait

Node = namedtuple("Node", ["name", "frequency", "peer"])
Probe = namedtuple("Probe", ["id", "timestamp"])

# Set the EXPERIMENTAL pat option for aux callsign only
env = os.environ.copy()
env['FW_AUX_ONLY_EXPERIMENT']="1"

CONFIG = {}

#  Map of node -> fixed size queue (ring buffer) containing 0 (healthy) or 1 (unhealthy) for each probe
PROBE_HISTORY = {}
HEALTH_STATE = {}


def str2bool(arg):
    return arg.lower() in ['true', '1', 't', 'y', 'yes']


def load_config(args):
    '''Parse config file and do some config syntax and sanity checking.
       Aborts on detection invalid conifg file.
    '''
    config_json = json.load(open(args.config, 'r'))

    # Time to wait (seconds) between sending a probe and checking for it. There's then exponential backoff for the retries.
    CONFIG['fetch_retry_interval_seconds'] = int(config_json.get("fetch_retry_interval_seconds", 30))

    # Number of times to retry looking for a probe. (There's exponential backoff between them - see interval, above)
    CONFIG['fetch_retries_count'] = int(config_json.get("fetch_retries_count", 3))

    # How many runs we look back at for determining health
    CONFIG['health_window_size'] = int(config_json.get("health_window_size", 5))

    # How long to wait between passes (O(hours) - we don't want to hog the channel)
    if args.next_pass_delay > 0:
        delay = args.next_pass_delay
    else:
        delay = int(config_json.get("next_pass_delay", 3600))
    CONFIG['next_pass_delay'] = delay

    # How many of the last ${WINDOW_SIZE} runs that failed we treat as unhealthy.
    CONFIG['unhealthy_threshold'] = int(config_json.get("unhealthy_threshold", 3))

    # Whether to use syslog
    CONFIG['syslog_enabled'] = str2bool(config_json.get("syslog_enabled", 'False'))

    # DEDICATED_MAILBOX (True/False)
    # How to handle the outbox
    # True: if the mailbox being used is dedicated to this funciton, then we can
    #   assume anything we find in the outbox at the start of a pass is left over
    #   from an aborted run, and remove it.
    # False: if the mailbox being used is shared with a real user, then if we find
    #   any mail there, be extra cautious and abort until the user clears the mail.
    CONFIG['dedicated_mailbox'] = str2bool(config_json.get("dedicated_mailbox", 'False'))

    # Our Call
    try:
        CONFIG['pat_call'] = config_json['pat_call']
    except KeyError:
        sys.stderr.write("ERROR: Missing pat_call in config!\n")
        sys.exit(1)

    # TODO: Make this optional
    try:
        CONFIG['rx_aux_callsign'] = config_json['rx_aux_call']
    except KeyError:
        sys.stderr.write("ERROR: Missing rx_aux_call in config!\n")
        sys.exit(1)

    # Sender - It seems like WinLink supresses the message if the envelope header is the recipient
    try:
        CONFIG['sender'] = config_json['sender']
    except KeyError:
        CONFIG['sender'] = CONFIG['pat_call']


    # Mailbox location - Aux messages come into this mailbox FOR NOW - this may change
    # Note: The default is a.) linux-specific and b.) assumes pat > 0.12.
    #       The latter assumption should be fine since vara support also assumes this.
    #       The former assumption really should do more XDG lookups but eh (future TODO)
    CONFIG['mailbox_base'] = config_json.get(
        'mailbox_base_path', 
        f"{os.environ['HOME']}/.local/share/pat/mailbox/{CONFIG['pat_call']}")

    # Path to the pat binary
    CONFIG['pat'] = config_json.get("pat_bin_path", "pat")

    # Rig serial port path
    try:
        CONFIG['rig_port_path'] = config_json['rig_port']
    except KeyError:
        sys.stderr.write("ERROR: Missing rig_port in config!\n")
        sys.exit(1)

    # Rig serial port speed
    try:
        CONFIG['rig_port_speed'] = int(config_json['rig_port_speed'])
    except KeyError:
        sys.stderr.write("ERROR: Missing rig_port_speed in config!\n")
        sys.exit(1)

    try:
        model_str = config_json['rig_model']
        if model_str == "TAIT":
            # Skip Hamlib
            CONFIG['rig_model'] = "TAIT"
        else:
        # Sigh: There is (as of writing) exactly one constant that has a single lower-case letter
            if not re.match(r"^RIG_MODEL_[A-Za-z0-9_]+$", model_str):
                sys.stderr.write("ERROR: Invalid format for rig_model in config! See documentation for help.\n")
                sys.exit(1)
            # This is ugly, but this is the best way to do it
            CONFIG['rig_model'] = eval(f"Hamlib.{model_str}")
    except KeyError:
        sys.stderr.write("ERROR: Missing rig_model in config!\n")
        sys.exit(1)
    except AttributeError:
        sys.stderr.write(f"ERROR: Could not find model {model_str} in Hamlib. See documentation for help.\n")
        sys.exit(1)


    # Nodes
    # TODO: This is tricky - add better error messaging
    CONFIG['nodes'] = []
    for nodeobj in config_json.get("nodes", []):
        node = Node(nodeobj["name"], nodeobj["frequency"], nodeobj["peer"])
        if args.nodes:
            if node.name not in args.nodes and node.peer not in args.nodes:
                continue
        CONFIG['nodes'].append(node)

    if args.verbose:
        print('config:')
        pprint.pprint(CONFIG, indent=4)

    if args.list:
        for node in CONFIG['nodes']:
            print(f"{node.name}: {node.peer}, {node.frequency}")
        sys.exit(0)

def setup(args):
    '''Initialize key data structures and initialize radios and VARAFM modems.
       args - parsed arguemnts from argparse
    '''

    if args.verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)
    elif args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Check VARA's health
    pass # TODO

    # Initiate PROBE_HISTORY and HEALTH_STATE
    for node in CONFIG['nodes']:
        PROBE_HISTORY[node] = deque(maxlen=CONFIG['health_window_size'])
        HEALTH_STATE[node] = 'PENDING'

    # Instantiate Hamlib.
    # Note that we do not use rigctld because we want to open/close the serial port to allow VARA to share it and VARA
    # does not support rigctld
    global RIG
    if CONFIG['rig_model'] == "TAIT":
        RIG = Tait(CONFIG['rig_port_path'], CONFIG['rig_port_speed'])
    else:
        Hamlib.rig_set_debug(Hamlib.RIG_DEBUG_NONE) # Disable the very, very verbose logging that hamlib does by default
        RIG = Hamlib.Rig(rig_model=CONFIG['rig_model'])
        RIG.set_conf("rig_pathname", CONFIG['rig_port_path'])

    # Open syslog, if enabled
    if CONFIG['syslog_enabled']:
        syslog.openlog(ident="winlink_monitor")
        syslog.syslog("winlink_monitor running")

def run_loop_step():
    '''Check the health of each node.
       Append healty to the node's circular buffer of health status
       This is the main logic loop for the canary. We invoke this from inside a loop - each invocation is a step.

       Each step does the following:
       For each node, sends a probe over RF then polls over the internet to ensure it's recieved.
       Adds an entry to each node's health buffer for either healthy or unhealthy
       Checks the state of the buffer to calculate whether a node is HEALTHY, UNHEALTHY or PENDING (insufficient data)
       Determines which nodes changed states in this pass, and reports the change
    '''

    for node in CONFIG['nodes']:
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


def check_health(node):
    '''
    Checks the health of a node.
    Returns True for healthy, False for unhealthy
    '''

    if CONFIG['dedicated_mailbox']:
        clear_outbox()
    else:
        assert_outbox_empty()

    try:
        pending_probe = send_probe(node)
        assert_outbox_empty()
    except (RuntimeError, CalledProcessError):
        logging.error('Failed to transmit probe to node %s!', node.name)
        # Cleanup non-empty outbox
        clear_outbox()
        return False

    return poll_for_probe(pending_probe)


def send_probe(node):
    probe = Probe(str(uuid.uuid4()), time.time())

    logging.info('Composing %s to %s at %s', probe.id, node.name, probe.timestamp)
    body = f"Canary message sent to {node.name} on {node.frequency} at {probe.timestamp}".encode()
    run([CONFIG['pat'], 'compose', '-s', probe.id, CONFIG['rx_aux_callsign'], '-r', CONFIG['sender']], input=body, env=env, check=True)
    logging.info('Composed. Changing frequency to %s.', node.frequency)
    # Change frequency - we open and close the RIG handle to avoid fighting with VARA on the serial port
    # if it's being used for PTT (ex: IC-705). Doesn't matter for a DRA/Signalink.
    RIG.open()
    RIG.set_freq(Hamlib.RIG_VFO_CURR, int(node.frequency * 1e6))
    RIG.close()
    run([CONFIG['pat'], '-s', 'connect', f'varafm:///{node.peer}'], env=env, check=True)

    logging.info('Sent!')

    return probe

def poll_for_probe(probe):
    sleep_int = CONFIG['fetch_retry_interval_seconds']
    for i in range(CONFIG['fetch_retries_count']):
        logging.info('Try %d to fetch probe %s. Will sleep %d seconds first...', i+1, probe.id, sleep_int)

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

    logging.warning('Giving up on probe %s', probe.id)
    return False

def fetch_all():
    download_mail_via_telnet()
    return find_all_ids()

def download_mail_via_telnet():
    '''Run pat over telnet to download all of our pending messages'''
    run([CONFIG['pat'], 'connect', 'telnet'], env=env, check=True)

def find_all_ids():
    '''Find all ids in inbox.
       Basically grep Subject: $MAILBOX_DIR/* | cut -d : -f 2
       (OK... I just shelled out instead of writing it natively - exactly that)
       Returns a set of discovered ids.
    '''

    output = run(f"grep -h Subject {CONFIG['mailbox_base']}/in/* | cut -d : -f 2",
                 shell=True, capture_output=True, check=False).stdout
    return set(map(str.strip, output.decode('utf-8').splitlines()))


def calculate_health_state():
    state = {}
    for (node, history) in PROBE_HISTORY.items():
        logging.info('Probe History for %s (%s)\t%s', node.name, node.peer, history_string(history))
        if len(history) < CONFIG['health_window_size']:
            state[node] = 'PENDING'
            continue
        failed = sum(history)
        if failed >= CONFIG['unhealthy_threshold']:
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
        if old[node] != health:
            logging.warning('STATE CHANGE: %s (%s) transitioned %s -> %s', node.name, node.peer, old[node], health)
            if (CONFIG['syslog_enabled']):
                syslog.syslog('STATE CHANGE: %s (%s) transitioned %s -> %s' % (node.name, node.peer, old[node], health))



def clear_inbox():
    # No .check_returncode because we may not have any (on failure)
    run(f"rm {CONFIG['mailbox_base']}/in/*", shell=True, check=False)

def clear_outbox():
    # No .check_returncode because we may not have any
    run(f"rm {CONFIG['mailbox_base']}/out/*", shell=True, check=False)

def assert_outbox_empty():
    '''Assert the outbox is empty.'''
    if len(os.listdir(CONFIG['mailbox_base'] + "/out")) > 0:
        raise RuntimeError("Outbox is non-empty - We don't handle this yet")


# MAIN

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--daemon', help='deamon mode (run continuously)', default=False, action='store_true')
    parser.add_argument('-c', '--count', help='number of passes to run', default='10', type=int)
    parser.add_argument('--next-pass-delay', help='time to wait between passes', default=0, type=int)
    parser.add_argument('-l', '--list', help='list systems available to test', action='store_true')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('config', help='configuration file')
    parser.add_argument('nodes', nargs='*', help='specific systems to test (either name or peer call)', default=[])
    args = parser.parse_args()

    load_config(args)

    setup(args)
    if args.daemon:
        while True:
            run_loop_step()
            time.sleep(CONFIG['next_pass_delay'])
    else:
        for count in range(int(args.count)):
            run_loop_step()
            if count == args.count - 1:
                sys.exit(0)
            time.sleep(CONFIG['next_pass_delay'])
