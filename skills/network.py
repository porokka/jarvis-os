"""
JARVIS Skill — Network scanning and topology mapping.

Discovers devices on the LAN, identifies types by MAC OUI + open ports,
builds a topology map for the HUD SVG renderer.
"""

import json
import re
import subprocess
import time
from pathlib import Path

SKILL_NAME = "network"
SKILL_DESCRIPTION = "Network scan, device discovery, topology map"

CONFIG_DIR = Path(__file__).parent.parent / "config"
TOPOLOGY_FILE = CONFIG_DIR / "network_topology.json"

# MAC OUI → vendor/type mapping (common home network devices)
OUI_MAP = {
    "00:1a:79": ("router", "Ubiquiti"),
    "24:5a:4c": ("router", "Ubiquiti"),
    "78:8a:20": ("router", "Ubiquiti"),
    "74:ac:b9": ("router", "Ubiquiti"),
    "fc:ec:da": ("router", "Ubiquiti"),
    "18:e8:29": ("router", "Ubiquiti"),
    "f0:9f:c2": ("router", "Ubiquiti"),
    "b4:fb:e4": ("switch", "Ubiquiti"),
    "48:b0:2d": ("ap", "NVIDIA"),
    "00:04:4b": ("media", "NVIDIA"),
    "48:d7:05": ("media", "NVIDIA Shield"),
    "a8:5e:45": ("desktop", "ASRock/PC"),
    "04:d4:c4": ("desktop", "ASRock"),
    "00:d8:61": ("desktop", "Micro-Star/MSI"),
    "3c:7c:3f": ("desktop", "ASUSTek"),
    "d8:bb:c1": ("desktop", "Dell"),
    "f0:2f:74": ("desktop", "HP"),
    "00:11:32": ("nas", "Synology"),
    "00:1b:63": ("printer", "HP"),
    "00:15:99": ("printer", "Samsung"),
    "bc:09:1b": ("phone", "Apple"),
    "f8:ff:c2": ("phone", "Apple"),
    "a4:83:e7": ("phone", "Apple"),
    "dc:a6:32": ("iot", "Raspberry Pi"),
    "b8:27:eb": ("iot", "Raspberry Pi"),
    "e8:48:b8": ("iot", "Samsung SmartTV"),
    "cc:2d:21": ("tv", "LG TV"),
    "a8:23:fe": ("tv", "Samsung TV"),
    "88:71:b1": ("speaker", "Sonos"),
    "54:2a:1b": ("speaker", "Sonos"),
    "30:fd:38": ("iot", "Google/Nest"),
    "f4:f5:d8": ("iot", "Google/Nest"),
    "68:ec:c5": ("receiver", "Denon"),
    "00:06:78": ("receiver", "Denon/Marantz"),
}

# Port → device type inference
PORT_TYPE_MAP = {
    80: "web",
    443: "web",
    5555: "shield",
    8008: "cast",
    8443: "cast",
    9100: "printer",
    515: "printer",
    631: "printer",
    5000: "nas",
    5001: "nas",
    8080: "web",
    3689: "media",
    1400: "speaker",
    8200: "media",
    32400: "media",
    554: "camera",
    22: "server",
    3000: "server",
    11434: "ai",
}

DEVICE_ICONS = {
    "router": "R",
    "switch": "SW",
    "ap": "AP",
    "desktop": "PC",
    "laptop": "LP",
    "phone": "PH",
    "media": "TV",
    "shield": "SH",
    "tv": "TV",
    "nas": "NAS",
    "printer": "PR",
    "speaker": "SPK",
    "iot": "IoT",
    "camera": "CAM",
    "server": "SRV",
    "ai": "AI",
    "receiver": "AV",
    "cast": "CS",
    "web": "WEB",
    "unknown": "?",
}


def _resolve_hostname(ip: str) -> str:
    """Try DNS reverse lookup for hostname."""
    try:
        import socket
        name, _, _ = socket.gethostbyaddr(ip)
        if "." in name:
            name = name.split(".")[0]
        return name
    except Exception:
        return ""


