#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int pir_gpio;
    uint32_t debounce_ms;
    bool wake_from_deep_sleep;
} clawcam_motion_config_t;

typedef struct {
    bool motion_detected;
    int64_t detected_at_unix_ms;
    uint32_t debounce_ms;
    const char *trigger_source;
} clawcam_motion_event_t;

esp_err_t clawcam_motion_init(const clawcam_motion_config_t *config);
bool clawcam_motion_is_detected(void);
esp_err_t clawcam_motion_get_event(clawcam_motion_event_t *event);
esp_err_t clawcam_motion_set_debounce(uint32_t debounce_ms);
esp_err_t clawcam_motion_deinit(void);

#ifdef __cplusplus
}
#endif
