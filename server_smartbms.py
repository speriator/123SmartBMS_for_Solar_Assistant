#!/usr/bin/env python3
import os
import sys
import json
import time
import threading
import serial
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

# Global state to store the decoded data and cell values
latest_data = {
    "total_voltage": 0.0,
    "current_i1": 0.0,
    "current_i2": 0.0,
    "current_total": 0.0,
    "v_lowest": 0.0,
    "cell_v_lowest": 0,
    "v_highest": 0.0,
    "cell_v_highest": 0,
    "t_lowest": 0,
    "cell_t_lowest": 0,
    "t_highest": 0,
    "cell_t_highest": 0,
    "nr_of_cells": 0,
    "last_updated_cell_id": 0,
    "status_flags_1": [],
    "today_energy_collected_wh": 0,
    "energy_stored_wh": 0,
    "today_energy_consumed_wh": 0,
    "soc_pct": 0,
    "total_collected_kwh": 0,
    "total_consumed_kwh": 0,
    "battery_capacity_kwh": 0.0,
    "v_min_setting": 0.0,
    "v_max_setting": 0.0,
    "v_balance_setting": 0.0,
    
    # Solar-Assistant power metrics
    "sa_pv_power": 0,
    "sa_load_power": 0,
    "sa_battery_power": 0,
    
    # Cycled key-value parameters
    "soh": None,
    "charge_efficiency": None,
    "fw_version": "",
    "cycles": None,
    "charged_energy_acc": None,
    "discharged_energy_acc": None,
    "vlow_setting": None,
    "vnom_setting": None,
    "vfull_setting": None,
    
    # Full cell array
    "cells": [{"cell_id": i + 1, "voltage": 0.0, "temp": 0, "last_update": 0} for i in range(22)]
}

# Lock for multi-threaded access to global data
data_lock = threading.Lock()

# Status Byte decoding helpers
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
        return []

def calculate_lto_soc(avg_voltage):
    # Lookup table for Yinlong LTO cells (voltage, soc_percentage)
    lut = [
        (1.50, 0),
        (1.85, 5),
        (2.00, 10),
        (2.15, 20),
        (2.20, 35),
        (2.23, 50),
        (2.27, 65),
        (2.32, 75),
        (2.40, 82),
        (2.50, 90),
        (2.60, 96),
        (2.65, 99),
        (2.70, 100)
    ]
    
    if avg_voltage <= lut[0][0]:
        return 0
    if avg_voltage >= lut[-1][0]:
        return 100
        
    for i in range(len(lut) - 1):
        v0, s0 = lut[i]
        v1, s1 = lut[i+1]
        if v0 <= avg_voltage < v1:
            return s0 + (avg_voltage - v0) * (s1 - s0) / (v1 - v0)
    return 100