def _identify_device(ip: str, mac: str, hostname: str, ports: list) -> dict:
    """Identify device type from MAC OUI, ports, and hostname."""
    mac_prefix = mac[:8].lower() if mac else ""
    device_type = "unknown"
    vendor = ""

    if mac_prefix in OUI_MAP:
        device_type, vendor = OUI_MAP[mac_prefix]

    hn = hostname.lower() if hostname else ""

    if any(x in hn for x in ["usw-", "us-8", "us-16", "us-24", "us-48", "usw "]):
        device_type, vendor = "switch", "Ubiquiti"
    elif any(x in hn for x in ["uap-", "u6-", "unifi-ap", "uap ", "nanohd", "flexhd", "lite-8-poe"]):
        device_type, vendor = "ap", "Ubiquiti"
    elif any(x in hn for x in ["usw-lite", "usw-flex"]):
        device_type, vendor = "switch", "Ubiquiti"
    elif "unifi" in hn and device_type == "unknown":
        device_type, vendor = "router", "Ubiquiti"
    elif "shield" in hn:
        device_type = "shield"
    elif any(x in hn for x in ["lgwebos", "lgtv", "lg-tv"]):
        device_type, vendor = "tv", "LG"
    elif any(x in hn for x in ["samsung-tv", "tizen"]):
        device_type, vendor = "tv", "Samsung"
    elif any(x in hn for x in ["chromecast", "google-home", "nest"]):
        device_type, vendor = "cast", "Google"
    elif "sonos" in hn or "speaker" in hn:
        device_type = "speaker"
    elif "denon" in hn or "marantz" in hn:
        device_type, vendor = "receiver", "Denon"
    elif any(x in hn for x in ["macbook", "macpro", "imac"]):
        device_type, vendor = ("laptop" if "book" in hn else "desktop"), "Apple"
    elif any(x in hn for x in ["iphone", "ipad"]):
        device_type, vendor = "phone", "Apple"
    elif any(x in hn for x in ["android", "galaxy", "s20", "s21", "s22", "s23", "s24", "pixel"]):
        device_type = "phone"
    elif any(x in hn for x in ["desktop", "pc", "workstation"]):
        device_type = "desktop"
    elif any(x in hn for x in ["laptop"]):
        device_type = "laptop"
    elif any(x in hn for x in ["amazon-", "echo", "alexa", "fire"]):
        device_type, vendor = "iot", "Amazon"
    elif any(x in hn for x in ["dreame", "vacuum", "roborock", "roomba"]):
        device_type = "iot"
    elif any(x in hn for x in ["hue", "tradfri", "ikea"]):
        device_type = "iot"
    elif any(x in hn for x in ["printer", "epson", "hp-", "canon", "lulzbot", "lutzl"]):
        device_type = "printer"
    elif any(x in hn for x in ["synology", "diskstation", "nas"]):
        device_type, vendor = "nas", "Synology"

    if device_type == "unknown":
        for port in ports:
            if port in PORT_TYPE_MAP:
                device_type = PORT_TYPE_MAP[port]
                break

    if ip.endswith(".1") and device_type == "unknown":
        device_type = "router"

    if not hostname or hostname == ip:
        hostname = _resolve_hostname(ip) or ip

    return {
        "ip": ip,
        "mac": mac,
        "hostname": hostname,
        "type": device_type,
        "vendor": vendor,
        "icon": DEVICE_ICONS.get(device_type, "?"),
        "ports": ports,
    }


