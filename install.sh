#!/bin/bash
# install.sh - Installer script for the 123SmartBMS Emulation & Dashboard on Solar-Assistant Pi

set -e

# Make sure the script is run with root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script as root (sudo ./install.sh)"
  exit 1
fi

echo "============================================="
echo " Installing 123SmartBMS Emulation & Web UI"
echo "============================================="

# 1. Install dependencies
echo "Installing dependencies (python3-serial, socat)..."
apt-get update
apt-get install -y python3-serial socat

# 2. Configure Boot parameters (disable bluetooth / enable UART console overlay)
if [ -d "/boot/firmware" ]; then
    BOOT_DIR="/boot/firmware"
else
    BOOT_DIR="/boot"
fi

CONFIG_FILE="$BOOT_DIR/config.txt"
CMDLINE_FILE="$BOOT_DIR/cmdline.txt"

echo "Using boot directory: $BOOT_DIR"

# 2a. Modify config.txt to enable UART and disable Bluetooth
echo "Configuring UART and overlays in $CONFIG_FILE..."
if ! grep -q "enable_uart=1" "$CONFIG_FILE"; then
    echo "enable_uart=1" >> "$CONFIG_FILE"
fi

if ! grep -q "dtoverlay=disable-bt" "$CONFIG_FILE"; then
    echo "dtoverlay=disable-bt" >> "$CONFIG_FILE"
fi

# 2b. Modify cmdline.txt to disable serial console
echo "Disabling serial console in $CMDLINE_FILE..."
if grep -q "console=serial0,115200" "$CMDLINE_FILE"; then
    sed -i 's/console=serial0,115200 //g' "$CMDLINE_FILE"
    sed -i 's/ console=serial0,115200//g' "$CMDLINE_FILE"
fi

# 2c. Disable hciuart service
echo "Disabling hciuart bluetooth service..."
systemctl disable hciuart 2>/dev/null || true

# 3. Create install directory and copy files
INSTALL_DIR="/home/solar-assistant"
echo "Creating installation folder at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

echo "Copying application files..."
cp server_smartbms.py "$INSTALL_DIR/"
cp index.html "$INSTALL_DIR/"
cp setup_virtual_port.sh "$INSTALL_DIR/"

# Ensure the helper script is executable
chmod +x "$INSTALL_DIR/setup_virtual_port.sh"

# Set permissions
chown -R solar-assistant:solar-assistant "$INSTALL_DIR"

# 4. Copy and enable systemd services
echo "Installing systemd services..."
cp smartbms-web.service /etc/systemd/system/
cp virtual-bms-port.service /etc/systemd/system/

# Fix service files ownership
chown root:root /etc/systemd/system/smartbms-web.service
chown root:root /etc/systemd/system/virtual-bms-port.service

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# 5. Enable and start services
echo "Enabling and starting smartbms-web service..."
systemctl enable smartbms-web.service
systemctl restart smartbms-web.service

echo "Enabling and starting virtual-bms-port service..."
systemctl enable virtual-bms-port.service
systemctl restart virtual-bms-port.service

# 6. Restart Solar-Assistant to hook onto the new port
echo "Restarting Solar-Assistant service..."
systemctl restart influx-bridge.service

echo "============================================="
echo " Installation completed successfully!"
echo " Please reboot the Raspberry Pi to apply the"
echo " serial port boot configurations (sudo reboot)."
echo "============================================="
