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

/* IR-cut filter on a two-input H-bridge (DRV8833, TB6612, L9110S).
 *
 * The filter is a bistable coil: one pulse pulls it into the light path (day),
 * the opposite pulse pulls it out (night), and it holds with no power, which
 * means it also holds through deep sleep. gpio_a/gpio_b are the bridge inputs;
 * CLAWCAM_CAMERA_GPIO_NC on either means no filter. */
typedef struct {
    int gpio_a;
    int gpio_b;
    bool engage_on_a;   /* pulsing gpio_a puts the filter IN (day); depends on coil wiring */
    int pulse_ms;
} clawcam_camera_ir_cut_t;

/* Day/night rule state. Small and plain so it can live in RTC memory and
 * survive deep sleep, where the filter keeps its position too. */
typedef struct {
    uint8_t night;      /* 1 when the filter is out */
    uint8_t run;        /* consecutive readings arguing for a switch */
} clawcam_camera_day_night_t;

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
    clawcam_camera_ir_cut_t ir_cut;
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

/* True when the config names both IR-cut GPIOs. */
bool clawcam_camera_has_ir_cut(void);
/* engaged=true: filter in the light path (day). Blocks for pulse_ms. */
esp_err_t clawcam_camera_set_ir_cut(bool engaged);
/* Scene light = 1000 * mean / (gain * exposure lines), from the sensor's own
 * registers. OV5640 only: ESP_ERR_NOT_SUPPORTED on any other sensor. The
 * sensor must have streamed a few frames first so auto-exposure has settled. */
esp_err_t clawcam_camera_read_light(uint32_t *light);
/* Pure rule, no hardware. Feed one reading; returns true when the filter must
 * move, with state->night already updated. day_above must exceed night_below:
 * the gap absorbs the infrared the open filter lets in. */
bool clawcam_camera_day_night_observe(clawcam_camera_day_night_t *state, uint32_t light,
                                      uint32_t night_below, uint32_t day_above, uint8_t dwell);
bool clawcam_camera_is_initialized(void);
esp_err_t clawcam_camera_deinit(void);

#ifdef __cplusplus
}
#endif
