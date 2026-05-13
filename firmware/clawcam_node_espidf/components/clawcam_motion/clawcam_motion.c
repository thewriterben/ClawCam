#include "clawcam_motion.h"

#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_timer.h"

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

    /* Detect if firmware woke from deep sleep due to PIR (EXT0) */
    if (config->wake_from_deep_sleep) {
        esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
        if (cause == ESP_SLEEP_WAKEUP_EXT0) {
            s_motion_latched = true;
            ESP_LOGI(TAG, "resumed from deep sleep via PIR EXT0 on gpio=%d", s_config.pir_gpio);
        }
    }

    ESP_LOGI(TAG, "motion initialized: pir_gpio=%d debounce_ms=%lu motion_latched=%s",
             s_config.pir_gpio, (unsigned long)s_config.debounce_ms,
             s_motion_latched ? "true" : "false");
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
    /* Best available time reference: microseconds since boot converted to ms */
    event->detected_at_unix_ms = (int64_t)(esp_timer_get_time() / 1000LL);
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
