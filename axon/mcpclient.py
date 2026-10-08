"""Minimal MCP client over stdio, the way an agent CLI talks to Axon's MCP server."""

import json
import subprocess


class Mcp:
    """Minimal MCP client over stdio, like a real agent CLI uses."""

    def __init__(self, argv):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.id = 0
        self.req("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "axon-agent", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def req(self, method, params):
        self.id += 1
        self.send({"jsonrpc": "2.0", "id": self.id, "method": method, "params": params})
        return json.loads(self.p.stdout.readline())

    def call(self, tool, args):
        return self.req("tools/call", {"name": tool, "arguments": args})["result"]
