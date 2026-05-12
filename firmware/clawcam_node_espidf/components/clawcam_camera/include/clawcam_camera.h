#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int jpeg_quality;
    int frame_size;
    int flash_gpio;
    bool flash_enabled;
} clawcam_camera_config_t;

typedef struct {
    uint8_t *data;
    size_t length;
    uint32_t width;
    uint32_t height;
    int64_t captured_at_unix_ms;
    const char *mime_type;
} clawcam_camera_capture_t;

esp_err_t clawcam_camera_init(const clawcam_camera_config_t *config);
esp_err_t clawcam_camera_capture(clawcam_camera_capture_t *capture);
void clawcam_camera_release(clawcam_camera_capture_t *capture);
esp_err_t clawcam_camera_set_quality(int jpeg_quality);
esp_err_t clawcam_camera_set_flash(bool enabled);
bool clawcam_camera_is_initialized(void);
esp_err_t clawcam_camera_deinit(void);

#ifdef __cplusplus
}
#endif