def exec_scan_network() -> str:
    """Full network scan — discover devices, identify types, save topology."""
    try:
        nmap_cmd = ["nmap", "-sn", "-oX", "-", "192.168.0.0/24"]
        result = subprocess.run(
            ["sudo", "-n"] + nmap_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            result = subprocess.run(
                nmap_cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

        devices = []
        current_ip = ""
        current_mac = ""
        current_hostname = ""
        current_vendor = ""

        for line in result.stdout.split("\n"):
            line = line.strip()

            m = re.search(r'addr="(\d+\.\d+\.\d+\.\d+)"', line)
            if m and 'addrtype="ipv4"' in line:
                if current_ip:
                    dev = _identify_device(current_ip, current_mac, current_hostname, [])
                    if current_vendor and not dev["vendor"]:
                        dev["vendor"] = current_vendor
                    devices.append(dev)
                current_ip = m.group(1)
                current_mac = ""
                current_hostname = ""
                current_vendor = ""

            m = re.search(r'addr="([0-9A-F:]{17})"', line)
            if m and 'addrtype="mac"' in line:
                current_mac = m.group(1)

            m = re.search(r'vendor="([^"]*)"', line)
            if m:
                current_vendor = m.group(1)

            m = re.search(r'name="([^"]*)"', line)
            if m and "hostname" in line:
                current_hostname = m.group(1)

        arp_macs = {}
        try:
            arp_result = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10)
            for line in arp_result.stdout.split("\n"):
                m = re.search(
                    r'(\d+\.\d+\.\d+\.\d+)\s+.*?([\da-fA-F]{2}[:-][\da-fA-F]{2}[:-][\da-fA-F]{2}[:-][\da-fA-F]{2}[:-][\da-fA-F]{2}[:-][\da-fA-F]{2})',
                    line,
                )
                if m:
                    arp_macs[m.group(1)] = m.group(2).upper().replace("-", ":")
        except Exception:
            pass

        if current_ip:
            dev = _identify_device(current_ip, current_mac, current_hostname, [])
            if current_vendor and not dev["vendor"]:
                dev["vendor"] = current_vendor
            devices.append(dev)

        for d in devices:
            if not d["mac"] and d["ip"] in arp_macs:
                d["mac"] = arp_macs[d["ip"]]
                mac_prefix = d["mac"][:8].lower()
                if mac_prefix in OUI_MAP and d["type"] == "unknown":
                    d["type"], d["vendor"] = OUI_MAP[mac_prefix]
                    d["icon"] = DEVICE_ICONS.get(d["type"], "?")

        ips = [d["ip"] for d in devices if not d["ip"].endswith(".1")][:20]
        if ips:
            port_result = subprocess.run(
                [
                    "nmap",
                    "-p",
                    "22,80,443,554,631,1400,3000,3689,5000,5001,5555,8008,8080,8200,8443,9100,11434,32400",
                    "--open",
                    "-oG",
                    "-",
                ] + ips,
                capture_output=True,
                text=True,
                timeout=60,
            )
            for line in port_result.stdout.split("\n"):
                if "/open" in line:
                    parts = line.split()
                    ip = parts[1] if len(parts) > 1 else ""
                    ports = [int(p.split("/")[0]) for p in line.split() if "/open" in p]
                    for d in devices:
                        if d["ip"] == ip:
                            d["ports"] = ports
                            if d["type"] == "unknown" and ports:
                                updated = _identify_device(ip, d["mac"], d["hostname"], ports)
                                d["type"] = updated["type"]
                                d["icon"] = updated["icon"]

        devices.sort(key=lambda d: (0 if d["type"] == "router" else 1, d["ip"]))

        topology = {
            "devices": devices,
            "gateway": next((d["ip"] for d in devices if d["type"] == "router"), "192.168.0.1"),
            "subnet": "192.168.0.0/24",
            "scan_time": time.time(),
        }
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOPOLOGY_FILE.write_text(json.dumps(topology, indent=2), encoding="utf-8")

        lines = [f"Found {len(devices)} devices on 192.168.0.0/24:\n"]
        for d in devices:
            name = d["hostname"] if d["hostname"] != d["ip"] else ""
            vendor_str = f" ({d['vendor']})" if d["vendor"] else ""
            port_str = f" ports:{','.join(str(p) for p in d['ports'])}" if d["ports"] else ""
            lines.append(f"  {d['icon']:>3} {d['ip']:<16} {d['mac']:<18} {name}{vendor_str}{port_str}")

        lines.append("\nTopology saved to config/network_topology.json")
        return "\n".join(lines)

    except subprocess.TimeoutExpired:
        return "Network scan timed out (120s)"
    except Exception as e:
        return f"Scan error: {e}"


def get_topology() -> dict:
    """Return saved topology for the HUD."""
    try:
        return json.loads(TOPOLOGY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"devices": [], "gateway": "192.168.0.1", "subnet": "192.168.0.0/24"}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scan_network",
            "description": "Scan the local network for all devices. Identifies device types such as PC, Shield, TV, phone, printer, and IoT by MAC vendor and open ports. Saves topology map.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

TOOL_MAP = {
    "scan_network": exec_scan_network,
}

KEYWORDS = {
    "scan_network": [
        "scan",
        "network",
        "devices",
        "find shield",
        "what devices",
        "discover",
        "topology",
        "network map",
        "lan",
    ],
}

SKILL_META = {
    "intent_aliases": [
        "network",
        "network scan",
        "scan network",
        "device discovery",
        "topology",
        "network map",
        "lan scan",
    ],
    "keywords": [
        "network",
        "scan network",
        "what devices are on the network",
        "device discovery",
        "discover devices",
        "network topology",
        "network map",
        "lan",
        "scan lan",
        "find devices",
        "find shield",
    ],
    "route": "reason",
    "tools": {
        "scan_network": {
            "intent_aliases": [
                "scan network",
                "network scan",
                "device discovery",
                "network topology",
                "network map",
            ],
            "keywords": [
                "scan",
                "network",
                "devices",
                "discover",
                "topology",
                "network map",
                "lan",
                "what devices",
                "find shield",
                "scan lan",
            ],
            "direct_match": [
                "scan network",
                "network scan",
                "scan lan",
                "network map",
                "network topology",
                "what devices are on the network",
            ],
            "route": "reason",
        }
    },
}