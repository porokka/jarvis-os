# ============================================================
# JARVIS OS — Systemd Service Files
# Install: sudo cp *.service /etc/systemd/system/
#          sudo systemctl daemon-reload
#          sudo systemctl enable jarvis-api jarvis-watcher ollama
# ============================================================

# ── jarvis-api.service ────────────────────────────────────────
cat > /etc/systemd/system/jarvis-api.service << 'EOF'
[Unit]
Description=JARVIS OS System API
After=network.target ollama.service

[Service]
Type=simple
User=%i
WorkingDirectory=/home/%i/jarvis-os
Environment="JARVIS_DIR=/home/%i/jarvis-os"
Environment="CODE_DIR=/home/%i/code"
Environment="JARVIS_API_TOKEN=jarvis-local-token"
ExecStart=/usr/bin/python3 -m uvicorn scripts.system_api:app --host 0.0.0.0 --port 7800 --ssl-keyfile /home/%i/jarvis-os/certs/jarvis.key --ssl-certfile /home/%i/jarvis-os/certs/jarvis.crt
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── jarvis-watcher.service ────────────────────────────────────
cat > /etc/systemd/system/jarvis-watcher.service << 'EOF'
[Unit]
Description=JARVIS File Bridge Watcher
After=network.target ollama.service jarvis-api.service

[Service]
Type=simple
User=%i
WorkingDirectory=/home/%i/jarvis-os
ExecStart=/bin/bash /home/%i/jarvis-os/scripts/watcher.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# ── jarvis-bridge.service ─────────────────────────────────────
cat > /etc/systemd/system/jarvis-bridge.service << 'EOF'
[Unit]
Description=JARVIS Voice Bridge Server
After=network.target

[Service]
Type=simple
User=%i
WorkingDirectory=/home/%i/jarvis-os
ExecStart=/usr/bin/python3 /home/%i/jarvis-os/scripts/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# ── jarvis-nextjs.service ─────────────────────────────────────
cat > /etc/systemd/system/jarvis-nextjs.service << 'EOF'
[Unit]
Description=JARVIS Next.js Web UI
After=network.target jarvis-api.service

[Service]
Type=simple
User=%i
WorkingDirectory=/home/%i/jarvis-os/ui
ExecStart=/usr/bin/npm run start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Service files written. Now run:"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable ollama jarvis-api jarvis-watcher jarvis-bridge jarvis-nextjs"
echo "  sudo systemctl start ollama jarvis-api jarvis-watcher jarvis-bridge jarvis-nextjs"
