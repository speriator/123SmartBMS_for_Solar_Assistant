# Solar-Assistant Workspace Rules

## Context
- **Solar-Assistant Raspberry Pi IP:** `192.168.80.186`
- **SSH Connection Command:** `ssh -o StrictHostKeyChecking=no solar-assistant@192.168.80.186`
- **SSH Key Authentication:** Configured and active from the user's macOS. No password is required.
- **Default Credentials Reference:** User `solar-assistant`, password `solar123` (if password prompt fallback is triggered).

## Project Architecture: 123SmartBMS to Solar-Assistant

This workspace integrates a physical **123SmartBMS** (reading raw UART packets) with **Solar-Assistant** by emulating a **Daly BMS** on a virtual port.

### Core File Structure
* **`read_smartbms.py`**: CLI script to read and decode the 123SmartBMS protocol on `/dev/serial0` (UART).
* **`server_smartbms.py`**: Multi-threaded core service.
  1. Reads raw 123SmartBMS UART packets.
  2. Runs a local HTTP server on port `8080` (serving `index.html` and `/api/data` JSON API).
  3. Emulates the Daly BMS protocol on `/dev/ttyBMS_backend`.
  4. Recalculates a custom SoC (State of Charge) using a LUT tailored for Yinlong 400Ah LTO cells (40Ah * 10 in parallel).
* **`index.html`**: A responsive, premium dark dashboard (glassmorphism UI) for live battery monitoring.
* **`setup_virtual_port.sh`**: Creates the virtual serial links and sets up the sysfs overlay.
* **`install.sh`**: Automates dependencies installation (`python3-serial`, `socat`), configures boot parameters/overlays, and installs systemd services.
* **`memoire.md`**: Operations handbook for duplication, migration, and technical details.

### How the Serial Port Emulation Hack Works
Solar-Assistant's serial port scanner (Elixir's `Circuits.UART`) only lists ports present under `/sys/class/tty/` and ignores plain symlinks.
1. `setup_virtual_port.sh` starts `socat` to link `/dev/ttyS9` (presented to Solar-Assistant) with `/dev/ttyBMS_backend` (used by the emulator).
2. It clones the sysfs folder of `ttyAMA0` into `/dev/shm/sys_class_tty/ttyS9`, modifies the major/minor numbers to point to `/dev/ttyS9`, and injects it.
3. It performs a bind-mount: `mount --bind /dev/shm/sys_class_tty /sys/class/tty` so the virtual port appears as a platform serial device.

### Services Management on the Pi
* **Web & Emulator Service**: `sudo systemctl status/restart/stop smartbms-web.service`
* **Virtual Port Service**: `sudo systemctl status/restart/stop virtual-bms-port.service`
* **Solar-Assistant Main Bridge**: `sudo systemctl restart influx-bridge.service`

