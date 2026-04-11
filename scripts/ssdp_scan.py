"""Quick SSDP scanner — find UPnP devices on LAN."""
import socket

SSDP_MSG = (
    'M-SEARCH * HTTP/1.1\r\n'
    'HOST: 239.255.255.250:1900\r\n'
    'MAN: "ssdp:discover"\r\n'
    'MX: 3\r\n'
    'ST: ssdp:all\r\n'
    '\r\n'
)

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(4)
s.sendto(SSDP_MSG.encode(), ("239.255.255.250", 1900))

target = "192.168.0.209"
try:
    while True:
        data, addr = s.recvfrom(4096)
        if addr[0] == target:
            print(data.decode("utf-8", errors="replace"))
            print("---")
except socket.timeout:
    print(f"No SSDP from {target}")
s.close()
