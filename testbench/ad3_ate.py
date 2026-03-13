import ctypes
import sys
import time

# Load the Digilent WaveForms Dynamic Library based on the OS
if sys.platform.startswith("darwin"):
    # macOS path
    dwf = ctypes.cdll.LoadLibrary("Library/Location")
elif sys.platform.startswith("win"):
    # Windows path
    dwf = ctypes.cdll.dwf
else:
    # Linux path
    dwf = ctypes.cdll.LoadLibrary("libdwf.so")

class AD3TestExecutive:
    def __init__(self):
        self.dwf = dwf
        self.hdwf = ctypes.c_int(0)
        
        # 1. Print the API Version to prove the library loaded
        version = ctypes.create_string_buffer(16)
        dwf.FDwfGetVersion(version)
        print(f"Loaded WaveForms API Version: {version.value.decode()}")

        # 2. Force the OS to enumerate (count) the Digilent USB devices
        cdevices = ctypes.c_int()
        dwf.FDwfEnum(ctypes.c_int(0), ctypes.byref(cdevices))
        print(f"Hardware Scan: Found {cdevices.value} Digilent devices on the USB bus.")

        if cdevices.value == 0:
            print("OS ERROR: The Mac does not see the AD3. Check cables/USB permissions.")
            sys.exit(1)

        # 3. Open the first available AD3
        print("Opening Analog Discovery 3...")
        dwf.FDwfDeviceOpen(ctypes.c_int(0), ctypes.byref(self.hdwf))
        
        if self.hdwf.value == 0:
            print("HARDWARE ERROR: AD3 is visible, but the USB port is locked by another program.")
            sys.exit(1)
            
        print("AD3 Successfully Connected!")
        
        # Configure Digital I/O (DIO) Pins
        # 0x0003 enables Pin 0 (HITL) and Pin 1 (NRST) as outputs
        dwf.FDwfDigitalIOOutputEnableSet(self.hdwf, ctypes.c_int(0x0003)) 
        
        # Set DIO-0 LOW (0V) and DIO-1 HIGH (3.3V)
        dwf.FDwfDigitalIOOutputSet(self.hdwf, ctypes.c_int(0x0002))
        
    def pulse_hitl_bypass(self):
        """Fires a 10ms 3.3V pulse on DIO-0."""
        dwf.FDwfDigitalIOOutputSet(self.hdwf, ctypes.c_int(0x0003))
        time.sleep(0.01) 
        dwf.FDwfDigitalIOOutputSet(self.hdwf, ctypes.c_int(0x0002))
    
    def hard_reset_mcu(self):
        """Violently reboots the STM32 by yanking the NRST pin to 0V."""
        print("[ATE] DEADLOCK DETECTED: Firing Hardware NRST Reset...")
        dwf.FDwfDigitalIOOutputSet(self.hdwf, ctypes.c_int(0x0000))
        time.sleep(0.05)
        dwf.FDwfDigitalIOOutputSet(self.hdwf, ctypes.c_int(0x0002))
        time.sleep(0.1) 
        print("[ATE] MCU Rebooted and Ready.")

    def arm_glitch_pulse(self, delay_us, pulse_width_ns=15):
        print(f"[ATE] Arming Glitch Weapon: {delay_us}µs delay, {pulse_width_ns}ns pulse width.")
        
        glitch_pin = ctypes.c_int(3) 
        trigsrcDetectorDigitalIn = ctypes.c_ubyte(3) 
        
        # 1. Configure the Trigger condition
        self.dwf.FDwfDigitalInTriggerSourceSet(self.hdwf, trigsrcDetectorDigitalIn)
        self.dwf.FDwfDigitalInTriggerSet(self.hdwf, ctypes.c_int(0), ctypes.c_int(0), ctypes.c_int(1<<2), ctypes.c_int(0))
        
        # 2. Enable the Pattern Generator
        self.dwf.FDwfDigitalOutEnableSet(self.hdwf, glitch_pin, ctypes.c_int(1))
        self.dwf.FDwfDigitalOutDividerSet(self.hdwf, glitch_pin, ctypes.c_int(1)) 
        self.dwf.FDwfDigitalOutIdleSet(self.hdwf, glitch_pin, ctypes.c_int(1)) # 1 = Idle LOW
        self.dwf.FDwfDigitalOutTypeSet(self.hdwf, glitch_pin, ctypes.c_int(0)) # 0 = Pulse
        
        # --- Force the pulse to stay HIGH ---
        # Initialize the counter to start HIGH (1) with 0 offset
        self.dwf.FDwfDigitalOutCounterInitSet(self.hdwf, glitch_pin, ctypes.c_int(1), ctypes.c_int(0))
        # Stay LOW for 0 ticks, Stay HIGH for 1,000,000 ticks (guarantees a solid 3.3V block)
        self.dwf.FDwfDigitalOutCounterSet(self.hdwf, glitch_pin, ctypes.c_int(0), ctypes.c_int(1000000))
        
        # 3. Setup Trigger & Timing
        self.dwf.FDwfDigitalOutTriggerSourceSet(self.hdwf, trigsrcDetectorDigitalIn)
        delay_sec = delay_us / 1_000_000.0
        self.dwf.FDwfDigitalOutWaitSet(self.hdwf, ctypes.c_double(delay_sec))
        
        run_sec = pulse_width_ns / 1_000_000_000.0
        self.dwf.FDwfDigitalOutRunSet(self.hdwf, ctypes.c_double(run_sec))
        
        self.dwf.FDwfDigitalOutRepeatSet(self.hdwf, ctypes.c_int(1)) 
        
        # 4. Arm it
        self.dwf.FDwfDigitalInConfigure(self.hdwf, ctypes.c_int(1), ctypes.c_int(1))
        self.dwf.FDwfDigitalOutConfigure(self.hdwf, ctypes.c_int(1))

    def close(self):
        print("Closing AD3 USB Connection...")
        dwf.FDwfDeviceCloseAll()