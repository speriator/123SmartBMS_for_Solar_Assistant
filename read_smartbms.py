#!/usr/bin/env python3
import os
import sys
import time
import serial

# Helper to decode Status Byte 1 flags
def decode_status_byte_1(b):
    flags = []
    if b & 0x80: flags.append("SoC not calibrated")
    if b & 0x40: flags.append("Exceed T max")
    if b & 0x20: flags.append("Exceed T min")
    if b & 0x10: flags.append("Exceed V max")
    if b & 0x08: flags.append("Exceed V min")
    if b & 0x04: flags.append("Comm error")
    if b & 0x02: flags.append("Allow to discharge")
    if b & 0x01: flags.append("Allow to charge")
    return flags

# Helper to decode Status Byte 2 flags (obtained from Key 16)
def decode_status_byte_2(b):
    flags = []
    if b & 0x20: flags.append("Relay 'Load' closed/active")
    if b & 0x10: flags.append("Relay 'Charge' closed/active")
    if b & 0x08: flags.append("Exceed Tmin discharge")
    if b & 0x04: flags.append("Exceed Tmin charge")
    if b & 0x02: flags.append("Early warning")
    return flags

class KeyValueStore:
    def __init__(self):
        self.raw_keys = {}

    def update(self, key, val):
        self.raw_keys[key] = val

    def get_vlow(self):
        if 2 in self.raw_keys and 3 in self.raw_keys:
            return (self.raw_keys[2] * 256 + self.raw_keys[3]) * 0.005
        return None

    def get_vnom(self):
        if 4 in self.raw_keys and 5 in self.raw_keys:
            return (self.raw_keys[4] * 256 + self.raw_keys[5]) * 0.005
        return None

    def get_vfull(self):
        if 17 in self.raw_keys and 18 in self.raw_keys:
            return (self.raw_keys[17] * 256 + self.raw_keys[18]) * 0.005
        return None

    def get_cycles(self):
        if 8 in self.raw_keys and 9 in self.raw_keys:
            return self.raw_keys[8] * 256 + self.raw_keys[9]
        return None

    def get_charged_energy(self):
        if 10 in self.raw_keys and 11 in self.raw_keys and 12 in self.raw_keys:
            return self.raw_keys[10] * 65536 + self.raw_keys[11] * 256 + self.raw_keys[12]
        return None

    def get_discharged_energy(self):
        if 13 in self.raw_keys and 14 in self.raw_keys and 15 in self.raw_keys:
            return self.raw_keys[13] * 65536 + self.raw_keys[14] * 256 + self.raw_keys[15]
        return None

    def get_soh(self):
        return self.raw_keys.get(0, None)

    def get_charge_efficiency(self):
        return self.raw_keys.get(1, None)

    def get_fw_version(self):
        if 6 in self.raw_keys and 7 in self.raw_keys:
            major = (self.raw_keys[6] >> 4) & 0x0F
            minor = self.raw_keys[6] & 0x0F
            patch = self.raw_keys[7]
            return f"{major}.{minor}.{patch}"
        return None

    def get_status_byte_2(self):
        if 16 in self.raw_keys:
            return decode_status_byte_2(self.raw_keys[16])
        return None


