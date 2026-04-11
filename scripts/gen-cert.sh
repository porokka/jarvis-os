#!/bin/bash
# Generate self-signed TLS cert for JARVIS OS
# Run once: bash scripts/gen-cert.sh

CERT_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/jarvis.crt" ] && [ -f "$CERT_DIR/jarvis.key" ]; then
  echo "Certs already exist at $CERT_DIR — delete them to regenerate."
  exit 0
fi

# Get local IP for SAN
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$LOCAL_IP" ] && LOCAL_IP="192.168.1.100"

echo "Generating self-signed cert for localhost + $LOCAL_IP ..."

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/jarvis.key" \
  -out "$CERT_DIR/jarvis.crt" \
  -days 3650 \
  -subj "/CN=jarvis-os" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:$LOCAL_IP"

echo ""
echo "Done: $CERT_DIR/jarvis.crt + jarvis.key"
echo "Local IP in SAN: $LOCAL_IP"
echo ""
echo "To trust on clients, install jarvis.crt as a trusted root CA:"
echo "  Windows: double-click .crt → Install → Local Machine → Trusted Root CAs"
echo "  macOS:   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain jarvis.crt"
echo "  Linux:   sudo cp jarvis.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates"
