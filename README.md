# Air-Gapped Secure Enclave & Fault-Injection Testbench

A bare-metal STM32 hardware security module (HSM) and automated Python Test Executive. This repository demonstrates dynamic margin testing, silicon fault injection, and Control Flow Integrity (CFI) countermeasures to defend against Silent Data Corruption.

## Overview
This project serves as a physical validation testbench designed for Post-Silicon Systems Engineering Principles. The target hardware operates as a Zero-Trust HSM, signing cryptographic payloads. The core engineering achievement is the headless Python Automated Test Equipment (ATE) built to attack, overclock, and validate the silicon using a Digilent Analog Discovery 3 (AD3), ultimately developing bare-metal firmware countermeasures to protect the chip.

## System Architecture

### 1. Bare-Metal Foundation & Variable-Length DMA
The firmware strips away standard Hardware Abstraction Layers (HAL) to achieve nanosecond determinism. 
* **DMA Pipeline:** Engineered a sVariable-Length DMA pipeline exploiting the STM32 IDLE Line Interrupt (`USART_CR1_IDLEIE`). The CPU sleeps while the DMA hardware silently shovels packed binary C-structs into SRAM.
* **Deterministic Cryptography:** Utilizes a 100% statically allocated bare-metal HMAC-SHA256 payload to establish a mathematically perfect execution baseline without heap fragmentation.

### 2. The Headless Test Executive (ATE)
Bypassed standard GUI tools to build a Python ATE script utilizing the macOS `dwf.framework` to control the Digilent AD3 headlessly. The ATE autonomously routes thousands of mixed-state packets through the Device Under Test (DUT), successfully spoofing human interrupts and executing automated hardware deadlock recoveries via the `NRST` pin.

### 3. Dynamic Margin Testing & Fault Injection
To attack the internally shielded ALU, the firmware implements Dynamic Frequency Scaling (DFS) and Dynamic Voltage Scaling (DVS). The firmware accepts 16-bit frequency commands to overwrite the STM32 Phase-Locked Loop (PLL) and Power Control (PWR) registers on the fly, calculating and updating the UART baud-rate register in under 1 millisecond so the ATE never loses connection.

## Validation Results: Shmoo Plotting & The "Fail Shut" Defense

The Python ATE executed an unattended 2D parameter sweep of Core Frequency (96MHz–150MHz) versus Voltage Scale (VOS 1-3). 

### The Golden Window (Vulnerability Identified)
At **108.0 MHz on VOS 1 (Low Power)**, the ATE successfully induced **Type A Silent Data Corruption**. The ALU transistors were starved of voltage, failing the mathematical state changes within the 9.25-nanosecond clock cycle, while the CPU survived to transmit a corrupted signature.

### Control Flow Integrity (100% Mitigation)
To patch this zero-day vulnerability, the firmware was restructured to implement a "Fail Shut" security posture:
1. **Temporal Redundancy:** The HMAC-SHA256 is calculated twice sequentially.
2. **Deterministic Trap:** The results are passed through a `memcmp` trap. Because analog glitches are non-deterministic, any dropped ALU bit results in a hash mismatch.
3. **SRAM Zeroization:** If the trap fires, the firmware securely zeroizes the SRAM master key via `memset` and deadlocks the processor in an infinite loop.

Regression testing verified a **100% conversion of dangerous Type A data leaks into secure Type C system hangs**.

## Repository Structure
* `/firmware`: The bare-metal C codebase, including the non-blocking FSM and redundant crypto logic.
* `/testbench`: The Python ATE scripts, including the dynamic 2D Shmoo campaign executive and hardware diagnostic tools.
* `/data`: Raw `.csv` outputs and generated Shmoo plot visualizations.

## Hardware Setup
* **Target:** STMicroelectronics NUCLEO-F411RE
* **ATE:** Digilent Analog Discovery 3 (AD3)
* **Wiring:** * `AD3 DIO-1` -> `STM32 NRST` (Automated Hardware Recovery)
  * `AD3 DIO-2` -> `STM32 PB0` (Nanosecond execution trigger)