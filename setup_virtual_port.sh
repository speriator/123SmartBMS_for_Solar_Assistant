#!/bin/bash
# 1. Kill any existing socat
killall socat 2>/dev/null || true

# 2. Run socat to create the symlinks in background
/usr/bin/socat PTY,link=/dev/ttyS9,raw,echo=0,mode=666 PTY,link=/dev/ttyBMS_backend,raw,echo=0,mode=666 &
SOCAT_PID=$!
sleep 2

# 3. Get major/minor of the newly created ttyS9 (which points to a pts device)
PTS_DEV=$(readlink /dev/ttyS9)
if [ -z "$PTS_DEV" ]; then
    echo "Error: /dev/ttyS9 was not created!"
    exit 1
fi

MAJOR_MINOR=$(stat -c "%t:%T" "$PTS_DEV")
MAJOR_HEX=$(echo "$MAJOR_MINOR" | cut -d: -f1)
MINOR_HEX=$(echo "$MAJOR_MINOR" | cut -d: -f2)
MAJOR_DEC=$((16#$MAJOR_HEX))
MINOR_DEC=$((16#$MINOR_HEX))

echo "Virtual serial port created on $PTS_DEV (Major: $MAJOR_DEC, Minor: $MINOR_DEC)"

# 4. Prepare /dev/shm/sys_class_tty
# First unmount if already mounted so we start clean
if mountpoint -q /sys/class/tty; then
    umount /sys/class/tty
fi

mkdir -p /dev/shm/sys_class_tty
rm -rf /dev/shm/sys_class_tty/*
cp -P /sys/class/tty/* /dev/shm/sys_class_tty/

# 5. Create fake ttyS9 entry in shm
mkdir -p /dev/shm/sys_devices_virtual_tty_ttyS9
echo "${MAJOR_DEC}:${MINOR_DEC}" > /dev/shm/sys_devices_virtual_tty_ttyS9/dev
echo "DRIVER=serial8250" > /dev/shm/sys_devices_virtual_tty_ttyS9/uevent
ln -sf ../../../../sys/devices/platform/serial8250 /dev/shm/sys_devices_virtual_tty_ttyS9/device

# Link it into sys_class_tty
ln -sf ../../../dev/shm/sys_devices_virtual_tty_ttyS9 /dev/shm/sys_class_tty/ttyS9

# 6. Bind-mount
mount --bind /dev/shm/sys_class_tty /sys/class/tty
echo "Bind mount set up on /sys/class/tty"

# 7. Wait for socat to exit
wait $SOCAT_PID
