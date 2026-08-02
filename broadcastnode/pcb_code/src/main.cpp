#include <Arduino.h>
#include <SX1276.h>

#define LORA_CS PIN_PA4
#define LORA_RST PIN_PA6
#define LORA_DIO0 PIN_PA5

SX1276 radio;

char* appendStr(char* p, const char* s) {
  while (*s) *p++ = *s++;
  return p;
}

char* appendInt(char* p, int32_t v) {
  itoa(v, p, 10);
  return p + strlen(p);
}

void setup() {
  Serial.begin(115200);

  int16_t state = radio.begin(915000000L, LORA_CS, LORA_RST, LORA_DIO0);
  if (state != SX1276_ERR_NONE) {
    while (true);
  }
  radio.setSpreadingFactor(SX1276_SF_9);
}

void loop() {
  uint8_t buf[128];
  int16_t len = radio.receive(buf, sizeof(buf));

  if (len > 0) {
    int16_t rssi = radio.getRSSI();
    int8_t snr = radio.getSNR();

    char line[200];
    char* p = line;
    p = appendStr(p, "RSSI:");
    p = appendInt(p, rssi);
    p = appendStr(p, ",SNR:");
    p = appendInt(p, snr / 4);
    p = appendStr(p, ",LEN:");
    p = appendInt(p, len);
    p = appendStr(p, ",DATA:");
    for (int16_t i = 0; i < len; i++) {
      char c = (char)buf[i];
      *p++ = (c == '\n' || c == '\r') ? '?' : c;
    }
    *p = '\0';

    Serial.println(line);
  }
}