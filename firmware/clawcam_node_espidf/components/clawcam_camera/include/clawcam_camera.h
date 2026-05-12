#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CLAWCAM_CAMERA_GPIO_NC (-1)
#define CLAWCAM_CAMERA_FRAME_SIZE_QVGA 5
#define CLAWCAM_CAMERA_FRAME_SIZE_VGA 8
#define CLAWCAM_CAMERA_FRAME_SIZE_SVGA 9
#define CLAWCAM_CAMERA_FRAME_SIZE_XGA 10
#define CLAWCAM_CAMERA_FRAME_SIZE_SXGA 12
#define CLAWCAM_CAMERA_FRAME_SIZE_UXGA 13

typedef struct {
    int pwdn;
    int reset;
    int xclk;
    int siod;
    int sioc;
    int d0;
    int d1;
    int d2;
    int d3;
    int d4;
    int d5;
    int d6;
    int d7;
    int vsync;
    int href;
    int pclk;
} clawcam_camera_pins_t;

typedef struct {
    int jpeg_quality;
    int frame_size;
    int flash_gpio;
    bool flash_enabled;
    int xclk_hz;
    int fb_count;
    bool use_psram;
    bool grab_latest;
    bool vflip;
    bool hflip;
    clawcam_camera_pins_t pins;
} clawcam_camera_config_t;

typedef struct {
    uint8_t *data;
    size_t length;
    uint32_t width;
    uint32_t height;
    int64_t captured_at_unix_ms;
    const char *mime_type;
    void *driver_frame;
} clawcam_camera_capture_t;

esp_err_t clawcam_camera_default_esp32_s3_eye_config(clawcam_camera_config_t *config);
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
