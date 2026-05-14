/*
 * ClawCam Node firmware — deterministic PIR → capture → deep-sleep loop.
 *
 * Boot flow:
 *   1. Load NVS config (defaults if first boot).
 *   2. Init all components.
 *   3. Check wake reason (PIR EXT0, timer, or power-on).
 *   4. Skip capture on low battery; sleep longer.
 *   5. Run capture cycle: image → metadata → event JSON → SD persist.
 *   6. Upload event via MQTT (publish event + receive any commands) OR HTTP poll.
 *   7. Configure PIR + timer wake sources and enter deep sleep.
 *
 * On first power-on, the optional camera smoke test runs (Kconfig-gated) before
 * the device enters its first sleep interval.
 */

#include <stdio.h>
#include <time.h>
#include <sys/time.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_timer.h"

#include "clawcam_camera.h"
#include "clawcam_capabilities.h"
#include "clawcam_command_client.h"
#include "clawcam_config.h"
#include "clawcam_events.h"
#include "clawcam_gateway_client.h"
#include "clawcam_motion.h"
#include "clawcam_mqtt.h"
#include "clawcam_ota.h"
#include "clawcam_power.h"
#include "clawcam_storage.h"

/* ── Kconfig defaults ───────────────────────────────────────────────────── */

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

/* ── Field parameters ───────────────────────────────────────────────────── */

#define CLAWCAM_PIR_GPIO               13
#define CLAWCAM_DEVICE_ID              "esp32-s3-eye-v2.2-node"
#define CLAWCAM_BOARD_PROFILE          "esp32-s3-eye-v2.2"

/* Minimum unix epoch considered a valid wall-clock time (2020-01-01) */
#define CLAWCAM_MIN_VALID_EPOCH        1577836800LL

static const char *TAG = "clawcam_node";

/* NVS-backed config — loaded at boot, used throughout the wake cycle */
static clawcam_config_t g_config;

/* ── Helpers ────────────────────────────────────────────────────────────── */

/*
 * Fill buf with an ISO 8601 UTC timestamp if the system clock looks set,
 * otherwise fill with the epoch sentinel. Sets *time_source to "rtc" or
 * "unknown" so the gateway can interpret confidence of the timestamp.
 */
static void get_iso8601_timestamp(char *buf, size_t len, const char **time_source_out)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    if (tv.tv_sec > CLAWCAM_MIN_VALID_EPOCH) {
        struct tm t;
        gmtime_r(&tv.tv_sec, &t);
        strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &t);
        *time_source_out = "rtc";
    } else {
        snprintf(buf, len, "1970-01-01T00:00:00Z");
        *time_source_out = "unknown";
    }
}

/* ── Component init ─────────────────────────────────────────────────────── */

static void init_components(void)
{
    const clawcam_power_config_t power_config = {
        .battery_adc_channel    = 0,
        .pir_wake_gpio          = CLAWCAM_PIR_GPIO,
        .battery_capacity_mah   = 6600.0f,
        .low_battery_threshold_v = g_config.low_battery_threshold_v,
        .energy_tracking_enabled = true,
    };
    clawcam_storage_config_t storage_config;
    ESP_ERROR_CHECK(clawcam_storage_default_esp32_s3_eye_config(&storage_config));
    clawcam_camera_config_t camera_config;
    ESP_ERROR_CHECK(clawcam_camera_default_esp32_s3_eye_config(&camera_config));
    const clawcam_motion_config_t motion_config = {
        .pir_gpio          = CLAWCAM_PIR_GPIO,
        .debounce_ms       = 2000,
        .wake_from_deep_sleep = true,
    };

    ESP_ERROR_CHECK(clawcam_power_init(&power_config));
    esp_err_t storage_err = clawcam_storage_init(&storage_config);
    if (storage_err != ESP_OK) {
        ESP_LOGW(TAG, "storage init incomplete (%s); capture continues without SD persistence",
                 esp_err_to_name(storage_err));
    }
    ESP_ERROR_CHECK(clawcam_camera_init(&camera_config));
    /* Motion init reads deep-sleep wake cause — must run after power init */
    ESP_ERROR_CHECK(clawcam_motion_init(&motion_config));
}

/* ── Capture persistence (shared by smoke-test and live capture) ─────────── */

