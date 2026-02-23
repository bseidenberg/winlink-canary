# Winlink/VARA node monitor

This program is designed to act as a canary (health monitor) for the SeattleACS Winlink/VARA nodes. 
It is designed to use Pat to periodically send messages through them, then verify the messages were readable through a telnet (internet) connection to Winlink CMS. 

The program will respond to web queries.

- /status.html - Status of nodes as HTML tables
- /status.json (or just /status) - Status of ndes as json
- /config - Configuration information

and otherwise responds with a help message.

## Status
This project is currently a work in progress, but has completed its first version and is in production.
