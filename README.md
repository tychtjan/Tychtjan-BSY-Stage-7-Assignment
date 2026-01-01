# MQTT C&C System - Covert Protocol

A Python-based Command and Control (C&C) system using MQTT with covert channel communication.

## Overview

- **Bot** (`mqtt_bot.py`): Runs on the target machine, receives and executes commands
- **Controller** (`mqtt_controller.py`): Interactive command interface to control bots
- **Monitor** (`mqtt_monitor.py`): Real-time traffic decoder for debugging
- **Protocol** (`covert_protocol.py`): Covert signaling via space-encoding in time messages

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Run the bot (on target machine)
python mqtt_bot.py

# Run the controller (on attacker machine)
python mqtt_controller.py

# Run the monitor (see decoded traffic)
python mqtt_monitor.py
```

### Command-Line Options

| Flag | Description |
|------|-------------|
| `--broker`, `-b` | MQTT broker address (default: 147.32.82.209) |
| `--port`, `-p` | MQTT broker port (default: 1883) |
| `--topic`, `-t` | MQTT topic (default: sensors) |
| `-T` | Timing level 1-5 (1=stealth, 3=normal, 5=instant) |
| `--bot-id`, `-i` | Bot ID in A#### format (bot only) |
| `--raw`, `-r` | Show raw payloads without decoding (monitor only) |

## Controller Commands

| Command | Description |
|---------|-------------|
| `discover` | Find all bots on the network |
| `bots` | List known/discovered bots |
| `ping [bot\|*]` | Check if bot(s) are alive |
| `who [bot\|*]` | List logged-in users |
| `user [bot\|*]` | Get user ID info |
| `ls <bot\|*> <path>` | List files in directory |
| `list <bot\|*> <path>` | List files with count |
| `copy <bot> <path>` | Download file from bot |
| `exec <bot\|*> <cmd>` | Execute shell command |
| `help` | Show commands |
| `exit` | Quit controller |

Use `*` to broadcast to all bots.

## Protocol Design

### Covert Command Signaling

Commands are encoded via spaces in innocent-looking time messages:

```
Time:[S1]TIMESTAMP[S2]
```

Where S1 = spaces after colon (0-2), S2 = spaces at end (0-2)

| Command | Encoding | Example |
|---------|----------|---------|
| DISCOVER | (0,0) | `Time:2026-01-01 12:00:00` |
| WHO | (0,1) | `Time:2026-01-01 12:00:00 ` |
| LS | (0,2) | `Time:2026-01-01 12:00:00  ` |
| USER | (1,0) | `Time: 2026-01-01 12:00:00` |
| COPY | (1,1) | `Time: 2026-01-01 12:00:00 ` |
| EXEC | (1,2) | `Time: 2026-01-01 12:00:00  ` |
| LIST | (2,0) | `Time:  2026-01-01 12:00:00` |
| PING | (2,1) | `Time:  2026-01-01 12:00:00 ` |

### Message Flow

1. Controller sends time signal (command encoded in spaces)
2. Controller sends XOR-encrypted params (1-3s later)
3. Bot executes command
4. Bot sends XOR-encrypted response (fragmented if needed)

### Encryption

- XOR cipher with 4-byte random salt + SHA256-derived key
- Different secrets per command type (`SECRET_<CMD>`, `SECRET_<CMD>_RESPONSE`)
- Messages fragmented to ~80 chars to avoid detection

## Docker

```bash
# Build
docker build -t mqtt-c2 .

# Run bot
docker run --rm mqtt-c2 mqtt_bot.py

# Run controller (interactive)
docker run -it --rm mqtt-c2 mqtt_controller.py

# Run monitor
docker run --rm mqtt-c2 mqtt_monitor.py
```

## File Structure

```
├── covert_protocol.py   # Protocol implementation
├── mqtt_bot.py          # Bot client
├── mqtt_controller.py   # Controller interface
├── mqtt_monitor.py      # Traffic decoder
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## License

For educational purposes only. Part of BSY course assignment.