static void persist_capture(
    const clawcam_camera_capture_t *capture,
    const char *event_id,
    const char *media_id,
    const char *timestamp,
    const char *time_source,
    const char *trigger)
{
    if (capture == NULL || capture->data == NULL || capture->length == 0) {
        ESP_LOGW(TAG, "no media bytes to persist for event %s", event_id);
        return;
    }

    const clawcam_storage_media_t media = {
        .data     = capture->data,
        .length   = capture->length,
        .media_id = media_id,
        .extension = "jpg",
    };
    char media_path[192];
    esp_err_t err = clawcam_storage_save_media(&media, media_path, sizeof(media_path));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "media not persisted (%s); event continues without SD artifact",
                 esp_err_to_name(err));
        return;
    }

    char metadata[512];
    snprintf(metadata, sizeof(metadata),
             "{\"schema_version\":\"clawcam.event.v1\","
             "\"event_id\":\"%s\","
             "\"event_type\":\"capture\","
             "\"trigger\":\"%s\","
             "\"media_id\":\"%s\","
             "\"media_path\":\"%s\","
             "\"bytes\":%u,"
             "\"width\":%lu,"
             "\"height\":%lu,"
             "\"mime_type\":\"%s\","
             "\"timestamp\":\"%s\","
             "\"time_source\":\"%s\","
             "\"source\":\"%s\"}\n",
             event_id, trigger, media_id, media_path,
             (unsigned)capture->length,
             (unsigned long)capture->width,
             (unsigned long)capture->height,
             capture->mime_type ? capture->mime_type : "image/jpeg",
             timestamp, time_source,
             CLAWCAM_BOARD_PROFILE);

    err = clawcam_storage_save_metadata(media_path, metadata);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "metadata not persisted: %s", esp_err_to_name(err));
    }

    const clawcam_event_capture_t event = {
        .event_id       = event_id,
        .event_type     = "capture",
        .device_id      = CLAWCAM_DEVICE_ID,
        .deployment_id  = g_config.deployment_id,
        .timestamp      = timestamp,
        .time_source    = time_source,
        .media_id       = media_id,
        .media_path     = media_path,
        .mime_type      = capture->mime_type ? capture->mime_type : "image/jpeg",
        .size_bytes     = capture->length,
        .width          = capture->width,
        .height         = capture->height,
        .trigger        = trigger,
        .board_profile  = CLAWCAM_BOARD_PROFILE,
        .capture_profile = "field",
    };
    char event_json[1024];
    err = clawcam_event_build_capture_json(&event, event_json, sizeof(event_json));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "event JSON build failed: %s", esp_err_to_name(err));
        return;
    }
    char event_path[192];
    err = clawcam_storage_save_event_json(event_id, event_json, event_path, sizeof(event_path));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "event artifact not persisted: %s", esp_err_to_name(err));
        return;
    }

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
    /* Try MQTT first (real-time, also receives pending commands).
     * Fall back to HTTP REST if MQTT is unavailable or times out. */
    clawcam_mqtt_config_t mqtt_cfg;
    clawcam_mqtt_default_config(&mqtt_cfg, CLAWCAM_DEVICE_ID);
    esp_err_t mqtt_err = clawcam_mqtt_publish_event(&mqtt_cfg, event_json, NULL, &g_config);
    bool uploaded_via_mqtt = (mqtt_err == ESP_OK);

    if (!uploaded_via_mqtt) {
        /* MQTT unavailable — fall back to HTTP REST */
        clawcam_gateway_client_config_t gateway_config;
        ESP_ERROR_CHECK(clawcam_gateway_client_default_config(&gateway_config));
        char device_json[768];
        snprintf(device_json, sizeof(device_json),
            "{\"device_id\":\"" CLAWCAM_DEVICE_ID "\","
            "\"device_type\":\"node\","
            "\"name\":\"ESP32-S3-EYE Field Node\","
            "\"hardware\":{\"board\":\"esp32-s3-eye-v2.2\",\"mcu\":\"esp32-s3\",\"camera\":\"ov2640\",\"storage\":\"sd/fatfs\"},"
            "\"firmware\":{\"name\":\"clawcam-node-espidf\",\"version\":\"0.1.0\",\"source\":\"field-firmware\"},"
            "\"deployment_id\":\"%s\","
            "\"capabilities\":[" CLAWCAM_ESP32_S3_EYE_CAPABILITIES "],"
            "\"status\":\"active\","
            "\"created_at\":\"1970-01-01T00:00:00Z\","
            "\"last_seen_at\":\"1970-01-01T00:00:00Z\","
            "\"metadata\":{\"firmware_generated\":true}}",
            g_config.deployment_id);

        esp_err_t reg_err = clawcam_gateway_client_register_device(&gateway_config, device_json);
        if (reg_err != ESP_OK) {
            ESP_LOGW(TAG, "HTTP device registration failed (%s); SD remains source of truth",
                     esp_err_to_name(reg_err));
        } else {
            esp_err_t up_err = clawcam_gateway_client_upload_event(&gateway_config, event_json);
            if (up_err != ESP_OK) {
                ESP_LOGW(TAG, "HTTP event upload failed (%s); SD remains source of truth",
                         esp_err_to_name(up_err));
            } else {
                clawcam_power_record_transmission();
            }
        }
    } else {
        clawcam_power_record_transmission();
    }
