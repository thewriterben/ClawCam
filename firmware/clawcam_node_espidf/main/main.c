/*
 * ClawCam Node firmware scaffold.
 *
 * This file wires the deterministic component boundaries that will receive the
 * WildCAM camera-trap behavior port. The first hardware-ready path is a gated
 * ESP32-S3-EYE camera smoke test that initializes the camera, captures one JPEG,
 * logs frame details, and releases the framebuffer safely.
 */

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_log.h"

#include "clawcam_camera.h"
#include "clawcam_motion.h"
#include "clawcam_power.h"
#include "clawcam_storage.h"

#ifndef CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT
#define CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT 0
#endif

#ifndef CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT
#define CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT 1
#endif

static const char *TAG = "clawcam_node";

static void init_components(void)
{
    const clawcam_power_config_t power_config = {
        .battery_adc_channel = 0,
        .pir_wake_gpio = 13,
        .battery_capacity_mah = 6600.0f,
        .low_battery_threshold_v = 3.55f,
        .energy_tracking_enabled = true,
    };
    const clawcam_storage_config_t storage_config = {
        .mount_point = "/sdcard",
        .media_dir = "media",
        .metadata_dir = "metadata",
        .min_free_bytes = 128 * 1024 * 1024,
        .auto_cleanup_enabled = false,
    };
    clawcam_camera_config_t camera_config;
    ESP_ERROR_CHECK(clawcam_camera_default_esp32_s3_eye_config(&camera_config));
    const clawcam_motion_config_t motion_config = {
        .pir_gpio = 13,
        .debounce_ms = 2000,
        .wake_from_deep_sleep = true,
    };

    ESP_ERROR_CHECK(clawcam_power_init(&power_config));
    ESP_ERROR_CHECK(clawcam_storage_init(&storage_config));
    ESP_ERROR_CHECK(clawcam_camera_init(&camera_config));
    ESP_ERROR_CHECK(clawcam_motion_init(&motion_config));
}

static void run_camera_smoke_test(void)
{
#if CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT
    ESP_LOGI(TAG, "camera smoke test enabled; attempting %d capture(s)", CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT);
    for (int attempt = 1; attempt <= CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT; attempt++) {
        clawcam_camera_capture_t capture;
        esp_err_t err = clawcam_camera_capture(&capture);
        if (err == ESP_OK) {
            ESP_LOGI(TAG,
                     "camera smoke test passed on attempt %d: bytes=%u width=%lu height=%lu mime=%s",
                     attempt,
                     (unsigned)capture.length,
                     (unsigned long)capture.width,
                     (unsigned long)capture.height,
                     capture.mime_type ? capture.mime_type : "unknown");
            clawcam_camera_release(&capture);
            return;
        }
        ESP_LOGW(TAG, "camera smoke test attempt %d failed: %s", attempt, esp_err_to_name(err));
        clawcam_camera_release(&capture);
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    ESP_LOGE(TAG, "camera smoke test failed after %d attempt(s)", CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT);
#else
    ESP_LOGI(TAG, "camera smoke test disabled; enable CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT for bench validation");
#endif
}

void app_main(void)
{
    ESP_LOGI(TAG, "ClawCam node firmware scaffold starting");
    init_components();
    run_camera_smoke_test();

    while (true) {
        clawcam_power_state_t power_state;
        clawcam_storage_health_t storage_health;
        clawcam_motion_event_t motion_event;

        if (clawcam_power_get_state(&power_state) == ESP_OK) {
            ESP_LOGI(TAG, "power scaffold: battery=%.2fV percentage=%d low=%s",
                     power_state.battery_voltage,
                     power_state.battery_percentage,
                     power_state.low_battery ? "true" : "false");
        }
        if (clawcam_storage_get_health(&storage_health) == ESP_OK) {
            ESP_LOGI(TAG, "storage scaffold: mounted=%s free=%llu",
                     storage_health.mounted ? "true" : "false",
                     (unsigned long long)storage_health.free_bytes);
        }
        if (clawcam_motion_get_event(&motion_event) == ESP_OK) {
            ESP_LOGI(TAG, "motion scaffold: detected=%s source=%s",
                     motion_event.motion_detected ? "true" : "false",
                     motion_event.trigger_source);
        }

        ESP_LOGI(TAG, "Next firmware port: SD/FATFS writes, PIR interrupt, battery ADC, deep sleep");
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}