def parse_and_update_state(packet, kv_store):
    global latest_data
    
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

    # 7. Lowest Temperature
    t_lowest = int.from_bytes(packet[18:20], byteorder='big') - 276
    cell_t_lowest = packet[20]

    # 8. Highest Temperature
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

    # Safe updates under the lock
    with data_lock:
        latest_data["total_voltage"] = total_voltage
        latest_data["current_i1"] = current_i1
        latest_data["current_i2"] = current_i2
        latest_data["current_total"] = current_total
        latest_data["v_lowest"] = v_lowest
        latest_data["cell_v_lowest"] = cell_v_lowest
        latest_data["v_highest"] = v_highest
        latest_data["cell_v_highest"] = cell_v_highest
        latest_data["t_lowest"] = t_lowest
        latest_data["cell_t_lowest"] = cell_t_lowest
        latest_data["t_highest"] = t_highest
        latest_data["cell_t_highest"] = cell_t_highest
        latest_data["nr_of_cells"] = nr_of_cells
        latest_data["status_flags_1"] = status_flags_1
        latest_data["today_energy_collected_wh"] = today_energy_collected
        latest_data["energy_stored_wh"] = energy_stored
        latest_data["today_energy_consumed_wh"] = today_energy_consumed
        latest_data["soc_pct"] = soc_pct
        latest_data["total_collected_kwh"] = total_collected_kwh
        latest_data["total_consumed_kwh"] = total_consumed_kwh
        latest_data["battery_capacity_kwh"] = battery_capacity_kwh
        latest_data["v_min_setting"] = v_min_setting
        latest_data["v_max_setting"] = v_max_setting
        latest_data["v_balance_setting"] = v_balance_setting
        
        # Load accumulated key-values
        latest_data["soh"] = kv_store.get_soh()
        latest_data["charge_efficiency"] = kv_store.get_charge_efficiency()
        latest_data["fw_version"] = kv_store.get_fw_version()
        latest_data["cycles"] = kv_store.get_cycles()
        latest_data["charged_energy_acc"] = kv_store.get_charged_energy()
        latest_data["discharged_energy_acc"] = kv_store.get_discharged_energy()
        latest_data["vlow_setting"] = kv_store.get_vlow()
        latest_data["vnom_setting"] = kv_store.get_vnom()
        latest_data["vfull_setting"] = kv_store.get_vfull()
        
        # Load extra status from key 16
        latest_data["status_flags_2"] = kv_store.get_status_byte_2()

        # Update specific cell status in cells array
        if len(latest_data["cells"]) != nr_of_cells:
            # Initialize or resize array
            latest_data["cells"] = [{"cell_id": i + 1, "voltage": 0.0, "temp": 0, "last_update": 0} for i in range(nr_of_cells)]

        if 1 <= specific_cell_nr <= nr_of_cells:
            latest_data["cells"][specific_cell_nr - 1] = {
                "cell_id": specific_cell_nr,
                "voltage": v_specific,
                "temp": t_specific,
                "last_update": time.time()
            }
        latest_data["last_updated_cell_id"] = specific_cell_nr

        # Calculate custom LTO SoC based on Yinlong 40Ah curve
        valid_voltages = [c["voltage"] for c in latest_data["cells"] if c["voltage"] > 0]
        if valid_voltages:
            avg_cell_v = sum(valid_voltages) / len(valid_voltages)
        else:
            avg_cell_v = total_voltage / nr_of_cells if nr_of_cells > 0 else 0
            
        if avg_cell_v > 0:
            custom_soc = calculate_lto_soc(avg_cell_v)
            latest_data["soc_pct"] = int(round(custom_soc))
            
            # Using real pack capacity (40Ah * 10 parallel = 400Ah)
            # 400Ah * 2.3V * nr_of_cells = total Wh capacity
            cells_count = nr_of_cells if nr_of_cells > 0 else 22
            actual_capacity_wh = 400.0 * 2.3 * cells_count
            latest_data["battery_capacity_kwh"] = actual_capacity_wh / 1000.0
            latest_data["energy_stored_wh"] = int(round((latest_data["soc_pct"] / 100.0) * actual_capacity_wh))


def serial_reader_thread():
    port = "/dev/serial0"
    baud = 9600
    
    print(f"[UART] Opening {port} at {baud} bps...")
    while True:
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5
            )
            print("[UART] Connected successfully!")
            break
        except Exception as e:
            print(f"[UART] Error opening port {port}: {e}. Retrying in 5s...")
            time.sleep(5)
            
    kv_store = KeyValueStore()
    buffer = bytearray()
    
    try:
        while True:
            # Read available bytes or wait
            data = ser.read(ser.in_waiting or 1)
            if data:
                buffer.extend(data)
                
            # Align and process frames
            while len(buffer) >= 58:
                calc_sum = sum(buffer[:57]) & 0xFF
                exp_sum = buffer[57]
                
                if calc_sum == exp_sum:
                    packet = bytes(buffer[:58])
                    del buffer[:58]
                    try:
                        parse_and_update_state(packet, kv_store)
                    except Exception as ex:
                        print(f"[UART] Parse error: {ex}")
                else:
                    # Slide window
                    buffer.pop(0)
                    
            time.sleep(0.05)
    except Exception as e:
        print(f"[UART] Thread exception: {e}")
    finally:
        ser.close()


class BMSHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence access logging to keep terminal clean
        return

    def do_GET(self):
        global latest_data
        
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            # Read index.html from local folder
            script_dir = os.path.dirname(os.path.abspath(__file__))
            index_path = os.path.join(script_dir, 'index.html')
            
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            except Exception as e:
                self.wfile.write(f"Error loading index.html: {e}".encode('utf-8'))
                
        elif self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            with data_lock:
                json_str = json.dumps(latest_data)
                
            self.wfile.write(json_str.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")


def run_web_server(port=8080):
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, BMSHTTPRequestHandler)
    print(f"[HTTP] Server running on http://0.0.0.0:{port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("[HTTP] Server stopped.")


def daly_emulator_thread():
    port = "/dev/ttyBMS_backend"
    baud = 9600
    
    while True:
        print(f"[Daly Emulator] Opening {port} at {baud} bps...")
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5
            )
            print("[Daly Emulator] Connected successfully!")
        except Exception as e:
            print(f"[Daly Emulator] Error opening port {port}: {e}. Retrying in 5s...")
            time.sleep(5)
            continue
            
        buffer = bytearray()
        life_cycle = 0
        
        try:
            while True:
                # Read from PTY
                data = ser.read(ser.in_waiting or 1)
                if data:
                    buffer.extend(data)
                    
                # A Daly request frame is 13 bytes
                while len(buffer) >= 13:
                    # Find start byte (0xA5) and destination address (0x40)
                    start_idx = -1
                    for i in range(len(buffer) - 1):
                        if buffer[i] == 0xA5 and buffer[i+1] == 0x40:
                            start_idx = i
                            break
                            
                    if start_idx == -1:
                        if len(buffer) > 0:
                            last_byte = buffer[-1]
                            buffer.clear()
                            if last_byte == 0xA5:
                                buffer.append(0xA5)
                        break
                        
                    if start_idx > 0:
                        del buffer[:start_idx]
                        
                    if len(buffer) < 13:
                        break
                        
                    # Validate checksum of the 13-byte query
                    calc_sum = sum(buffer[:12]) & 0xFF
                    exp_sum = buffer[12]
                    
                    if calc_sum == exp_sum:
                        query = bytes(buffer[:13])
                        del buffer[:13]
                        
                        cmd = query[2]
                        
                        # Prepare response
                        response_data = bytearray(8)
                        
                        with data_lock:
                            total_v = latest_data["total_voltage"]
                            curr_total = latest_data["current_total"]
                            soc = latest_data["soc_pct"]
                            v_highest = latest_data["v_highest"]
                            c_highest = latest_data["cell_v_highest"]
                            v_lowest = latest_data["v_lowest"]
                            c_lowest = latest_data["cell_v_lowest"]
                            t_highest = latest_data["t_highest"]
                            t_lowest = latest_data["t_lowest"]
                            status_flags = latest_data["status_flags_1"]
                            cells = latest_data["cells"]
                            nr_of_cells = latest_data["nr_of_cells"] if latest_data["nr_of_cells"] > 0 else 22
                        
                        if cmd == 0x90:
                            # Voltage, Current, SOC
                            val_v = int(round(total_v * 10))
                            response_data[0:2] = val_v.to_bytes(2, byteorder='big')
                            response_data[2:4] = val_v.to_bytes(2, byteorder='big')
                            
                            val_c = int(round(curr_total * 10)) + 30000
                            response_data[4:6] = val_c.to_bytes(2, byteorder='big')
                            
                            val_soc = int(round(soc * 10))
                            response_data[6:8] = val_soc.to_bytes(2, byteorder='big')
                            
                        elif cmd == 0x91:
                            # Min/Max Cell Voltages
                            val_max_v = int(round(v_highest * 1000))
                            response_data[0:2] = val_max_v.to_bytes(2, byteorder='big')
                            response_data[2] = c_highest
                            
                            val_min_v = int(round(v_lowest * 1000))
                            response_data[3:5] = val_min_v.to_bytes(2, byteorder='big')
                            response_data[5] = c_lowest
                            
                        elif cmd == 0x92:
                            # Temperatures (offset by 40)
                            response_data[0] = max(0, min(255, int(t_highest) + 40))
                            response_data[1] = 1
                            response_data[2] = max(0, min(255, int(t_lowest) + 40))
                            response_data[3] = 1
                            
                        elif cmd == 0x93:
                            # MOS Status & Capacity
                            chg_mos = 1 if "Allow to charge" in status_flags else 0
                            dis_mos = 1 if "Allow to discharge" in status_flags else 0
                            
                            if curr_total > 0.5:
                                bms_state = 1
                            elif curr_total < -0.5:
                                bms_state = 2
                            else:
                                bms_state = 0
                                
                            response_data[0] = chg_mos
                            response_data[1] = dis_mos
                            response_data[2] = bms_state
                            
                            life_cycle = (life_cycle + 1) % 256
                            response_data[3] = life_cycle
                            
                            rem_cap_mah = int(round(soc * 4000)) # 400Ah capacity -> 400000mAh * (soc/100)
                            response_data[4:8] = rem_cap_mah.to_bytes(4, byteorder='big')
                            
                        elif cmd == 0x94:
                            # Status Info
                            response_data[0] = nr_of_cells
                            response_data[1] = 2
                            response_data[2] = 1 if "Allow to charge" in status_flags else 0
                            response_data[3] = 1 if "Allow to discharge" in status_flags else 0
                            response_data[4] = 0x00
                            
                        elif cmd == 0x95:
                            # Cell Voltages (3 cells per frame)
                            frame_num = query[4]
                            response_data[0] = frame_num
                            
                            start_cell_idx = (frame_num - 1) * 3
                            for i in range(3):
                                cell_idx = start_cell_idx + i
                                if cell_idx < len(cells):
                                    cv = int(round(cells[cell_idx]["voltage"] * 1000))
                                else:
                                    cv = 0
                                response_data[1 + i*2 : 3 + i*2] = cv.to_bytes(2, byteorder='big')
                                
                        elif cmd == 0x96:
                            # Cell Temperatures
                            frame_num = query[4]
                            response_data[0] = frame_num
                            t1 = max(0, min(255, int(t_highest) + 40))
                            t2 = max(0, min(255, int(t_lowest) + 40))
                            response_data[1] = t1
                            response_data[2] = t2
                            
                        elif cmd == 0x97:
                            # Balance status
                            response_data[0:4] = b'\x00\x00\x00\x00'
                            
                        elif cmd == 0x98:
                            # Alarm status
                            response_data[0:8] = b'\x00\x00\x00\x00\x00\x00\x00\x00'
                            
                        else:
                            continue
                            
                        # Build response frame
                        resp_frame = bytearray([0xA5, 0x01, cmd, 0x08])
                        resp_frame.extend(response_data)
                        checksum = sum(resp_frame) & 0xFF
                        resp_frame.append(checksum)
                        
                        ser.write(resp_frame)
                    else:
                        buffer.pop(0)
                        
                time.sleep(0.01)
        except Exception as e:
            print(f"[Daly Emulator] Exception: {e}. Reconnecting...")
            try:
                ser.close()
            except:
                pass
            time.sleep(2)