def parse_packet(packet, kv_store):
    # Verify checksum
    calc_sum = sum(packet[:57]) & 0xFF
    exp_sum = packet[57]
    if calc_sum != exp_sum:
        return None

    # 1. Total voltage (24 bit)
    total_voltage = int.from_bytes(packet[0:3], byteorder='big') * 0.005

    # 2. Current 1
    sign_i1 = packet[3]
    val_i1 = int.from_bytes(packet[4:6], byteorder='big') * 0.125
    current_i1 = val_i1 if sign_i1 == 0x2B else -val_i1 if sign_i1 == 0x2D else 0.0

    # 3. Current 2
    sign_i2 = packet[6]
    val_i2 = int.from_bytes(packet[7:9], byteorder='big') * 0.125
    current_i2 = val_i2 if sign_i2 == 0x2B else -val_i2 if sign_i2 == 0x2D else 0.0

    # 4. Total Current (I1 - I2)
    sign_isum = packet[9]
    val_isum = int.from_bytes(packet[10:12], byteorder='big') * 0.125
    current_total = val_isum if sign_isum == 0x2B else -val_isum if sign_isum == 0x2D else 0.0

    # 5. Lowest Cell Voltage
    v_lowest = int.from_bytes(packet[12:14], byteorder='big') * 0.005
    cell_v_lowest = packet[14]

    # 6. Highest Cell Voltage
    v_highest = int.from_bytes(packet[15:17], byteorder='big') * 0.005
    cell_v_highest = packet[17]

    # 7. Lowest Temperature (Offset is 276)
    t_lowest = int.from_bytes(packet[18:20], byteorder='big') - 276
    cell_t_lowest = packet[20]

    # 8. Highest Temperature (Offset is 276)
    t_highest = int.from_bytes(packet[21:23], byteorder='big') - 276
    cell_t_highest = packet[23]

    # 9. Specific Cell Voltage & Temp
    specific_cell_nr = packet[24]
    nr_of_cells = packet[25]
    v_specific = int.from_bytes(packet[26:28], byteorder='big') * 0.005
    t_specific = int.from_bytes(packet[28:30], byteorder='big') - 276

    # 10. Status Byte 1
    status_flags_1 = decode_status_byte_1(packet[30])

    # 11. Energies (24 bit)
    today_energy_collected = int.from_bytes(packet[31:34], byteorder='big')
    energy_stored = int.from_bytes(packet[34:37], byteorder='big')
    today_energy_consumed = int.from_bytes(packet[37:40], byteorder='big')

    # 12. SoC %
    soc_pct = packet[40]

    # 13. Totals (24 bit)
    total_collected_kwh = int.from_bytes(packet[41:44], byteorder='big')
    total_consumed_kwh = int.from_bytes(packet[44:47], byteorder='big')

    # 14. Key / Value
    kv_key = packet[47]
    kv_value = packet[48]
    kv_store.update(kv_key, kv_value)

    # 15. Settings
    battery_capacity_kwh = int.from_bytes(packet[49:51], byteorder='big') * 0.1
    v_min_setting = int.from_bytes(packet[51:53], byteorder='big') * 0.005
    v_max_setting = int.from_bytes(packet[53:55], byteorder='big') * 0.005
    v_balance_setting = int.from_bytes(packet[55:57], byteorder='big') * 0.005

    return {
        "total_voltage": total_voltage,
        "current_i1": current_i1,
        "current_i2": current_i2,
        "current_total": current_total,
        "v_lowest": v_lowest,
        "cell_v_lowest": cell_v_lowest,
        "v_highest": v_highest,
        "cell_v_highest": cell_v_highest,
        "t_lowest": t_lowest,
        "cell_t_lowest": cell_t_lowest,
        "t_highest": t_highest,
        "cell_t_highest": cell_t_highest,
        "specific_cell_nr": specific_cell_nr,
        "nr_of_cells": nr_of_cells,
        "v_specific": v_specific,
        "t_specific": t_specific,
        "status_flags_1": status_flags_1,
        "today_energy_collected_wh": today_energy_collected,
        "energy_stored_wh": energy_stored,
        "today_energy_consumed_wh": today_energy_consumed,
        "soc_pct": soc_pct,
        "total_collected_kwh": total_collected_kwh,
        "total_consumed_kwh": total_consumed_kwh,
        "battery_capacity_kwh": battery_capacity_kwh,
        "v_min_setting": v_min_setting,
        "v_max_setting": v_max_setting,
        "v_balance_setting": v_balance_setting,
        "last_kv_key": kv_key,
        "last_kv_value": kv_value
    }


