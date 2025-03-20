#!/usr/bin/python3
'''
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
'''

import argparse
import json
import logging
import os
import re
import secrets
import ssl
import sys
import syslog
import threading
import time
from asyncio import InvalidStateError
from collections import namedtuple, deque
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from subprocess import run, CalledProcessError
import Hamlib
from tait import Tait

Node = namedtuple("Node", ["name", "frequency", "peer"])
Probe = namedtuple("Probe", ["id", "timestamp"])

# Set the EXPERIMENTAL pat option for aux callsign only
env = os.environ.copy()
env['FW_AUX_ONLY_EXPERIMENT']="1"

CONFIG = {}
STATUS = { 'mode': 'starting', 'max_passes': -1 }

#  Map of node -> fixed size queue (ring buffer) containing 0 (healthy) or 1 (unhealthy) for each probe
PROBE_HISTORY = {}
#  Map of node -> current state of the node
HEALTH_STATE = {}
#  Map of node -> the timestamp of the last healthy check of the node
LAST_HEALTHY = {}


# Return from check_health()
class Health(Enum):
    '''Enum possible health states. UNKNOWN implies not enough samples.'''
    HEALTHY = 1
    UNHEALTHY = 2
    UNKNOWN = 3


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

    # How much health history we should keep.  Anything more than health_window_size
    # is for human consumption through the web interface to assess historicl health.
    # Force this to be at least health_window_size.
    CONFIG['history_size'] = max(int(config_json.get("history_size", 60)),
                                 CONFIG['health_window_size'])

    # Optional processes to run before and/or after each pass
    CONFIG['pre_pass_process'] = config_json.get("pre_pass_process", None)
    CONFIG['post_pass_process'] = config_json.get("post_pass_process", None)

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

    CONFIG['pat_config'] = config_json.get('pat_config', None)

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

    # Build the list of Nodes
    CONFIG['nodes'] = []
    for nodeobj in config_json.get("nodes", []):
        node = Node(nodeobj["name"], nodeobj["frequency"], nodeobj["peer"])
        # The config file specifies a list of nodes with supporting information
        # (frequency and peer). We provide an option to limit the polling to a subset
        # of that list by specifying either the human friendly name or the peer id.
        #
        if args.nodes:
            # Skip this node if we can't find it in our list by name or peer id.
            if node.name not in args.nodes and node.peer not in args.nodes:
                continue
        CONFIG['nodes'].append(node)
        LAST_HEALTHY[node] = 0

    # HTTP server parameters
    CONFIG['http_address'] = config_json.get('http_address', '127.0.0.1')
    CONFIG['http_port'] = int(config_json.get('http_port', 8080))
    # Use of HTTPS is optional.  The server will only support one of the protocols at a time.
    CONFIG['use_https'] = str2bool(config_json.get("use_https", 'False'))
    CONFIG['https_key_file'] = config_json.get('https_key_file', './key.pem')
    CONFIG['https_cert_file'] = config_json.get('https_cert_file', './cert.pem')

    logging.info(f'config:\n{json.dumps(CONFIG,)}')

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

    # Initiate PROBE_HISTORY and HEALTH_STATE
    for node in CONFIG['nodes']:
        PROBE_HISTORY[node] = deque(maxlen=CONFIG['history_size'])
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

    if CONFIG['pre_pass_process']:
        logging.info(f"Running {CONFIG['pre_pass_process']}")
        run([CONFIG['pre_pass_process']], check=False)

    for node in CONFIG['nodes']:
        STATUS['mode'] = f'polling {node.name}'
        ret = check_health(node)

        # We explictly ignore return health of UNKNOWN. This indicates our probe failed locally
        # and we learned nothing about the remote health. Ignore this pass and try again later.
        if ret == Health.HEALTHY:
            PROBE_HISTORY[node].append(0)
            LAST_HEALTHY[node] = int(time.time())
        elif ret == Health.UNHEALTHY:
            PROBE_HISTORY[node].append(1)

    if CONFIG['post_pass_process']:
        logging.info(f"Running {CONFIG['post_pass_process']}")
        run([CONFIG['post_pass_process']], check=False)

    # Calculate the new health state
    new_health_state = calculate_health_state()

    # Handle the diff (Including reporting)
    global HEALTH_STATE
    diff_and_report_health_state(HEALTH_STATE, new_health_state)

    # Save the state
    HEALTH_STATE = new_health_state

    # Clean up
    clear_inbox()
    clear_sent()


