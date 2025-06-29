import serial
import json
import time
from datetime import datetime

# simple serial monitor

def load_config():
    with open('config_serial.json') as config_file:
        return json.load(config_file)

def find_serial_port(port_list):
    import os
    for port in port_list:
        if os.path.exists(port):
            return port
    return None

def main():
    config = load_config()
    config_port = config.get('serial', {}).get('port')
    if isinstance(config_port, list):
        SERIAL_PORT = find_serial_port(config_port)
    else:
        SERIAL_PORT = config_port
    BAUD_RATE = 115200
    if not SERIAL_PORT:
        print(f"{datetime.now()} - Error: No serial port found in configuration")
        return
    import os
    while not os.path.exists(SERIAL_PORT):
        time.sleep(5)
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            print(f"{datetime.now()} - Serial output recognized on {SERIAL_PORT}")
            while True:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"{datetime.now()} | {line}")
                except Exception as e:
                    time.sleep(1)
    except Exception as e:
        print(f"{datetime.now()} - Error opening serial port: {str(e)}")

if __name__ == "__main__":
    main()
