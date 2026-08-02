#include "MLX90640_I2C_Driver.h"
#include <Wire.h>

void MLX90640_I2CInit() {
  Wire.begin();
}

int MLX90640_I2CRead(uint8_t slaveAddr, uint16_t startAddress, uint16_t nMemAddressRead, uint16_t *data) {
  Wire.beginTransmission(slaveAddr);
  Wire.write(startAddress >> 8);
  Wire.write(startAddress & 0xFF);
  if (Wire.endTransmission(false) != 0) return -1;

  uint16_t bytesToRead = nMemAddressRead * 2;
  Wire.requestFrom((int)slaveAddr, (int)bytesToRead);

  for (uint16_t i = 0; i < nMemAddressRead; i++) {
    uint16_t hi = Wire.read();
    uint16_t lo = Wire.read();
    data[i] = (hi << 8) | lo;
  }
  return 0;
}

int MLX90640_I2CWrite(uint8_t slaveAddr, uint16_t writeAddress, uint16_t data) {
  Wire.beginTransmission(slaveAddr);
  Wire.write(writeAddress >> 8);
  Wire.write(writeAddress & 0xFF);
  Wire.write(data >> 8);
  Wire.write(data & 0xFF);
  return Wire.endTransmission() == 0 ? 0 : -1;
}

void MLX90640_I2CFreqSet(int freq) {
  Wire.setClock(freq * 1000UL);
}