class LocalRigError(Exception):
    '''Raise when there is a local radio error unrelated to the remote site.'''


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
    except LocalRigError:
        logging.error('Failed to transmit probe to node %s (local error)', node.name)
        # Cleanup non-empty outbox
        clear_outbox()
        return Health.UNKNOWN
    except (RuntimeError, CalledProcessError):
        logging.error('Failed to transmit probe to node %s!', node.name)
        # Cleanup non-empty outbox
        clear_outbox()
        return Health.UNHEALTHY

    return poll_for_probe(pending_probe)


def send_probe(node):
    probe = Probe(secrets.token_urlsafe(10), time.time())

    logging.info('Composing %s to %s at %s', probe.id, node.name, probe.timestamp)
    body = f"To {node.peer}, {node.frequency} at {int(probe.timestamp)}".encode()
    run_args = [CONFIG['pat'], '--send-only']
    if CONFIG['pat_config']:
        run_args.extend(['--config', CONFIG['pat_config']])
    run_args.extend(['compose', '-s', probe.id, CONFIG['rx_aux_callsign'], '-r', CONFIG['sender']])
    print(f'run_args is {run_args}')
    run(run_args, input=body, env=env, check=True)
    logging.info('Composed. Changing frequency to %s.', node.frequency)
    # Change frequency - we open and close the RIG handle to avoid fighting with VARA on the serial port
    # if it's being used for PTT (ex: IC-705). Doesn't matter for a DRA/Signalink.
    try:
        RIG.open()
        RIG.set_freq(Hamlib.RIG_VFO_CURR, int(node.frequency * 1e6))
        RIG.close()
    except (RuntimeError, InvalidStateError) as e:
        # If the error is while setting the frequency, don't blame the remote node.  Just retry next cycle.
        raise LocalRigError from e
    run([CONFIG['pat'], '-s', 'connect', f'varafm:///{node.peer}'], env=env, check=True)

    logging.info('Sent!')

    return probe

def poll_for_probe(probe):
    sleep_int = CONFIG['fetch_retry_interval_seconds']
    for i in range(CONFIG['fetch_retries_count']):
        logging.info('Try %d to fetch probe %s. Will sleep %d seconds first...', i+1, probe.id, sleep_int)

        # Sleep first to give the remote system time to handle the sent mail
        time.sleep(sleep_int)

        try:
            # Fetch pending mail
            rxd_probe_ids = fetch_all()
        except (CalledProcessError) as e:
            logging.error(f'Probe failure: {e}')
        else:
            # Check for our probe
            if probe.id in rxd_probe_ids:
                logging.info("Probe found!")
                return Health.HEALTHY

        # Exponential Backoff
        logging.info("Probe not found, sleeping...")
        sleep_int = 2*sleep_int

    logging.warning('Giving up on probe %s', probe.id)
    return Health.UNHEALTHY

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
        # Only look at the last health_window_size entries in history
        history = history[-CONFIG['health_window_size']:]
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

def health_state_dicts():
    states = []
    for (node, history) in PROBE_HISTORY.items():
        state = {}
        state['name'] = node.name
        state['peer'] = node.peer
        state['state'] = HEALTH_STATE[node]
        state['history'] = history_string(history) # return full history
        state['last_healthy'] = int(LAST_HEALTHY[node])
        states.append(state)
    return states

