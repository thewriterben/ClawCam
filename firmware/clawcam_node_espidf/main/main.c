/*
 * ClawCam Node firmware scaffold.
 *
 * This file wires the deterministic component boundaries that will receive the
 * WildCAM camera-trap behavior port. The current hardware-ready path is a gated
 * ESP32-S3-EYE camera smoke test that can capture one JPEG, optionally persist
 * it to SD/FATFS storage, write metadata, and release the framebuffer safely.
 */

#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "clawcam_camera.h"
#include "clawcam_events.h"
#include "clawcam_gateway_client.h"
#include "clawcam_motion.h"
#include "clawcam_power.h"
#include "clawcam_storage.h"

#ifndef CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT
#define CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT 0
#endif

#ifndef CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT
#define CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT 1
#endif

#ifndef CONFIG_CLAWCAM_STORAGE_PERSIST_SMOKE_TEST_CAPTURE
#define CONFIG_CLAWCAM_STORAGE_PERSIST_SMOKE_TEST_CAPTURE 0
#endif

#ifndef CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
#define CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED 0
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
    clawcam_storage_config_t storage_config;
    ESP_ERROR_CHECK(clawcam_storage_default_esp32_s3_eye_config(&storage_config));
    clawcam_camera_config_t camera_config;
    ESP_ERROR_CHECK(clawcam_camera_default_esp32_s3_eye_config(&camera_config));
    const clawcam_motion_config_t motion_config = {
        .pir_gpio = 13,
        .debounce_ms = 2000,
        .wake_from_deep_sleep = true,
    };

    ESP_ERROR_CHECK(clawcam_power_init(&power_config));
    esp_err_t storage_err = clawcam_storage_init(&storage_config);
    if (storage_err != ESP_OK) {
        ESP_LOGW(TAG, "storage initialization did not complete: %s; capture can still run without persistence", esp_err_to_name(storage_err));
    }
    ESP_ERROR_CHECK(clawcam_camera_init(&camera_config));
    ESP_ERROR_CHECK(clawcam_motion_init(&motion_config));
}

static void persist_smoke_test_capture(const clawcam_camera_capture_t *capture)
{
#if CONFIG_CLAWCAM_STORAGE_PERSIST_SMOKE_TEST_CAPTURE
    if (capture == NULL || capture->data == NULL || capture->length == 0) {
        ESP_LOGW(TAG, "smoke-test capture has no media bytes to persist");
        return;
    }

    char media_id[64];
    snprintf(media_id, sizeof(media_id), "smoke-%lld", (long long)esp_timer_get_time());

    const clawcam_storage_media_t media = {
        .data = capture->data,
        .length = capture->length,
        .media_id = media_id,
        .extension = "jpg",
    };
    char media_path[192];
    esp_err_t err = clawcam_storage_save_media(&media, media_path, sizeof(media_path));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "smoke-test media was not persisted: %s", esp_err_to_name(err));
        return;
    }

    char metadata[384];
    snprintf(metadata,
             sizeof(metadata),
             "{\"schema_version\":\"clawcam.event.v1\",\"event_type\":\"camera_smoke_test\",\"media_id\":\"%s\",\"media_path\":\"%s\",\"bytes\":%u,\"width\":%lu,\"height\":%lu,\"mime_type\":\"%s\",\"source\":\"esp32-s3-eye-v2.2\"}\n",
             media_id,
             media_path,
             (unsigned)capture->length,
             (unsigned long)capture->width,
             (unsigned long)capture->height,
             capture->mime_type ? capture->mime_type : "image/jpeg");

    err = clawcam_storage_save_metadata(media_path, metadata);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "smoke-test metadata was not persisted: %s", esp_err_to_name(err));
        return;
    }

    char event_id[80];
    snprintf(event_id, sizeof(event_id), "evt-%s", media_id);
    const clawcam_event_capture_t event = {
        .event_id = event_id,
        .event_type = "capture",
        .device_id = "esp32-s3-eye-v2.2-bench-node",
        .deployment_id = "hardware-bench",
        .timestamp = "1970-01-01T00:00:00Z",
        .time_source = "unknown",
        .media_id = media_id,
        .media_path = media_path,
        .mime_type = capture->mime_type ? capture->mime_type : "image/jpeg",
        .size_bytes = capture->length,
        .width = capture->width,
        .height = capture->height,
        .trigger = "camera_smoke_test",
        .board_profile = "esp32-s3-eye-v2.2",
        .capture_profile = "smoke_test",
    };
    char event_json[1024];
    err = clawcam_event_build_capture_json(&event, event_json, sizeof(event_json));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "smoke-test event JSON was not generated: %s", esp_err_to_name(err));
        return;
    }
    char event_path[192];
    err = clawcam_storage_save_event_json(event_id, event_json, event_path, sizeof(event_path));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "smoke-test event artifact was not persisted: %s", esp_err_to_name(err));
        return;
    }

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
    clawcam_gateway_client_config_t gateway_config;
    ESP_ERROR_CHECK(clawcam_gateway_client_default_config(&gateway_config));
    const char *device_json = "{\"device_id\":\"esp32-s3-eye-v2.2-bench-node\",\"device_type\":\"node\",\"name\":\"ESP32-S3-EYE Bench Node\",\"hardware\":{\"board\":\"esp32-s3-eye-v2.2\",\"mcu\":\"esp32-s3\",\"camera\":\"ov2640\",\"storage\":\"sd/fatfs\"},\"firmware\":{\"name\":\"clawcam-node-espidf\",\"version\":\"0.1.0\",\"source\":\"bench-firmware\"},\"deployment_id\":\"hardware-bench\",\"capabilities\":[\"camera\",\"sd_fatfs\",\"event_artifact\",\"gateway_upload\"],\"status\":\"active\",\"created_at\":\"1970-01-01T00:00:00Z\",\"last_seen_at\":\"1970-01-01T00:00:00Z\",\"metadata\":{\"firmware_generated\":true}}";
    err = clawcam_gateway_client_register_device(&gateway_config, device_json);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "gateway device registration failed; SD event remains source of truth: %s", esp_err_to_name(err));
    } else {
        err = clawcam_gateway_client_upload_event(&gateway_config, event_json);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "gateway event upload failed; SD event remains source of truth: %s", esp_err_to_name(err));
        }
    }
#else
    ESP_LOGI(TAG, "gateway upload disabled; SD event remains offline source of truth");
#endif

    ESP_LOGI(TAG, "smoke-test capture persisted: media=%s event=%s", media_path, event_path);
#else
    (void)capture;
    ESP_LOGI(TAG, "smoke-test storage persistence disabled; enable CONFIG_CLAWCAM_STORAGE_PERSIST_SMOKE_TEST_CAPTURE for bench validation");
#endif
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
            persist_smoke_test_capture(&capture);
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
            ESP_LOGI(TAG, "storage: mounted=%s total=%llu free=%llu media_count=%lu",
                     storage_health.mounted ? "true" : "false",
                     (unsigned long long)storage_health.total_bytes,
                     (unsigned long long)storage_health.free_bytes,
                     (unsigned long)storage_health.media_count);
        }
        if (clawcam_motion_get_event(&motion_event) == ESP_OK) {
            ESP_LOGI(TAG, "motion scaffold: detected=%s source=%s",
                     motion_event.motion_detected ? "true" : "false",
                     motion_event.trigger_source);
        }

        ESP_LOGI(TAG, "Next firmware port: PIR interrupt, battery ADC, deep sleep, gateway event queue");
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}
