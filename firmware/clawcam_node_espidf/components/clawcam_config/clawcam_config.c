#include "clawcam_config.h"

#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char *TAG = "clawcam_config";
static const char *NVS_NAMESPACE = "clawcam_cfg";

/* ── Factory defaults ───────────────────────────────────────────────────── */

void clawcam_config_defaults(clawcam_config_t *config)
{
    memset(config, 0, sizeof(*config));
    strncpy(config->deployment_id, "unset", sizeof(config->deployment_id) - 1);
    strncpy(config->site_name,     "unset", sizeof(config->site_name) - 1);
    config->capture_interval_s    = 300;   /* 5-minute timer fallback */
    config->low_battery_sleep_s   = 1800;  /* 30-minute sleep when low battery */
    config->low_battery_threshold_v = 3.55f;
    config->motion_sensitivity    = 2;     /* medium */
    config->gateway_upload_enabled = false;
}

/* ── NVS helpers ────────────────────────────────────────────────────────── */

static esp_err_t open_nvs(nvs_handle_t *handle, nvs_open_mode_t mode)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS partition truncated; erasing and re-initialising");
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) {
        return err;
    }
    return nvs_open(NVS_NAMESPACE, mode, handle);
}

/* ── Load ───────────────────────────────────────────────────────────────── */

esp_err_t clawcam_config_load(clawcam_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    clawcam_config_defaults(config);

    nvs_handle_t h;
    esp_err_t err = open_nvs(&h, NVS_READONLY);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGI(TAG, "no config namespace found; using factory defaults");
        return ESP_OK;
    }
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "NVS open failed (%s); using factory defaults", esp_err_to_name(err));
        return ESP_OK;
    }

    size_t len;

    len = sizeof(config->deployment_id);
    nvs_get_str(h, "deploy_id", config->deployment_id, &len);

    len = sizeof(config->site_name);
    nvs_get_str(h, "site_name", config->site_name, &len);

    uint32_t u32;
    if (nvs_get_u32(h, "cap_interval_s", &u32) == ESP_OK) config->capture_interval_s = u32;
    if (nvs_get_u32(h, "lo_batt_slp_s",  &u32) == ESP_OK) config->low_battery_sleep_s = u32;

    int32_t i32;
    if (nvs_get_i32(h, "lo_batt_mv",  &i32) == ESP_OK) {
        config->low_battery_threshold_v = (float)i32 / 1000.0f;
    }

    uint8_t u8;
    if (nvs_get_u8(h, "motion_sens", &u8) == ESP_OK) config->motion_sensitivity = u8;
    if (nvs_get_u8(h, "gw_upload",   &u8) == ESP_OK) config->gateway_upload_enabled = (u8 != 0);

    nvs_close(h);
    ESP_LOGI(TAG, "config loaded: deploy=%s site=%s interval=%lus",
             config->deployment_id, config->site_name,
             (unsigned long)config->capture_interval_s);
    return ESP_OK;
}

/* ── Save ───────────────────────────────────────────────────────────────── */

esp_err_t clawcam_config_save(const clawcam_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t h;
    esp_err_t err = open_nvs(&h, NVS_READWRITE);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "NVS open for write failed: %s", esp_err_to_name(err));
        return err;
    }

    nvs_set_str(h, "deploy_id",    config->deployment_id);
    nvs_set_str(h, "site_name",    config->site_name);
    nvs_set_u32(h, "cap_interval_s", config->capture_interval_s);
    nvs_set_u32(h, "lo_batt_slp_s",  config->low_battery_sleep_s);
    nvs_set_i32(h, "lo_batt_mv",  (int32_t)(config->low_battery_threshold_v * 1000.0f));
    nvs_set_u8(h,  "motion_sens", config->motion_sensitivity);
    nvs_set_u8(h,  "gw_upload",   config->gateway_upload_enabled ? 1 : 0);

    err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "NVS commit failed: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "config saved to NVS");
    return ESP_OK;
}

/* ── Apply JSON patch ───────────────────────────────────────────────────── */

/*
 * Minimal JSON key-value scanner. Looks for "key": <value> pairs in a flat
 * JSON object. Does not handle nested objects or arrays in values.
 * Returns the start of the value string for a given key, or NULL.
 */
