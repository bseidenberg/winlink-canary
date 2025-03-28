#!/usr/bin/python3
#
# Tait Radio Interface Tester
#
# Copyright (C) 2021-2025 Benjamin Seidenberg WY2K, Doug Kingston KD7DK
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
# This is a diagnostic program. This program is intended to stress tait.py and the radio's serial
# control to ensure that we don't have flaky control channel (which we thought we we seeing).
# The program helped prove that at least in the absence of RF feedback the system was stable.
#
# Current status: Ready for initial release.

import argparse
import json
import logging
import os
import pprint
import re
import sys
import time
from collections import namedtuple
import Hamlib
from tait import Tait

Node = namedtuple("Node", ["name", "frequency", "peer"])

# Set the EXPERIMENTAL pat option for aux callsign only
env = os.environ.copy()
env['FW_AUX_ONLY_EXPERIMENT']="1"

CONFIG = {}
STATUS = { 'mode': 'starting' }


def str2bool(arg):
    return arg.lower() in ['true', '1', 't', 'y', 'yes']

def load_config(args):
    '''Parse config file and do some config syntax and sanity checking.
       Aborts on detection invalid conifg file.
    '''
    config_json = json.load(open(args.config, 'r'))

    # How long to wait between passes (O(hours) - we don't want to hog the channel)
    if args.next_pass_delay > 0:
        delay = args.next_pass_delay
    else:
        delay = int(config_json.get("next_pass_delay", 3600))
    CONFIG['next_pass_delay'] = delay

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
        CONFIG['nodes'].append(node)

    # HTTP server parameters
    CONFIG['http_address'] = config_json.get('http_address', '127.0.0.1')
    CONFIG['http_port'] = int(config_json.get('http_port', 8080))
    # Use of HTTPS is optional.  The server will only support one of the protocols at a time.
    CONFIG['use_https'] = str2bool(config_json.get("use_https", 'False'))
    CONFIG['https_key_file'] = config_json.get('https_key_file', './key.pem')
    CONFIG['https_cert_file'] = config_json.get('https_cert_file', './cert.pem')

    if args.verbose:
        # This needs to be fixed to ouput a string for using in logging.info()
        pprint.pprint(CONFIG, indent=4)

def setup(args):
    '''Initialize key data structures and initialize radios and VARAFM modems.
       args - parsed arguemnts from argparse
    '''
    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 2 else logging.INFO if args.verbose == 1 else logging.WARNING,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)]
    )

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

def run_test():
    RIG.open()
    for node in CONFIG['nodes']:
        logging.debug(f'setting frequency {node.frequency}')

        try:
            RIG.set_freq(Hamlib.RIG_VFO_CURR, int(node.frequency * 1e6))
        except RuntimeError as e:
            print(f'RIG error on set_freq({node.frequency}): {e}')

        try:
            mode = RIG.get_current_mode()
        except RuntimeError as e:
            print(f'RIG error on get_current_mode_radio: {e}')

        time.sleep(0.1)
    RIG.close()

# MAIN

def sleep_between_passes():
    logging.info(f"sleeping for {CONFIG['next_pass_delay']} seconds...")
    time.sleep(CONFIG['next_pass_delay'])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--count', help='number of passes to run', default='10', type=int)
    parser.add_argument('--next-pass-delay', help='time to wait between passes', default=0, type=int)
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('config', help='configuration file')
    args = parser.parse_args()

    STATUS['start_time'] = time.time()
    load_config(args)
    setup(args)

    logging.info(f'Starting test at {time.time()}')
    for count in range(int(args.count)):
        run_test()
        logging.info(f'end of pass {count+1}')
        if count < args.count - 1:
            sleep_between_passes()
    logging.info(f"Finishing test after {time.time() - STATUS['start_time']} seconds," +
                 f' with {RIG.retries} retries from {args.count} passes')


if __name__ == "__main__":
    main()
