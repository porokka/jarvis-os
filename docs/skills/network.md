# Network Skill

Scans the LAN for devices, identifies types by MAC OUI + open ports + hostname patterns, builds a topology map for the HUD.

**File:** `skills/network.py`

---

## Prerequisites

- `nmap` installed
- For MAC addresses: `sudo` access or ARP table

---

## Tools

### scan_network

No parameters. Scans `192.168.0.0/24`:
1. Ping sweep to find live hosts
2. DNS reverse lookup for hostnames
3. ARP table for MAC addresses
4. Port scan on discovered devices
5. Device identification by MAC OUI, hostname patterns, and open ports
6. Saves topology to `config/network_topology.json`

**Examples:**
```
"Scan the network"
"What devices are on the network?"
"Show me the network map"
```

---

## Device Identification

Priority order:
1. **MAC OUI** — Ubiquiti, NVIDIA, Apple, Synology, etc.
2. **Hostname patterns** — USW-* (switch), LGwebOS (TV), iPhone (phone), dreame_vacuum (IoT)
3. **Open ports** — 5555 (Shield/ADB), 32400 (Plex), 554 (camera), 22 (server)

---

## HUD Integration

The NETWORK tab in the HUD shows:
- Tree topology — router > switches/APs > end devices
- Color-coded device icons by type
- Click any device for info modal with clickable port links
- Zoom and pan controls
- Auto-opens when scan completes

---

## Topology File

Saved to `config/network_topology.json`:

```json
{
  "devices": [
    {
      "ip": "192.168.0.1",
      "mac": "...",
      "hostname": "unifi.localdomain",
      "type": "router",
      "vendor": "Ubiquiti",
      "icon": "R",
      "ports": [80, 443]
    }
  ],
  "gateway": "192.168.0.1",
  "subnet": "192.168.0.0/24",
  "scan_time": 1712847600.0
}
```
