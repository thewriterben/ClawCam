#include "clawcam_motion.h"

#include "esp_log.h"

static const char *TAG = "clawcam_motion";
static bool s_initialized = false;
static bool s_motion_latched = false;
static clawcam_motion_config_t s_config = {0};

esp_err_t clawcam_motion_init(const clawcam_motion_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config = *config;
    s_initialized = true;
    s_motion_latched = false;
    ESP_LOGI(TAG, "motion scaffold initialized: pir_gpio=%d debounce_ms=%lu",
             s_config.pir_gpio, (unsigned long)s_config.debounce_ms);
    return ESP_OK;
}

bool clawcam_motion_is_detected(void)
{
    return s_initialized && s_motion_latched;
}

esp_err_t clawcam_motion_get_event(clawcam_motion_event_t *event)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (event == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    event->motion_detected = s_motion_latched;
    event->detected_at_unix_ms = 0;
    event->debounce_ms = s_config.debounce_ms;
    event->trigger_source = "pir";
    return ESP_OK;
}

esp_err_t clawcam_motion_set_debounce(uint32_t debounce_ms)
{
    if (debounce_ms == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config.debounce_ms = debounce_ms;
    return ESP_OK;
}

esp_err_t clawcam_motion_deinit(void)
{
    s_initialized = false;
    s_motion_latched = false;
    return ESP_OK;
}
