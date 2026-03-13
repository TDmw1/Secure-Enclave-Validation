#include "stm32f411xe.h"
#include <stdint.h>

#include "crypto.h"

#include <string.h> // Required for memcmp and memset

// Resides in rewritable SRAM
uint8_t ENCLAVE_SECRET_KEY[] = "MY_NEW_CUSTOM_API_KEY_9988776655";

// --- PACKET & FSM DEFINITIONS ---
#define SYNC_BYTE 0xAA

// Command IDs
#define CMD_ECHO        0x00
#define CMD_EXEC_HASH   0x01
#define CMD_AI_POLICY   0x02
#define CMD_SET_FREQ    0x03

// Response Codes
#define RESP_SUCCESS       0x10
#define RESP_PENDING_AUTH  0x11
#define RESP_ERR_SYNC      0xFF

// Force the compiler to pack this struct tightly (no hidden padding bytes)
#pragma pack(push, 1)
typedef struct {
    uint8_t sync;
    uint8_t cmd_id;
    uint8_t payload_len; 
    // Payload bytes follow immediately after
} PacketHeader;
#pragma pack(pop)

// System States
typedef enum {
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_AWAITING_BUTTON
} EnclaveState;

volatile EnclaveState current_state = STATE_IDLE;


#define RX_BUFFER_SIZE 256
volatile uint8_t rx_buffer[RX_BUFFER_SIZE];
volatile uint8_t packet_received = 0;
volatile uint16_t packet_length = 0;

// Clock Tree Code
void SystemClock_Config_96MHz(void) {
    RCC->CR |= RCC_CR_HSEBYP | RCC_CR_HSEON;  
    while (!(RCC->CR & RCC_CR_HSERDY)); 
    RCC->APB1ENR |= RCC_APB1ENR_PWREN;
    PWR->CR |= PWR_CR_VOS_1 | PWR_CR_VOS_0; 
    FLASH->ACR = FLASH_ACR_LATENCY_3WS | FLASH_ACR_ICEN | FLASH_ACR_DCEN | FLASH_ACR_PRFTEN;
    RCC->PLLCFGR = (4 << RCC_PLLCFGR_PLLM_Pos) | (192 << RCC_PLLCFGR_PLLN_Pos) | (1 << RCC_PLLCFGR_PLLP_Pos) | RCC_PLLCFGR_PLLSRC_HSE;         
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));
    RCC->CFGR |= RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV1; 
    RCC->CFGR |= RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL); 
}

// Dynamic Frequency & Voltage Scaling
void SystemClock_Update_DFS(uint16_t target_plln, uint8_t target_vos) {
    // 1. Switch system clock to HSE (8MHz) temporarily
    RCC->CFGR &= ~RCC_CFGR_SW;
    RCC->CFGR |= RCC_CFGR_SW_HSE;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_HSE);

    // 2. Disable PLL
    RCC->CR &= ~RCC_CR_PLLON;
    while (RCC->CR & RCC_CR_PLLRDY);

    // 3. DYNAMIC VOLTAGE SCALING (Undervolting)
    // Clear bits 14 and 15, then set requested VOS scale (1, 2, or 3)
    PWR->CR &= ~(0x3 << 14); 
    PWR->CR |= (target_vos << 14);

    // 4. DYNAMIC FLASH SCALING
    if (target_plln > 200) {
        FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    } else {
        FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_3WS;
    }

    // 5. Update PLLN multiplier
    RCC->PLLCFGR &= ~(0x1FF << RCC_PLLCFGR_PLLN_Pos);
    RCC->PLLCFGR |= ((uint32_t)target_plln << RCC_PLLCFGR_PLLN_Pos);

    // 6. Re-enable PLL
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));

    // 7. Switch system clock back to PLL
    RCC->CFGR &= ~RCC_CFGR_SW;
    RCC->CFGR |= RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
    
    // 8. UPDATE BAUD RATE
    uint32_t pclk1 = (target_plln * 1000000) / 4;
    USART2->BRR = (pclk1 + 57600) / 115200; 
}

