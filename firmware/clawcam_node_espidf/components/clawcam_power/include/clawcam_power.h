#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int battery_adc_channel;
    int pir_wake_gpio;
    float battery_capacity_mah;
    float low_battery_threshold_v;
    bool energy_tracking_enabled;
} clawcam_power_config_t;

typedef struct {
    float idle_current_ma;
    float capture_current_ma;
    float transmit_current_ma;
    float deep_sleep_current_ua;
} clawcam_power_profile_t;

typedef struct {
    float battery_voltage;
    int battery_percentage;
    bool low_battery;
    float estimated_remaining_hours;
    bool charging;
} clawcam_power_state_t;

esp_err_t clawcam_power_init(const clawcam_power_config_t *config);
esp_err_t clawcam_power_get_state(clawcam_power_state_t *state);
esp_err_t clawcam_power_set_profile(const clawcam_power_profile_t *profile);
esp_err_t clawcam_power_record_capture(void);
esp_err_t clawcam_power_record_transmission(void);
esp_err_t clawcam_power_configure_wake_on_motion(int pir_gpio);
esp_err_t clawcam_power_configure_wake_on_timer(uint64_t seconds);
esp_err_t clawcam_power_enter_deep_sleep(uint64_t seconds);

#ifdef __cplusplus
}
#endif
