/*
 * ClawCam Node firmware scaffold.
 *
 * This file intentionally starts minimal. Hardware capture, storage, power, and
 * ESP-Claw capability integration will be added component by component.
 */

#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "clawcam_node";

void app_main(void)
{
    ESP_LOGI(TAG, "ClawCam node firmware scaffold starting");
    ESP_LOGI(TAG, "Next milestones: config, camera, storage, motion, event publication, deep sleep");

    while (true) {
        ESP_LOGI(TAG, "ClawCam node scaffold heartbeat");
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}