// UART and DMA Initialization
void UART2_DMA_Init(void) {
    // 1. Enable Clocks for GPIOA, USART2, and DMA1
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_DMA1EN;
    RCC->APB1ENR |= RCC_APB1ENR_USART2EN;

    // 2. Configure PA2 (TX) and PA3 (RX) for Alternate Function (AF7 = USART2)
    GPIOA->MODER &= ~(GPIO_MODER_MODE2 | GPIO_MODER_MODE3);
    GPIOA->MODER |= (GPIO_MODER_MODE2_1 | GPIO_MODER_MODE3_1); // Set to AF mode (10)
    GPIOA->AFR[0] |= (7 << GPIO_AFRL_AFSEL2_Pos) | (7 << GPIO_AFRL_AFSEL3_Pos); // AF7

    // 3. Configure USART2 (115200 Baud @ 48MHz APB1)
    USART2->BRR = 0x1A1; 
    USART2->CR3 |= USART_CR3_DMAR; // Enable DMA Receiver for USART2
    USART2->CR1 |= USART_CR1_TE | USART_CR1_RE | USART_CR1_IDLEIE | USART_CR1_UE; // Enable TX, RX, IDLE Interrupt, and USART

    // 4. Configure DMA1 Stream 5 Channel 4 (Mapped to USART2 RX)
    DMA1_Stream5->CR &= ~DMA_SxCR_EN; // Disable DMA to configure it
    while (DMA1_Stream5->CR & DMA_SxCR_EN); // Wait until disabled
    
    DMA1_Stream5->PAR = (uint32_t)&USART2->DR;     // Peripheral Address (UART Data Register)
    DMA1_Stream5->M0AR = (uint32_t)rx_buffer;      // Memory Address (array)
    DMA1_Stream5->NDTR = RX_BUFFER_SIZE;           // Number of bytes to receive before rolling over
    
    // Channel 4, MINC (Memory Increment), Circular Mode, Transfer Complete Interrupt
    DMA1_Stream5->CR |= (4 << DMA_SxCR_CHSEL_Pos) | DMA_SxCR_MINC | DMA_SxCR_CIRC;
    DMA1_Stream5->CR |= DMA_SxCR_EN; // Enable DMA

    // 5. Enable the USART2 Interrupt in the NVIC
    NVIC_EnableIRQ(USART2_IRQn);
}

void HITL_Button_Init(void) {
    // 1. Enable GPIOA Clock (Already enabled by UART, but redundant)
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;

    // 2. Configure PA4 as Input (00 in MODER)
    GPIOA->MODER &= ~(GPIO_MODER_MODE4);

    // 3. Enable Pull-Down Resistor (10 in PUPDR)
    // This ensures PA4 stays at 0V until the AD3 physically drives it to 3.3V
    GPIOA->PUPDR &= ~(GPIO_PUPDR_PUPD4);
    GPIOA->PUPDR |= GPIO_PUPDR_PUPD4_1;
}

// Bare-metal blocking TX function for echo test
void UART2_SendBuffer(uint8_t *buffer, uint16_t length) {
    for (uint16_t i = 0; i < length; i++) {
        while (!(USART2->SR & USART_SR_TXE)); // Wait for Transmit Data Register Empty
        USART2->DR = buffer[i];               // Load next byte
    }
}

// --- THE INTERRUPT HANDLER ---
// This fires automatically when the host computer stops sending data for 1 frame
void USART2_IRQHandler(void) {
    if (USART2->SR & USART_SR_IDLE) {
        volatile uint32_t tmp = USART2->DR; // Reading SR then DR clears the IDLE flag
        (void)tmp;

        // Calculate how many bytes the DMA actually transferred
        packet_length = RX_BUFFER_SIZE - DMA1_Stream5->NDTR;
        packet_received = 1;
        
        // Reset DMA for the next packet
        DMA1_Stream5->CR &= ~DMA_SxCR_EN;
        while (DMA1_Stream5->CR & DMA_SxCR_EN);
        DMA1_Stream5->NDTR = RX_BUFFER_SIZE;
        DMA1_Stream5->CR |= DMA_SxCR_EN;
    }
}

void Glitch_Trigger_Init(void) {
    // 1. Enable GPIOB Clock
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
    
    // 2. Configure PB0 as General Purpose Output (01 in MODER)
    GPIOB->MODER &= ~(GPIO_MODER_MODE0); 
    GPIOB->MODER |= GPIO_MODER_MODE0_0;
    
    // 3. Set PB0 to Maximum Output Speed (11 in OSPEEDR) 
    // This is critical for nanosecond precision.
    GPIOB->OSPEEDR |= GPIO_OSPEEDER_OSPEEDR0;
    
    // 4. Ensure it starts LOW
    GPIOB->BSRR = GPIO_BSRR_BR0; 
}

