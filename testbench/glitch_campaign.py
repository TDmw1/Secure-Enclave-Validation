import serial
import time
import csv
import hmac
import hashlib
import ctypes
import sys

# --- TARGET PARAMETERS ---
SERIAL_PORT = '/STLINKPORT' # UPDATE THIS to ST link port
BAUD_RATE = 115200
SECRET_KEY = b"MY_NEW_CUSTOM_API_KEY_9988776655"

# --- COMMAND DEFINITIONS ---
SYNC_BYTE = 0xAA
CMD_EXEC_HASH = 0x01
CMD_SET_FREQ = 0x03

# --- OVERCLOCKING CAMPAIGN SETUP ---
# PLLN 192 = 96MHz (Baseline). Sweep up to 250 (125 MHz)
START_PLLN = 192
END_PLLN = 300
STEP_PLLN = 2
TESTS_PER_FREQ = 50 # How many packets to send at each frequency to find edge cases

# --- AD3 / DWF SETUP (macOS) ---
print("[*] Initializing Digilent AD3 for Hardware Recovery...")
try:
    dwf = ctypes.cdll.LoadLibrary("path/to/dwf")
except Exception as e:
    print(f"[!] Failed to load DWF framework. Is WaveForms installed? {e}")
    sys.exit(1)

hdwf = ctypes.c_int()
dwf.FDwfDeviceOpen(ctypes.c_int(-1), ctypes.byref(hdwf))
if hdwf.value == 0:
    print("[!] Failed to open AD3. Check USB connection.")
    sys.exit(1)

# Enable Digital I/O
dwf.FDwfDigitalIOOutputEnableSet(hdwf, ctypes.c_int(0xFFFF))
# Set DIO-1 (NRST) HIGH to let the board run normally
dwf.FDwfDigitalIOOutputSet(hdwf, ctypes.c_int(0x0002)) 

def hard_reset_target():
    """Drops the NRST pin LOW via AD3 to recover from Type C Hangs."""
    print("    [!] SYSTEM HANG (Type C). Executing Hard Reset via AD3...")
    dwf.FDwfDigitalIOOutputSet(hdwf, ctypes.c_int(0x0000)) # NRST LOW
    time.sleep(0.05)
    dwf.FDwfDigitalIOOutputSet(hdwf, ctypes.c_int(0x0002)) # NRST HIGH
    time.sleep(0.5) # Wait for STM32 to boot and PLL to stabilize

def get_golden_mac(payload):
    """The Golden Model: computes mathematically perfect HMAC-SHA256."""
    return hmac.new(SECRET_KEY, payload, hashlib.sha256).digest()

def main():
    # Open Serial connection
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    except Exception as e:
        print(f"[!] Could not open Serial Port: {e}")
        return

    # Open CSV for Shmoo Plot data logging
    csv_file = open('phase6_shmoo_data.csv', 'w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['Target_MHz', 'Iteration', 'Status', 'Error_Type'])

    payload = b"TEST_TEST_VECTOR_0123456789"
    golden_mac = get_golden_mac(payload)

    print("\n=======================================================")
    print("   PHASE 5: DYNAMIC FREQUENCY SCALING (DFS) CAMPAIGN   ")
    print("=======================================================\n")
    
    # Ensure board starts in a clean state
    hard_reset_target()
    ser.reset_input_buffer()

    # We will test all three voltage scales: 3 (Max), 2 (Med), 1 (Low)
    for target_vos in [3, 2, 1]:
        print(f"\n=======================================================")
        print(f"   INITIATING SWEEP AT VOLTAGE SCALE {target_vos}   ")
        print(f"=======================================================\n")
        
        for plln in range(START_PLLN, END_PLLN + 1, STEP_PLLN):
            current_mhz = plln / 2.0
            print(f"\n[*] --- CLOCK: {current_mhz} MHz | VOS: {target_vos} ---")
            
            # SEND OVERCLOCK & UNDERVOLT COMMAND
            # [SYNC] [CMD] [LEN=3] [PLLN_2BYTES] [VOS_1BYTE]
            freq_packet = bytes([SYNC_BYTE, CMD_SET_FREQ, 3]) + plln.to_bytes(2, byteorder='little') + bytes([target_vos])
            ser.write(freq_packet)
            ser.flush()
            
            # Wait for board to shift gears, lower voltage, and reply
            sync_resp = ser.read(1)
            if len(sync_resp) == 0 or sync_resp[0] != SYNC_BYTE:
                print(f"    [!] CRASH: The core could not survive {current_mhz}MHz at VOS {target_vos}.")
                hard_reset_target()
                ser.reset_input_buffer()
                continue 
                
            print(f"    [+] Shift survived. Blasting Cryptography...")

            # Blast the payloads (Keep TESTS_PER_FREQ at 10 or 20 for speed)
            for i in range(TESTS_PER_FREQ):
                hash_packet = bytes([SYNC_BYTE, CMD_EXEC_HASH, len(payload)]) + payload
                ser.write(hash_packet)
                
                response = ser.read(32)
                
                error_type = "None"
                status = "Success"
                
                if len(response) == 0:
                    error_type = "Type C"
                    status = "System Hang"
                    hard_reset_target()
                    ser.reset_input_buffer()
                    # Re-establish frequency and voltage after a hang
                    ser.write(bytes([SYNC_BYTE, CMD_SET_FREQ, 3]) + plln.to_bytes(2, byteorder='little') + bytes([target_vos]))
                    ser.read(1) 
                elif len(response) != 32:
                    error_type = "Type B"
                    status = "Hard Fault"
                elif response != golden_mac:
                    error_type = "Type A"
                    status = "SILENT DATA CORRUPTION"
                    print(f"    [!!!] TYPE A VULNERABILITY HIT AT {current_mhz}MHz / VOS {target_vos}!")
                    
                csv_writer.writerow([current_mhz, target_vos, i, status, error_type])
                csv_file.flush()
    # Cleanup
    print("\n[*] Campaign Complete. Restoring safe 96MHz baseline...")
    ser.write(bytes([SYNC_BYTE, CMD_SET_FREQ, 1, 192]))
    dwf.FDwfDeviceCloseAll()
    csv_file.close()
    ser.close()
    print("[*] Data saved to phase6_shmoo_data.csv")

if __name__ == "__main__":
    main()