def print_dashboard(data, kv_store):
    # Clear screen
    os.system('clear')
    
    print("=" * 60)
    print("             123\\SmartBMS Live Data Dashboard           ")
    print("=" * 60)
    
    # 1. State of Charge (SoC) & Voltages
    print(f"State of Charge (SoC):  {data['soc_pct']}%  (Stored: {data['energy_stored_wh']} Wh)")
    print(f"Total Battery Voltage:  {data['total_voltage']:.2f} V")
    print(f"Total System Current:   {data['current_total']:.2f} A")
    print(f"Current Sensors:        I1 = {data['current_i1']:.2f} A | I2 = {data['current_i2']:.2f} A")
    print("-" * 60)
    
    # 2. Cells & Temperature
    print(f"Cells Count:            {data['nr_of_cells']}")
    print(f"Voltage Range:          Lowest:  {data['v_lowest']:.3f} V (Cell #{data['cell_v_lowest']})")
    print(f"                        Highest: {data['v_highest']:.3f} V (Cell #{data['cell_v_highest']})")
    print(f"Temperature Range:      Lowest:  {data['t_lowest']} °C (Cell #{data['cell_t_lowest']})")
    print(f"                        Highest: {data['t_highest']} °C (Cell #{data['cell_t_highest']})")
    print("-" * 60)
    
    # 3. Specific Cell Info Cycling
    print(f"Specific Cell Monitor:  Cell #{data['specific_cell_nr']} -> Voltage: {data['v_specific']:.3f} V | Temp: {data['t_specific']} °C")
    print("-" * 60)
    
    # 4. Settings
    print("BMS Settings:")
    print(f"  Capacity: {data['battery_capacity_kwh']:.1f} kWh | Balance V: {data['v_balance_setting']:.2f} V")
    print(f"  V-MIN Setting: {data['v_min_setting']:.2f} V | V-MAX Setting: {data['v_max_setting']:.2f} V")
    print("-" * 60)
    
    # 5. Energy statistics
    print("Energy Statistics:")
    print(f"  Today Collected: {data['today_energy_collected_wh']} Wh | Today Consumed: {data['today_energy_consumed_wh']} Wh")
    print(f"  Total Collected: {data['total_collected_kwh']} kWh | Total Consumed: {data['total_consumed_kwh']} kWh")
    print("-" * 60)
    
    # 6. Status and Flags
    print("Status Flags (Active):")
    if data['status_flags_1']:
        print(f"  Status 1: {', '.join(data['status_flags_1'])}")
    else:
        print("  Status 1: OK")
        
    s2 = kv_store.get_status_byte_2()
    if s2:
        print(f"  Status 2: {', '.join(s2)}")
    else:
        print("  Status 2: -")
    print("-" * 60)
    
    # 7. Accumulated Key/Values
    print("Accumulated Parameters (Cycled over UART):")
    print(f"  State of Health (SoH): {kv_store.get_soh() or '-'} %")
    print(f"  Charge Efficiency:     {kv_store.get_charge_efficiency() or '-'} %")
    print(f"  Firmware Version:      {kv_store.get_fw_version() or '-'}")
    print(f"  Battery Cycles:        {kv_store.get_cycles() or '-'}")
    print(f"  Charged Energy (acc):  {kv_store.get_charged_energy() or '-'} kWh")
    print(f"  Discharged Energy (acc):{kv_store.get_discharged_energy() or '-'} kWh")
    print(f"  Vlow setting / Vnom:   {kv_store.get_vlow() or '-'} V / {kv_store.get_vnom() or '-'} V")
    print(f"  Vfull setting:         {kv_store.get_vfull() or '-'} V")
    print("=" * 60)


def main():
    port = "/dev/serial0"
    baud = 9600
    
    print(f"Opening port {port} at {baud} bps...")
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5
        )
    except Exception as e:
        print(f"Error opening serial port {port}: {e}")
        sys.exit(1)
        
    kv_store = KeyValueStore()
    buffer = bytearray()
    
    print("Listening for 123SmartBMS frames. Please wait...")
    
    try:
        while True:
            # Read whatever bytes are currently waiting, or block for 1 byte
            data = ser.read(ser.in_waiting or 1)
            if data:
                buffer.extend(data)
                
            # Search for valid 58-byte packet using sliding window
            while len(buffer) >= 58:
                # Calculate expected checksum
                calc_sum = sum(buffer[:57]) & 0xFF
                exp_sum = buffer[57]
                
                if calc_sum == exp_sum:
                    # Valid packet found!
                    packet = bytes(buffer[:58])
                    # Remove it from buffer
                    del buffer[:58]
                    
                    # Parse and print
                    parsed = parse_packet(packet, kv_store)
                    if parsed:
                        print_dashboard(parsed, kv_store)
                else:
                    # Discard first byte and slide window
                    buffer.pop(0)
                    
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
