#include "clawcam_power.h"

#include <string.h>
#include "esp_log.h"

static const char *TAG = "clawcam_power";
static bool s_initialized = false;
static clawcam_power_config_t s_config = {0};
static clawcam_power_profile_t s_profile = {
    .idle_current_ma = 80.0f,
    .capture_current_ma = 240.0f,
    .transmit_current_ma = 320.0f,
    .deep_sleep_current_ua = 150.0f,
};

esp_err_t clawcam_power_init(const clawcam_power_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config = *config;
    s_initialized = true;
    ESP_LOGI(TAG, "power scaffold initialized: adc=%d pir_wake_gpio=%d capacity=%.1fmAh",
             s_config.battery_adc_channel, s_config.pir_wake_gpio, s_config.battery_capacity_mah);
    return ESP_OK;
}

esp_err_t clawcam_power_get_state(clawcam_power_state_t *state)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (state == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(state, 0, sizeof(*state));
    state->battery_voltage = 0.0f;
    state->battery_percentage = -1;
    state->low_battery = false;
    state->estimated_remaining_hours = 0.0f;
    state->charging = false;
    return ESP_OK;
}

esp_err_t clawcam_power_set_profile(const clawcam_power_profile_t *profile)
{
    if (profile == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_profile = *profile;
    return ESP_OK;
}

esp_err_t clawcam_power_record_capture(void)
{
    ESP_LOGI(TAG, "capture energy accounting scaffold: %.1fmA", s_profile.capture_current_ma);
    return ESP_OK;
}

esp_err_t clawcam_power_record_transmission(void)
{
    ESP_LOGI(TAG, "transmission energy accounting scaffold: %.1fmA", s_profile.transmit_current_ma);
    return ESP_OK;
}

esp_err_t clawcam_power_configure_wake_on_motion(int pir_gpio)
{
    s_config.pir_wake_gpio = pir_gpio;
    ESP_LOGI(TAG, "wake-on-motion scaffold configured for gpio=%d", pir_gpio);
    return ESP_OK;
}

esp_err_t clawcam_power_configure_wake_on_timer(uint64_t seconds)
{
    ESP_LOGI(TAG, "wake-on-timer scaffold configured for %llu seconds", (unsigned long long)seconds);
    return ESP_OK;
}

esp_err_t clawcam_power_enter_deep_sleep(uint64_t seconds)
{
    ESP_LOGW(TAG, "deep sleep scaffold requested for %llu seconds; not entering sleep yet", (unsigned long long)seconds);
    return ESP_ERR_NOT_SUPPORTED;
}
