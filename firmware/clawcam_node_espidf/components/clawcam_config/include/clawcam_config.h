#pragma once

/*
 * clawcam_config — NVS-backed persistent node configuration.
 *
 * Configuration survives deep sleep and power cycles via ESP32 NVS flash.
 * Values are loaded once on boot; apply_config_patch commands write new
 * values to NVS so they persist across subsequent wake cycles.
 *
 * Keys are intentionally short (≤ 15 chars) to satisfy NVS key limits.
 */

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Maximum string length for NVS string values (including null terminator) */
#define CLAWCAM_CONFIG_STR_MAX 64

typedef struct {
    char deployment_id[CLAWCAM_CONFIG_STR_MAX];
    char site_name[CLAWCAM_CONFIG_STR_MAX];
    uint32_t capture_interval_s;     /* timer-wake interval between forced captures */
    uint32_t low_battery_sleep_s;    /* extended sleep duration when battery is low */
    float low_battery_threshold_v;   /* voltage below which low-battery mode activates */
    uint8_t motion_sensitivity;      /* 0 = off, 1 = low, 2 = medium, 3 = high */
    bool gateway_upload_enabled;
} clawcam_config_t;

/* Load config from NVS; fills defaults for any missing keys */
esp_err_t clawcam_config_load(clawcam_config_t *config);

/* Persist the full config struct to NVS */
esp_err_t clawcam_config_save(const clawcam_config_t *config);

/* Apply a JSON patch object to config (validates and writes to NVS).
 * patch_json must be a flat JSON object: {"key": value, ...}
 * Returns ESP_ERR_INVALID_ARG if any key is unknown or value is invalid. */
esp_err_t clawcam_config_apply_patch_json(const char *patch_json, clawcam_config_t *config);

/* Reset all config keys to factory defaults in NVS */
esp_err_t clawcam_config_reset(clawcam_config_t *config);

/* Fill *config with factory default values (does not write NVS) */
void clawcam_config_defaults(clawcam_config_t *config);

#ifdef __cplusplus
}
#endif
