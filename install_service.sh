#!/bin/bash

if [ "$EUID" -ne 0 ]; then
    echo "you are not root. gtfo."
    exit 1
fi

echo "installing meshservices..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="meshservices"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_SCRIPT="$SCRIPT_DIR/meshservices.py"
USER="$(stat -c '%U' "$SCRIPT_DIR" 2>/dev/null || stat -f '%Su' "$SCRIPT_DIR")"
find "$SCRIPT_DIR" -name "*.sh" -type f -exec chmod +x {} \;

if [ ! -f "$PYTHON_SCRIPT" ]; then
    exit 1
fi

PYTHON_CMD=$(which python3)
if [ -z "$PYTHON_CMD" ]; then
    PYTHON_CMD=$(which python)
    if [ -z "$PYTHON_CMD" ]; then
        exit 1
    fi
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl stop "$SERVICE_NAME"
fi

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=meshservices
After=network.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=10
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_CMD $PYTHON_SCRIPT
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$SERVICE_FILE"

systemctl daemon-reload

systemctl enable "$SERVICE_NAME"

if systemctl start "$SERVICE_NAME"; then
    echo "installed and started service"
else
    echo "error starting service!"
    echo "need logs? journalctl -u $SERVICE_NAME -f"
    exit 1
fi

AUTO_UPDATE_SCRIPT="$SCRIPT_DIR/autoUpdate.sh"
if [ -f "$AUTO_UPDATE_SCRIPT" ]; then
    
    CRON_LINE="0 3 * * * $AUTO_UPDATE_SCRIPT >/dev/null 2>&1"
    
    TEMP_CRON=$(mktemp)
    sudo -u "$USER" crontab -l > "$TEMP_CRON" 2>/dev/null || true
    
    if ! grep -q "autoUpdate.sh" "$TEMP_CRON"; then
        echo "$CRON_LINE" >> "$TEMP_CRON"
        sudo -u "$USER" crontab "$TEMP_CRON"
        echo "Added autoUpdate Cronjob"
    else
        echo "autoUpdate Cronjob already active"
    fi
    
    rm -f "$TEMP_CRON"
    chmod +x "$AUTO_UPDATE_SCRIPT"
fi

echo ""
systemctl status "$SERVICE_NAME" --no-pager -l

echo "done."