int main(void) {
    SystemClock_Config_96MHz();
    UART2_DMA_Init();

    // Inside main()
    HITL_Button_Init();
    Glitch_Trigger_Init();

    while(1) {
        // --- 1. HANDLE NEW INCOMING PACKETS ---
        if (packet_received) {
            PacketHeader *header = (PacketHeader *)rx_buffer;
            
            if (header->sync != SYNC_BYTE) {
                uint8_t err = RESP_ERR_SYNC;
                UART2_SendBuffer(&err, 1);
            } else {
                switch (header->cmd_id) {
                    case CMD_ECHO:
                        UART2_SendBuffer((uint8_t*)&rx_buffer[3], header->payload_len);
                        current_state = STATE_IDLE;
                        break;
                        
                    case CMD_EXEC_HASH: {
                        uint8_t mac_output_1[32];
                        uint8_t mac_output_2[32];
                        
                        // --- ARM THE TRIGGER (PB0 HIGH) ---
                        GPIOB->BSRR = GPIO_BSRR_BS0;
                        
                        // Execution 1
                        hmac_sha256(ENCLAVE_SECRET_KEY, sizeof(ENCLAVE_SECRET_KEY)-1, 
                                    (uint8_t*)&rx_buffer[3], header->payload_len, mac_output_1);
                                    
                        // Execution 2 (Redundancy)
                        hmac_sha256(ENCLAVE_SECRET_KEY, sizeof(ENCLAVE_SECRET_KEY)-1, 
                                    (uint8_t*)&rx_buffer[3], header->payload_len, mac_output_2);
                                    
                        // --- DISARM THE TRIGGER (PB0 LOW) ---
                        GPIOB->BSRR = GPIO_BSRR_BR0;
                        
                        // --- Control Flow Integrity Check ---
                        if (memcmp(mac_output_1, mac_output_2, 32) != 0) {
                            // Glitch Detected

                            // 1. Securely Zeroize the SRAM Key
                            memset(ENCLAVE_SECRET_KEY, 0, sizeof(ENCLAVE_SECRET_KEY));
                            
                            // 2. Zeroize the output buffers to prevent partial leakage
                            memset(mac_output_1, 0, 32);
                            memset(mac_output_2, 0, 32);
                            
                            // 3. Fail Shut: Trap the core. 
                            // It will stop responding to the host computer, and the Python ATE 
                            // will eventually flag a Type C Hang and trigger the AD3 hard-reset.
                            while(1) {
                                // Locked.
                            }
                        }
                        
                        // If survived the trap (math was perfect), blast the signature back
                        UART2_SendBuffer(mac_output_1, 32);
                        current_state = STATE_IDLE;
                        break;
                    }
                        
                    case CMD_AI_POLICY:
                        // Trap the state. Send the Auth Request.
                        uint8_t auth_req = RESP_PENDING_AUTH;
                        UART2_SendBuffer(&auth_req, 1);
                        current_state = STATE_AWAITING_BUTTON;
                        break;
                        
                    case CMD_SET_FREQ: {
                        // Payload: [PLLN_Low] [PLLN_High] [VOS_Scale]
                        uint16_t new_plln = rx_buffer[3] | (rx_buffer[4] << 8);
                        uint8_t new_vos = rx_buffer[5];
                        
                        // Execute the frequency AND voltage shift
                        SystemClock_Update_DFS(new_plln, new_vos);
                        
                        uint8_t sync_resp = SYNC_BYTE;
                        UART2_SendBuffer(&sync_resp, 1);
                        current_state = STATE_IDLE;
                        break;
                    }
                    
                }
            }
            packet_received = 0;
        }

        // --- 2. HANDLE THE HITL HARDWARE INTERRUPT ---
        if (current_state == STATE_AWAITING_BUTTON) {
            // Read the IDR (Input Data Register) for PA4
            if (GPIOA->IDR & GPIO_IDR_ID4) { 
                
                // The AD3 pulsed the pin. The HITL requirement is met.
                PacketHeader *header = (PacketHeader *)rx_buffer;
                uint8_t mac_output[32];
                
                // Execute the Cryptography
                hmac_sha256(ENCLAVE_SECRET_KEY, sizeof(ENCLAVE_SECRET_KEY)-1, 
                            (uint8_t*)&rx_buffer[3], header->payload_len, mac_output);
                
                // Blast the 32-byte signature back to the Mac and reset state
                UART2_SendBuffer(mac_output, 32);
                current_state = STATE_IDLE;
            }
        }
    }
}