def history_string(history):
    '''Render the history as a string of + and - characters.'''
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
            if CONFIG['syslog_enabled']:
                syslog.syslog('STATE CHANGE: %s (%s) transitioned %s -> %s' % (node.name, node.peer, old[node], health))


def clear_inbox():
    '''Empty inbox folder. No .check_returncode because we may not have any (on failure).'''
    run(f"rm -f {CONFIG['mailbox_base']}/in/*", shell=True, check=False)

def clear_outbox():
    '''Empty outbox folder. No .check_returncode because we may not have any.'''
    run(f"rm -f {CONFIG['mailbox_base']}/out/*", shell=True, check=False)

def clear_sent():
    '''Empty sent folder. No .check_returncode because we may not have any.'''
    run(f"rm -f {CONFIG['mailbox_base']}/sent/*", shell=True, check=False)

def assert_outbox_empty():
    '''Assert the outbox is empty.'''
    if len(os.listdir(CONFIG['mailbox_base'] + "/out")) > 0:
        raise RuntimeError("Outbox is non-empty - We don't handle this yet")

def canary_status():
    '''Returns current status to answer web query on /status.'''
    if STATUS['mode'] == 'sleeping':
        STATUS['time_left'] = int(STATUS['sleep_start_time'] + CONFIG['next_pass_delay'] - time.time())
    else:
        STATUS['time_left'] = 0
    return {'status': STATUS, 'health': health_state_dicts() }


# Webserver to handle status requests

class Handler(BaseHTTPRequestHandler):
    '''Basis for diagnostic web interface'''

    def do_GET(self):
        if self.path == "/status":
            response = f'<pre>{json.dumps(canary_status(), indent=4)}</pre>\n'
        elif self.path == "/config":
            response = f'<pre>{json.dumps(CONFIG, indent=4)}</pre>\n'
        else:
            response = 'Help:\n/status - for current status of nodes\n/config - for configuration\n'
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(bytes(str(response), 'utf-8'))

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    '''Handle requests in a separate thread.'''

def create_httpserver():
    '''Start the webserver.'''
    server = ThreadedHTTPServer((CONFIG['http_address'], CONFIG['http_port']), Handler)
    if CONFIG['use_https']:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)  # Create SSL context
        context.load_cert_chain(certfile='./cert.pem', keyfile='./key.pem')  # Load cert and key
        server.socket = context.wrap_socket(server.socket, server_side=True)  # Wrap the socket

    server.serve_forever()

def sleep_between_passes():
    '''Besides sleeping, it records our current state and increments the pass count.'''
    STATUS['mode'] = 'sleeping'
    STATUS['sleep_start_time'] = int(time.time())
    STATUS['next_pass_delay'] = CONFIG['next_pass_delay']
    logging.info("sleeping for %s seconds...", {CONFIG['next_pass_delay']})
    time.sleep(CONFIG['next_pass_delay'])
    STATUS['sleep_start_time'] = 0
    STATUS['pass'] += 1


# MAIN

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--daemon', help='deamon mode (run continuously)', default=False, action='store_true')
    parser.add_argument('-c', '--count', help='number of passes to run', default='10', type=int)
    parser.add_argument('--next-pass-delay', help='time to wait between passes', default=0, type=int)
    parser.add_argument('-l', '--list', help='list systems available to test', action='store_true')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('config', help='configuration file')
    parser.add_argument('nodes', nargs='*', help='specific systems to test (either name or peer call)', default=[])
    args = parser.parse_args()

    STATUS['start_time'] = int(time.time())
    STATUS['pass'] = 1
    load_config(args)
    threading.Thread(target=create_httpserver, daemon=True).start()

    setup(args)
    if args.daemon:
        STATUS['max_passes'] = -1
        while True:
            run_loop_step()
            sleep_between_passes()
    else:
        STATUS['max_passes'] = args.count
        for count in range(int(args.count)):
            run_loop_step()
            if count < args.count - 1:
                sleep_between_passes()

if __name__ == "__main__":
    main()
