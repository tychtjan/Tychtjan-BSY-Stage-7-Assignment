#!/usr/bin/env python3
"""MQTT Monitor - Covert Protocol Decoder"""

import argparse
import sys
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from datetime import datetime
from covert_protocol import (
    parse_time_signal, parse_params_message, parse_response_message,
    cleanup_fragments, CMD_ENCODE
)

BROKER = "147.32.82.209"
PORT = 1883
TOPIC = "sensors"


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    WHITE = '\033[97m'


def make_on_connect(broker, port, topic):
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc.is_failure if hasattr(rc, 'is_failure') else rc != 0:
            print(f"{Colors.RED}Connection failed: {rc}{Colors.RESET}")
            sys.exit(1)
        print(f"{Colors.GREEN}Connected to {broker}:{port}{Colors.RESET}")
        print(f"{Colors.GREEN}Subscribed to: {topic}{Colors.RESET}")
        mode = "RAW" if userdata.get("raw") else "DECODED"
        print(f"{Colors.BOLD}Monitoring ({mode})... (Ctrl+C to stop){Colors.RESET}")
        print("=" * 70)
        client.subscribe(topic)
    return on_connect


def on_message(client, userdata, msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    raw_mode = userdata.get("raw", False)

    if not msg.payload or len(msg.payload.strip()) == 0:
        return

    try:
        payload = msg.payload.decode('utf-8')
        if not payload.strip():
            return

        if raw_mode:
            print(f"[{timestamp}] {payload}")
            return

        c = Colors
        cleanup_fragments()

        cmd = parse_time_signal(payload)
        if cmd:
            display = payload.replace(' ', '·')
            print(f"\n{c.MAGENTA}[{timestamp}] TIME SIGNAL{c.RESET}")
            print(f"  {c.DIM}Raw:{c.RESET} {display}")
            print(f"  {c.YELLOW}Command:{c.RESET} {cmd.upper()}")
            return

        for cmd_name in CMD_ENCODE:
            parsed = parse_params_message(payload, cmd_name)
            if parsed:
                print(f"\n{c.BLUE}[{timestamp}] ENCRYPTED PARAMS{c.RESET}")
                print(f"  {c.DIM}Raw:{c.RESET} {payload[:50]}...")
                print(f"  {c.YELLOW}Command:{c.RESET} {cmd_name.upper()}")
                print(f"  {c.WHITE}Target:{c.RESET} {parsed['target']}")
                if parsed['params']:
                    print(f"  {c.WHITE}Params:{c.RESET} {parsed['params']}")
                return

        for cmd_name in CMD_ENCODE:
            parsed = parse_response_message(payload, cmd_name)
            if parsed:
                if parsed.get('complete'):
                    status = f"{c.GREEN}OK{c.RESET}" if parsed['success'] else f"{c.RED}FAIL{c.RESET}"
                    print(f"\n{c.GREEN}[{timestamp}] RESPONSE{c.RESET} {cmd_name.upper()} from {c.WHITE}{parsed['bot_id']}{c.RESET} [{status}]")
                    result = parsed.get('result', {})
                    if isinstance(result, dict):
                        for k, v in result.items():
                            if k == "data":
                                print(f"  {c.WHITE}{k}:{c.RESET} <{len(str(v))} chars>")
                            elif k in ("o", "output"):
                                for line in str(v).strip().split('\n'):
                                    print(f"  {line}")
                            else:
                                print(f"  {c.WHITE}{k}:{c.RESET} {v}")
                    elif result:
                        print(f"  {c.WHITE}Result:{c.RESET} {result}")
                else:
                    print(f"{c.DIM}[{timestamp}] Fragment {parsed.get('have')}/{parsed.get('need')} ({cmd_name.upper()} {parsed['bot_id']}){c.RESET}")
                return

        if len(payload) > 20:
            print(f"\n{c.DIM}[{timestamp}] OTHER: {payload[:60]}...{c.RESET}")
        else:
            print(f"\n{c.DIM}[{timestamp}] OTHER: {payload}{c.RESET}")

    except Exception as e:
        print(f"{Colors.RED}[{timestamp}] Error: {e}{Colors.RESET}")


def main():
    parser = argparse.ArgumentParser(description="MQTT Monitor - Covert Protocol")
    parser.add_argument("--broker", "-b", type=str, default=BROKER)
    parser.add_argument("--port", "-p", type=int, default=PORT)
    parser.add_argument("--topic", "-t", type=str, default=TOPIC)
    parser.add_argument("--raw", "-r", action="store_true", help="Show raw payloads only")
    args = parser.parse_args()

    c = Colors
    print(f"{c.CYAN}MQTT Monitor - Covert Protocol Decoder{c.RESET}")
    print(f"Broker: {args.broker}:{args.port}")
    print(f"Topic:  {args.topic}")
    if args.raw:
        print(f"Mode:   RAW")
    print()

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"monitor_{int(time.time())}",
        userdata={"raw": args.raw}
    )
    client.on_connect = make_on_connect(args.broker, args.port, args.topic)
    client.on_message = on_message

    try:
        client.connect(args.broker, args.port)
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n{c.YELLOW}Stopped.{c.RESET}")
        client.disconnect()
    except Exception as e:
        print(f"{c.RED}Error: {e}{c.RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
