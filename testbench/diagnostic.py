import serial
import time
import ctypes
import sys

SERIAL_PORT = '/port' # UPDATE to MAC ST LINK PORT
BAUD_RATE = 115200

# Command IDs
SYNC_BYTE = 0xAA
CMD_ECHO = 0x00
CMD_SET_FREQ = 0x03

print("[*] Initializing Digilent AD3...")
try:
    dwf = ctypes.cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
except Exception as e:
    print(f"[!] Failed to load DWF. {e}")
    sys.exit(1)

hdwf = ctypes.c_int()
dwf.FDwfDeviceOpen(ctypes.c_int(-1), ctypes.byref(hdwf))
dwf.FDwfDigitalIOOutputEnableSet(hdwf, ctypes.c_int(0xFFFF))
dwf.FDwfDigitalIOOutputSet(hdwf, ctypes.c_int(0x0002)) # NRST HIGH

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2.0)
except Exception as e:
    print(f"[!] Could not open Serial Port: {e}")
    sys.exit(1)

print("\n=============================================")
print("      PHASE 5: SYSTEM DIAGNOSTIC TOOL        ")
print("=============================================\n")

# --- TEST 1: AD3 HARD RESET ---
print("[1] Testing AD3 Hard Reset (NRST)...")
dwf.FDwfDigitalIOOutputSet(hdwf, ctypes.c_int(0x0000)) # NRST LOW
time.sleep(0.1)
dwf.FDwfDigitalIOOutputSet(hdwf, ctypes.c_int(0x0002)) # NRST HIGH
time.sleep(1.0) # Wait for STM32 to fully boot
print("    [+] Reset complete. Board should be alive.\n")

# --- TEST 2: DMA ECHO ---
print("[2] Testing DMA Echo Pipeline...")
ser.reset_input_buffer()
test_payload = b"HELLO_DMA"
# [SYNC] [CMD] [LEN] [PAYLOAD]
echo_packet = bytes([SYNC_BYTE, CMD_ECHO, len(test_payload)]) + test_payload
ser.write(echo_packet)

response = ser.read(len(test_payload))
if response == test_payload:
    print("    [+] Echo SUCCESS. DMA is working perfectly.\n")
else:
    print(f"    [!] Echo FAILED. Received: {response}\n")

# --- TEST 3: THE 96MHz SHIFT ---
print("[3] Testing DFS Shift to Baseline 96MHz...")
# We are commanding it to shift to PLLN 192 (96MHz)
freq_packet = bytes([SYNC_BYTE, CMD_SET_FREQ, 1, 192])
ser.write(freq_packet)

print("    [*] Waiting for board to shift clocks and reply...")
start_time = time.time()
sync_resp = ser.read(1)
end_time = time.time()

if len(sync_resp) == 0:
    print("    [!] TIMEOUT. The board crashed or locked up during the clock shift.")
elif sync_resp[0] == SYNC_BYTE:
    print(f"    [+] SUCCESS! Received SYNC byte in {end_time - start_time:.4f} seconds.")
else:
    print(f"    [!] BAUD RATE CORRUPTION. Received garbage byte: {hex(sync_resp[0])}")

print("\n[*] Diagnostics Complete.")
ser.close()
dwf.FDwfDeviceCloseAll()