static const char *find_json_value(const char *json, const char *key, size_t *value_len)
{
    if (!json || !key) return NULL;
    char search[64];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char *p = strstr(json, search);
    if (!p) return NULL;
    p += strlen(search);
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (*p != ':') return NULL;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    /* Find end of value: stop at comma or closing brace, respecting quoted strings */
    const char *start = p;
    if (*p == '"') {
        p++;
        while (*p && *p != '"') {
            if (*p == '\\') p++;
            p++;
        }
        if (*p == '"') p++;
    } else {
        while (*p && *p != ',' && *p != '}' && *p != '\n') p++;
        while (p > start && (*(p-1) == ' ' || *(p-1) == '\t')) p--;
    }
    *value_len = (size_t)(p - start);
    return start;
}

esp_err_t clawcam_config_apply_patch_json(const char *patch_json, clawcam_config_t *config)
{
    if (patch_json == NULL || config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    bool changed = false;
    size_t vlen;
    const char *v;
    char buf[CLAWCAM_CONFIG_STR_MAX];

    v = find_json_value(patch_json, "deployment_id", &vlen);
    if (v && vlen > 0 && *v == '"') {
        size_t slen = vlen - 2 < sizeof(config->deployment_id) - 1
                      ? vlen - 2 : sizeof(config->deployment_id) - 1;
        memcpy(config->deployment_id, v + 1, slen);
        config->deployment_id[slen] = '\0';
        changed = true;
        ESP_LOGI(TAG, "patch: deployment_id=%s", config->deployment_id);
    }

    v = find_json_value(patch_json, "site_name", &vlen);
    if (v && vlen > 0 && *v == '"') {
        size_t slen = vlen - 2 < sizeof(config->site_name) - 1
                      ? vlen - 2 : sizeof(config->site_name) - 1;
        memcpy(config->site_name, v + 1, slen);
        config->site_name[slen] = '\0';
        changed = true;
        ESP_LOGI(TAG, "patch: site_name=%s", config->site_name);
    }

    v = find_json_value(patch_json, "capture_interval_seconds", &vlen);
    if (v && vlen > 0 && *v != '"') {
        memcpy(buf, v, vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1);
        buf[vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1] = '\0';
        long val = strtol(buf, NULL, 10);
        if (val >= 30 && val <= 86400) {
            config->capture_interval_s = (uint32_t)val;
            changed = true;
            ESP_LOGI(TAG, "patch: capture_interval_seconds=%lu", (unsigned long)config->capture_interval_s);
        } else {
            ESP_LOGW(TAG, "patch: capture_interval_seconds %ld out of range [30, 86400]; ignored", val);
        }
    }

    v = find_json_value(patch_json, "low_battery_sleep_seconds", &vlen);
    if (v && vlen > 0 && *v != '"') {
        memcpy(buf, v, vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1);
        buf[vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1] = '\0';
        long val = strtol(buf, NULL, 10);
        if (val >= 60 && val <= 86400) {
            config->low_battery_sleep_s = (uint32_t)val;
            changed = true;
            ESP_LOGI(TAG, "patch: low_battery_sleep_seconds=%lu", (unsigned long)config->low_battery_sleep_s);
        }
    }

    v = find_json_value(patch_json, "motion_sensitivity", &vlen);
    if (v && vlen > 0 && *v != '"') {
        memcpy(buf, v, vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1);
        buf[vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1] = '\0';
        long val = strtol(buf, NULL, 10);
        if (val >= 0 && val <= 3) {
            config->motion_sensitivity = (uint8_t)val;
            changed = true;
            ESP_LOGI(TAG, "patch: motion_sensitivity=%d", config->motion_sensitivity);
        }
    }

    if (!changed) {
        ESP_LOGW(TAG, "config patch contained no recognised keys");
        return ESP_ERR_NOT_FOUND;
    }

    return clawcam_config_save(config);
}

/* ── Reset ──────────────────────────────────────────────────────────────── */

esp_err_t clawcam_config_reset(clawcam_config_t *config)
{
    clawcam_config_defaults(config);
    nvs_handle_t h;
    esp_err_t err = open_nvs(&h, NVS_READWRITE);
    if (err != ESP_OK) return err;
    nvs_erase_namespace(h);  /* clear all keys in the namespace */
    err = nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "config reset to factory defaults");
    return err;
}
