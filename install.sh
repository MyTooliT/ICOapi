#!/bin/bash

set -e

SERVICE_NAME="icoapi"
INSTALL_DIR="/etc/icoapi"
SERVICE_PATH="/etc/systemd/system"

echo "Stopping and removing old files..."
sudo systemctl start $SERVICE_NAME.service
sudo rm -rf $INSTALL_DIR

echo "Creating installation directory..."
sudo rm -rf $INSTALL_DIR
sudo mkdir -p $INSTALL_DIR
sudo chown $USER:$USER $INSTALL_DIR

echo "Copying application files..."
FILES_AND_DIRS=(".env" "api.py" "models" "requirements.txt" "routers" "scripts")

for ITEM in "${FILES_AND_DIRS[@]}"; do
  cp -r "$ITEM" "$INSTALL_DIR"
done
cd $INSTALL_DIR

echo "Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "Creating systemd service..."
sudo bash -c "cat << EOF > $SERVICE_PATH/$SERVICE_NAME.service
[Unit]
Description=ICOapi Service
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/api.py
RestartSec=5
Restart=always

[Install]
WantedBy=multi-user.target
EOF"

echo "Reloading systemd and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME.service
sudo systemctl start $SERVICE_NAME.service

echo "Checking service status..."
sudo systemctl status $SERVICE_NAME.service

