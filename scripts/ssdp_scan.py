"""Quick SSDP scanner — find UPnP devices on LAN."""
import socket
import sys

SSDP_MSG = (
    'M-SEARCH * HTTP/1.1\r\n'
    'HOST: 239.255.255.250:1900\r\n'
    'MAN: "ssdp:discover"\r\n'
    'MX: 3\r\n'
    'ST: ssdp:all\r\n'
    '\r\n'
)

target = sys.argv[1] if len(sys.argv) > 1 else None

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(4)
s.sendto(SSDP_MSG.encode(), ("239.255.255.250", 1900))

seen = set()
try:
    while True:
        data, addr = s.recvfrom(4096)
        ip = addr[0]
        if target and ip != target:
            continue
        if ip not in seen:
            seen.add(ip)
            text = data.decode("utf-8", errors="replace")
            srv = ""
            for line in text.split("\r\n"):
                if line.lower().startswith("server:"):
                    srv = line
                    break
            print(f"{ip:16s} {srv}")
            if target:
                print(text)
                print("---")
except socket.timeout:
    if not seen:
        print(f"No SSDP responses{' from ' + target if target else ''}")
s.close()