#else
    ESP_LOGI(TAG, "gateway upload disabled; SD event is source of truth");
#endif

    clawcam_power_record_capture();
    ESP_LOGI(TAG, "capture persisted: media=%s event=%s trigger=%s", media_path, event_path, trigger);
}

/* ── Camera smoke test (bench validation, Kconfig-gated) ────────────────── */

static void run_camera_smoke_test(void)
{
#if CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT
    ESP_LOGI(TAG, "camera smoke test: attempting %d capture(s)",
             CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT);
    for (int attempt = 1; attempt <= CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT; attempt++) {
        clawcam_camera_capture_t capture;
        esp_err_t err = clawcam_camera_capture(&capture);
        if (err == ESP_OK) {
            ESP_LOGI(TAG,
                     "smoke test passed (attempt %d): bytes=%u width=%lu height=%lu mime=%s",
                     attempt,
                     (unsigned)capture.length,
                     (unsigned long)capture.width,
                     (unsigned long)capture.height,
                     capture.mime_type ? capture.mime_type : "unknown");
#if CONFIG_CLAWCAM_STORAGE_PERSIST_SMOKE_TEST_CAPTURE
            char smoke_id[64];
            snprintf(smoke_id, sizeof(smoke_id), "smoke-%lld", (long long)esp_timer_get_time());
            char evt_id[80];
            snprintf(evt_id, sizeof(evt_id), "evt-%s", smoke_id);
            persist_capture(&capture, evt_id, smoke_id,
                            "1970-01-01T00:00:00Z", "unknown", "camera_smoke_test");
#endif
            clawcam_camera_release(&capture);
            return;
        }
        ESP_LOGW(TAG, "smoke test attempt %d failed: %s", attempt, esp_err_to_name(err));
        clawcam_camera_release(&capture);
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    ESP_LOGE(TAG, "camera smoke test failed after %d attempt(s)",
             CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT);
#else
    ESP_LOGI(TAG, "camera smoke test disabled (enable CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT)");
#endif
}

/* ── Deterministic capture cycle ────────────────────────────────────────── */

static void run_capture_cycle(const char *trigger)
{
    char timestamp[32];
    const char *time_source = "unknown";
    get_iso8601_timestamp(timestamp, sizeof(timestamp), &time_source);

    int64_t boot_us = esp_timer_get_time();
    char media_id[64];
    snprintf(media_id, sizeof(media_id), "cap-%lld", (long long)boot_us);
    char event_id[80];
    snprintf(event_id, sizeof(event_id), "evt-%s", media_id);

    ESP_LOGI(TAG, "capture cycle: trigger=%s ts=%s (%s)", trigger, timestamp, time_source);

    clawcam_camera_capture_t capture;
    esp_err_t err = clawcam_camera_capture(&capture);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "capture failed: %s; event not recorded", esp_err_to_name(err));
        clawcam_camera_release(&capture);
        return;
    }

    ESP_LOGI(TAG, "captured: bytes=%u width=%lu height=%lu",
             (unsigned)capture.length,
             (unsigned long)capture.width,
             (unsigned long)capture.height);

    persist_capture(&capture, event_id, media_id, timestamp, time_source, trigger);
    clawcam_camera_release(&capture);
}

/* ── Sleep configuration ────────────────────────────────────────────────── */

