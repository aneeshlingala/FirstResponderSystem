#include <Arduino.h>
#include <Bosch_BME280_Arduino.h>
#include <ADXL345_WE.h>
#include "Zanshin_BME680.h"
#include <RadioLib.h>
#include <WiFi.h> 

BME680_Class BME680;

#define ADXL345_I2C 0x53
ADXL345_WE adxl345 = ADXL345_WE(ADXL345_I2C);

BME::Bosch_BME280 bme280{BME280_I2C_ADDR_PRIM, 249.67F, true};

SX1276 radio = new Module(5, 26, 14, RADIOLIB_NC);

String nodeID = "";

String getNodeID() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char idBuf[8];
  sprintf(idBuf, "%02X%02X", mac[4], mac[5]); 
  return "ENV-" + String(idBuf);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);

  Serial.println("Looking for BME680 sensor");
  while (!BME680.begin(I2C_STANDARD_MODE, 0x77)) {
    Serial.println("Couldn't find BME680 sensor");
    delay(2000);
  }
  Serial.println("BME680 sensor found");

  Serial.println("Looking for ADXL345 sensor");
  while (!adxl345.init()) {
    Serial.println("ADXL345 not found");
    delay(2000);
  }
  Serial.println("ADXL345 sensor found");

  Serial.println("Looking for BME280 sensor");
  while (bme280.begin() != 0) {
    Serial.println("Couldn't find BME280 sensor");
    delay(2000);
  }
  Serial.println("BME280 sensor found");

  Serial.println("Initializing LoRa radio");
  int state = radio.begin(915.0);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("LoRa radio initialize failed, code: ");
    Serial.println(state);
    while (true);
  }
  Serial.println("LoRa radio initialized");
}

void loop() {
  int32_t temp, humidity, pressure, gas;
  BME680.getSensorData(temp, humidity, pressure, gas);

  xyzFloat g;
  adxl345.getGValues(&g);

  float bmeTemp = bme280.getTemperature();
  float bmePressure = bme280.getPressure();
  float bmeHumidity = bme280.getHumidity();

  String info = String("Node ID:") + getNodeID() +
                    ",Temp:" + bmeTemp +
                    ",Pressure:" + bmePressure +
                    ",Humidity:" + bmeHumidity +
                    ",X gyro:" + g.x +
                    ",Y gyro:" + g.y +
                    ",Z gyro:" + g.z +
                    ",Gas temp:" + (temp / 100.0) +
                    ",VOC:" + gas;

  int state = radio.transmit(info);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("Sent successfully");
  } else {
    Serial.print("Send failed, code: ");
    Serial.println(state);
  }

  delay(2000);
}
 