def influx_reader_thread():
    print("[InfluxDB Reader] Starting InfluxDB telemetry thread...")
    while True:
        try:
            query = 'SELECT combined FROM "PV power" ORDER BY time DESC LIMIT 1; SELECT combined FROM "Load power" ORDER BY time DESC LIMIT 1; SELECT combined FROM "Battery power" ORDER BY time DESC LIMIT 1'
            url = 'http://localhost:8086/query?db=solar_assistant&q=' + urllib.parse.quote(query)
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                results = res_data.get("results", [])
                
                pv_power = 0
                load_power = 0
                battery_power = 0
                
                if len(results) > 0 and "series" in results[0]:
                    pv_power = int(round(results[0]["series"][0]["values"][0][1]))
                if len(results) > 1 and "series" in results[1]:
                    load_power = int(round(results[1]["series"][0]["values"][0][1]))
                if len(results) > 2 and "series" in results[2]:
                    battery_power = int(round(results[2]["series"][0]["values"][0][1]))
                
                with data_lock:
                    latest_data["sa_pv_power"] = pv_power
                    latest_data["sa_load_power"] = load_power
                    latest_data["sa_battery_power"] = battery_power
        except Exception as e:
            # Silence exception to avoid log flooding
            pass
            
        time.sleep(2)

def main():
    # 1. Start UART reading thread
    reader = threading.Thread(target=serial_reader_thread, daemon=True)
    reader.start()
    
    # 2. Start Daly emulator thread
    emulator = threading.Thread(target=daly_emulator_thread, daemon=True)
    emulator.start()
    
    # 3. Start InfluxDB reader thread
    influx_reader = threading.Thread(target=influx_reader_thread, daemon=True)
    influx_reader.start()
    
    # 4. Run HTTP server in main thread
    run_web_server(port=8080)

if __name__ == "__main__":
    main()
