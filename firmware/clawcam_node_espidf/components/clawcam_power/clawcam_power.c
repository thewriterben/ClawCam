#include "clawcam_power.h"

#include <string.h>
#include "esp_log.h"
#include "esp_sleep.h"
#include "driver/gpio.h"

/* Optional ADC battery sensing — gated so scaffold builds stay clean. */
#if defined(__has_include)
#  if __has_include("esp_adc/adc_oneshot.h")
#    include "esp_adc/adc_oneshot.h"
#    define CLAWCAM_HAVE_ADC_ONESHOT 1
#  endif
#  if __has_include("esp_adc/adc_cali_scheme.h")
#    include "esp_adc/adc_cali.h"
#    include "esp_adc/adc_cali_scheme.h"
#    define CLAWCAM_HAVE_ADC_CALI 1
#  endif
#endif
#ifndef CLAWCAM_HAVE_ADC_ONESHOT
#define CLAWCAM_HAVE_ADC_ONESHOT 0
#endif
#ifndef CLAWCAM_HAVE_ADC_CALI
#define CLAWCAM_HAVE_ADC_CALI 0
#endif

/* Battery sense wiring: VBAT — R1 — sense — R2 — GND. Default assumes a
 * symmetric divider (ratio 2.0). LiPo percentage is a linear 3.0–4.2 V map —
 * coarse, but monotonic and good enough for low-battery gating. */
#define CLAWCAM_BATT_DIVIDER_DEFAULT 2.0f
#define CLAWCAM_BATT_EMPTY_V         3.0f
#define CLAWCAM_BATT_FULL_V          4.2f
#define CLAWCAM_BATT_ADC_SAMPLES     8

static const char *TAG = "clawcam_power";
static bool s_initialized = false;
static clawcam_power_config_t s_config = {0};
#if CLAWCAM_HAVE_ADC_ONESHOT
static adc_oneshot_unit_handle_t s_adc_unit = NULL;
#if CLAWCAM_HAVE_ADC_CALI
static adc_cali_handle_t s_adc_cali = NULL;
#endif
#endif
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

#if CLAWCAM_HAVE_ADC_ONESHOT
    if (s_config.battery_adc_channel >= 0) {
        adc_oneshot_unit_init_cfg_t unit_cfg = {
            .unit_id = ADC_UNIT_1,
        };
        esp_err_t err = adc_oneshot_new_unit(&unit_cfg, &s_adc_unit);
        if (err == ESP_OK) {
            adc_oneshot_chan_cfg_t chan_cfg = {
                .atten = ADC_ATTEN_DB_12,
                .bitwidth = ADC_BITWIDTH_DEFAULT,
            };
            err = adc_oneshot_config_channel(
                s_adc_unit, (adc_channel_t)s_config.battery_adc_channel, &chan_cfg);
        }
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "battery ADC init failed (%s); battery telemetry disabled",
                     esp_err_to_name(err));
            s_adc_unit = NULL;
        }
#if CLAWCAM_HAVE_ADC_CALI
        if (s_adc_unit != NULL) {
            adc_cali_curve_fitting_config_t cali_cfg = {
                .unit_id = ADC_UNIT_1,
                .atten = ADC_ATTEN_DB_12,
                .bitwidth = ADC_BITWIDTH_DEFAULT,
            };
            if (adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_adc_cali) != ESP_OK) {
                s_adc_cali = NULL; /* fall back to linear raw conversion */
            }
        }
#endif
    }
#endif

    ESP_LOGI(TAG, "power initialized: adc=%d pir_wake_gpio=%d capacity=%.1fmAh",
             s_config.battery_adc_channel, s_config.pir_wake_gpio, s_config.battery_capacity_mah);
    return ESP_OK;
}

#if CLAWCAM_HAVE_ADC_ONESHOT
/* Return battery voltage in volts, or a negative value when unavailable. */
static float read_battery_voltage(void)
{
    if (s_adc_unit == NULL || s_config.battery_adc_channel < 0) {
        return -1.0f;
    }
    int raw_sum = 0;
    int good = 0;
    for (int i = 0; i < CLAWCAM_BATT_ADC_SAMPLES; i++) {
        int raw = 0;
        if (adc_oneshot_read(s_adc_unit,
                             (adc_channel_t)s_config.battery_adc_channel, &raw) == ESP_OK) {
            raw_sum += raw;
            good++;
        }
    }
    if (good == 0) {
        return -1.0f;
    }
    int raw_avg = raw_sum / good;
    int mv = -1;
#if CLAWCAM_HAVE_ADC_CALI
    if (s_adc_cali != NULL) {
        if (adc_cali_raw_to_voltage(s_adc_cali, raw_avg, &mv) != ESP_OK) {
            mv = -1;
        }
    }
#endif
    if (mv < 0) {
        /* Uncalibrated fallback: 12 dB attenuation ≈ 0–3300 mV over 12 bits. */
        mv = (raw_avg * 3300) / 4095;
    }
    return ((float)mv / 1000.0f) * CLAWCAM_BATT_DIVIDER_DEFAULT;
}
#endif /* CLAWCAM_HAVE_ADC_ONESHOT */

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
    state->battery_percentage = -1;   /* -1 = unknown; health report omits battery */
    state->low_battery = false;
    state->estimated_remaining_hours = 0.0f;
    state->charging = false;

#if CLAWCAM_HAVE_ADC_ONESHOT
    float volts = read_battery_voltage();
    if (volts > 0.0f) {
        state->battery_voltage = volts;
        float frac = (volts - CLAWCAM_BATT_EMPTY_V) /
                     (CLAWCAM_BATT_FULL_V - CLAWCAM_BATT_EMPTY_V);
        if (frac < 0.0f) frac = 0.0f;
        if (frac > 1.0f) frac = 1.0f;
        state->battery_percentage = (int)(frac * 100.0f + 0.5f);
        if (s_config.low_battery_threshold_v > 0.0f) {
            state->low_battery = volts < s_config.low_battery_threshold_v;
        }
        if (s_config.battery_capacity_mah > 0.0f && s_profile.idle_current_ma > 0.0f) {
            state->estimated_remaining_hours =
                (s_config.battery_capacity_mah * frac) / s_profile.idle_current_ma;
        }
    }
#endif
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
    /* PIR output goes HIGH on motion; EXT0 triggers when gpio level == 1 */
    esp_err_t err = esp_sleep_enable_ext0_wakeup((gpio_num_t)pir_gpio, 1);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "EXT0 wakeup on gpio=%d not available (%s); node will rely on timer wake only",
                 pir_gpio, esp_err_to_name(err));
    } else {
        ESP_LOGI(TAG, "wake-on-motion configured: gpio=%d", pir_gpio);
    }
    return ESP_OK;
}

esp_err_t clawcam_power_configure_wake_on_timer(uint64_t seconds)
{
    if (seconds == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t err = esp_sleep_enable_timer_wakeup(seconds * 1000000ULL);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "timer wakeup configuration failed: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "wake-on-timer configured: %llu seconds", (unsigned long long)seconds);
    return ESP_OK;
}

esp_err_t clawcam_power_enter_deep_sleep(uint64_t seconds)
{
    if (seconds > 0) {
        /* Caller may have already configured timer wake; this ensures a fallback exists */
        clawcam_power_configure_wake_on_timer(seconds);
    }
    ESP_LOGI(TAG, "entering deep sleep (pir_gpio=%d timer_fallback=%llus)",
             s_config.pir_wake_gpio, (unsigned long long)seconds);
    esp_deep_sleep_start();
    /* never reached */
    return ESP_OK;
}
