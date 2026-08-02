#include <Arduino.h>
#include <Wire.h>
#include <ADXL345_WE.h>
#include <ld2410.h>
#define LORA_ENABLED
#include <SX1276.h>

#define ADXL345_I2C 0x53
ADXL345_WE adxl345 = ADXL345_WE(ADXL345_I2C);

ld2410 radar;

#define RCWL_PIN PIN_PA4

#define LORA_CS PIN_PB3
#define LORA_RST -1
#define LORA_DIO0 -1

SX1276 radio;

#define MLX90640_ADDR 0x33
#define MLX90640_RAM_START 0x0400
#define MLX90640_NUM_PIXELS 768
#define MLX90640_CHUNK 16
#define IR_ROWS 3
#define IR_COLS 4
#define IR_BLOCKS (IR_ROWS * IR_COLS)
#define IR_EMA_SHIFT 6
#define IR_DELTA_THRESHOLD 25
#define IR_WARMUP_FRAMES 5

int16_t irBaseline[IR_BLOCKS];
uint8_t irWarmup = 0;

char nodeID[9];
const char hexChars[] = "0123456789ABCDEF";

void getNodeID() {
  uint8_t raw[4] = {SIGROW.SERNUM0, SIGROW.SERNUM1, SIGROW.SERNUM2, SIGROW.SERNUM3};
  for (uint8_t i = 0; i < 4; i++) {
    nodeID[i * 2] = hexChars[raw[i] >> 4];
    nodeID[i * 2 + 1] = hexChars[raw[i] & 0x0F];
  }
  nodeID[8] = '\0';
}

bool mlxReadAndDetect() {
  int32_t blockSum[IR_BLOCKS] = {0};
  uint8_t blockCount[IR_BLOCKS] = {0};
  uint16_t addr = MLX90640_RAM_START;

  for (uint16_t p = 0; p < MLX90640_NUM_PIXELS; p += MLX90640_CHUNK) {
    Wire.beginTransmission(MLX90640_ADDR);
    Wire.write(addr >> 8);
    Wire.write(addr & 0xFF);
    Wire.endTransmission(false);
    Wire.requestFrom((int)MLX90640_ADDR, (int)(MLX90640_CHUNK * 2));
    for (uint8_t i = 0; i < MLX90640_CHUNK; i++) {
      uint16_t v = (Wire.read() << 8) | Wire.read();
      uint16_t pixelIdx = p + i;
      uint8_t col = ((pixelIdx % 32) * IR_COLS) / 32;
      uint8_t row = ((pixelIdx / 32) * IR_ROWS) / 24;
      uint8_t b = row * IR_COLS + col;
      blockSum[b] += v;
      blockCount[b]++;
    }
    addr += MLX90640_CHUNK;
  }

  bool detected = false;
  for (uint8_t b = 0; b < IR_BLOCKS; b++) {
    int16_t avg = blockSum[b] / blockCount[b];
    if (irWarmup < IR_WARMUP_FRAMES) {
      irBaseline[b] = avg;
    } else {
      int16_t d = avg - irBaseline[b];
      irBaseline[b] += d >> IR_EMA_SHIFT;
      if (d > IR_DELTA_THRESHOLD) detected = true;
    }
  }
  if (irWarmup < IR_WARMUP_FRAMES) irWarmup++;

  return detected;
}

char* appendStr(char* p, const char* s) {
  while (*s) *p++ = *s++;
  return p;
}

char* appendInt(char* p, int16_t v) {
  itoa(v, p, 10);
  return p + strlen(p);
}

void setup() {
  Wire.swap(1);
  pinMode(RCWL_PIN, INPUT);
  radar.begin(Serial);

  while (!adxl345.init()) {
    delay(2000);
  }

  getNodeID();

  if (radio.begin(915000000L, LORA_CS, LORA_RST, LORA_DIO0) != SX1276_ERR_NONE) {
    while (true);
  }
  radio.setSpreadingFactor(SX1276_SF_9);
}

void loop() {
  xyzFloat g;
  adxl345.getGValues(&g);

  int16_t gx100 = (int16_t)(g.x * 100);
  int16_t gy100 = (int16_t)(g.y * 100);
  int16_t gz100 = (int16_t)(g.z * 100);

  bool motion = digitalRead(RCWL_PIN);

  radar.read();
  bool presence = radar.presenceDetected();
  uint16_t targetDistance = radar.movingTargetDistance();

  bool irHuman = mlxReadAndDetect();
  bool humanDetected = irHuman || presence || motion;

  char payload[100];
  char* p = payload;
  p = appendStr(p, "ID:");
  p = appendStr(p, nodeID);
  p = appendStr(p, ",X:");
  p = appendInt(p, gx100);
  p = appendStr(p, ",Y:");
  p = appendInt(p, gy100);
  p = appendStr(p, ",Z:");
  p = appendInt(p, gz100);
  p = appendStr(p, ",M:");
  *p++ = motion ? '1' : '0';
  p = appendStr(p, ",P:");
  *p++ = presence ? '1' : '0';
  p = appendStr(p, ",D:");
  p = appendInt(p, (int16_t)targetDistance);
  p = appendStr(p, ",H:");
  *p++ = humanDetected ? '1' : '0';
  *p = '\0';

  radio.transmit((uint8_t*)payload, strlen(payload));

  delay(2000);
}