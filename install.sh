#!/bin/bash

set -e

SERVICE_NAME="icoapi"
MODULE_NAME="icoapi"
INSTALL_DIR="/etc/icoapi"
SERVICE_PATH="/etc/systemd/system"
FORCE_REINSTALL=false

# Check for --force flag
if [[ "$1" == "--force" ]]; then
  FORCE_REINSTALL=true
  echo "Forcing reinstallation: Deleting existing installation..."
fi

echo "Stopping service..."
sudo systemctl stop $SERVICE_NAME.service || true

# Handle force reinstallation
if [ "$FORCE_REINSTALL" = true ]; then
  sudo rm -rf $INSTALL_DIR
fi

echo "Creating installation directory if not exists..."
sudo mkdir -p $INSTALL_DIR
sudo chown $USER:$USER $INSTALL_DIR

echo "Copying application files..."
FILES_AND_DIRS=("$MODULE_NAME" "pyproject.toml" "README.md")

for ITEM in "${FILES_AND_DIRS[@]}"; do
  #cp -r "$ITEM" "$INSTALL_DIR"
  rsync -av --exclude='__pycache__' "$ITEM" "$INSTALL_DIR"
done
cd $INSTALL_DIR

echo "Checking for existing virtual environment..."
if [ "$FORCE_REINSTALL" = true ] || [ ! -d "venv" ]; then
  echo "Setting up virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install .
deactivate

echo "Ensuring systemd service exists..."
sudo bash -c "cat << EOF > $SERVICE_PATH/$SERVICE_NAME.service
[Unit]
Description=ICOapi Service
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/$MODULE_NAME/api.py
RestartSec=5
Restart=always

[Install]
WantedBy=multi-user.target
EOF"

echo "Reloading systemd and restarting service..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME.service
sudo systemctl start $SERVICE_NAME.service

echo "Checking service status..."
sudo systemctl status $SERVICE_NAME.service