static void enter_field_sleep(uint64_t sleep_seconds)
{
    /* PIR EXT0 is the primary wake source; timer is the fallback */
    clawcam_power_configure_wake_on_motion(CLAWCAM_PIR_GPIO);
    clawcam_power_enter_deep_sleep(sleep_seconds);
    /* never reached */
}

/* ── Command client callbacks ───────────────────────────────────────────── */

static void on_command_capture(const char *command_id, const char *reason)
{
    ESP_LOGI(TAG, "executing gateway capture command: id=%s reason=%s", command_id, reason);
    run_capture_cycle(reason[0] != '\0' ? reason : "command");
}

static esp_err_t on_command_ota(
    const char *base_url,
    const char *firmware_path,
    const char *sha256,
    const char *version)
{
    ESP_LOGI(TAG, "executing OTA command: version=%s", version ? version : "?");
    return clawcam_ota_update(base_url, firmware_path, sha256, version);
}

/* ── Entry point ────────────────────────────────────────────────────────── */

void app_main(void)
{
    ESP_LOGI(TAG, "ClawCam node firmware starting");

    /* Load NVS config first — provides sleep intervals and deployment metadata */
    esp_err_t cfg_err = clawcam_config_load(&g_config);
    if (cfg_err != ESP_OK) {
        ESP_LOGW(TAG, "config load failed (%s); using factory defaults", esp_err_to_name(cfg_err));
        clawcam_config_defaults(&g_config);
    }
    ESP_LOGI(TAG, "config: deploy=%s site=%s interval=%lus lo_batt=%lus",
             g_config.deployment_id, g_config.site_name,
             (unsigned long)g_config.capture_interval_s,
             (unsigned long)g_config.low_battery_sleep_s);

    init_components();

    /* Smoke test runs once on bench / first power-on to validate hardware */
    esp_sleep_wakeup_cause_t wake_cause = esp_sleep_get_wakeup_cause();
    bool first_boot = (wake_cause == ESP_SLEEP_WAKEUP_UNDEFINED);
    if (first_boot) {
        run_camera_smoke_test();
    }

    /* Read system state */
    clawcam_power_state_t power_state = {0};
    clawcam_power_get_state(&power_state);

    clawcam_storage_health_t storage_health = {0};
    clawcam_storage_get_health(&storage_health);

    clawcam_motion_event_t motion_event = {0};
    clawcam_motion_get_event(&motion_event);

    ESP_LOGI(TAG, "state: wake=%d battery=%.2fV(%d%%) low=%s storage_free=%lluMB pir=%s",
             (int)wake_cause,
             power_state.battery_voltage,
             power_state.battery_percentage,
             power_state.low_battery ? "true" : "false",
             (unsigned long long)(storage_health.free_bytes / (1024 * 1024)),
             motion_event.motion_detected ? "triggered" : "idle");

    /* Low battery: skip capture and sleep longer to conserve energy */
    if (power_state.low_battery) {
        ESP_LOGW(TAG, "low battery — skipping capture, sleeping %lus",
                 (unsigned long)g_config.low_battery_sleep_s);
        enter_field_sleep((uint64_t)g_config.low_battery_sleep_s);
        return;
    }

    /* Run capture on PIR trigger or on timer wake (periodic health check / interval shot) */
    if (motion_event.motion_detected) {
        run_capture_cycle("pir_motion");
    } else if (!first_boot) {
        run_capture_cycle("timer");
    }
    /* On first boot: smoke test already ran above; skip a redundant capture */

    /* Poll gateway command queue and execute any pending commands */
#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
    clawcam_gateway_client_config_t gw_cfg;
    if (clawcam_gateway_client_default_config(&gw_cfg) == ESP_OK) {
        const clawcam_command_client_config_t cmd_cfg = {
            .gateway_config       = &gw_cfg,
            .device_id            = CLAWCAM_DEVICE_ID,
            .node_config          = &g_config,
            .capture_cb           = on_command_capture,
            .ota_cb               = on_command_ota,
            .max_commands_per_wake = 5,
        };
        int handled = clawcam_command_client_poll(&cmd_cfg);
        if (handled > 0) {
            ESP_LOGI(TAG, "executed %d gateway command(s) this wake cycle", handled);
        }
    }
#endif

    enter_field_sleep((uint64_t)g_config.capture_interval_s);
}
