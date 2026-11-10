#include "clawcam_camera.h"

#include <string.h>
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#if defined(__has_include)
#  if __has_include("esp_camera.h")
#    include "esp_camera.h"
#    define CLAWCAM_HAVE_ESP_CAMERA 1
#  else
#    define CLAWCAM_HAVE_ESP_CAMERA 0
#  endif
#else
#  define CLAWCAM_HAVE_ESP_CAMERA 0
#endif

#ifndef CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA
#define CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA 0
#endif
#ifndef CONFIG_CLAWCAM_IRCUT_GPIO_A
#define CONFIG_CLAWCAM_IRCUT_GPIO_A (-1)
#endif
#ifndef CONFIG_CLAWCAM_IRCUT_GPIO_B
#define CONFIG_CLAWCAM_IRCUT_GPIO_B (-1)
#endif
#ifndef CONFIG_CLAWCAM_IRCUT_ENGAGE_ON_A
#define CONFIG_CLAWCAM_IRCUT_ENGAGE_ON_A 0
#endif
#ifndef CONFIG_CLAWCAM_IRCUT_PULSE_MS
#define CONFIG_CLAWCAM_IRCUT_PULSE_MS 150
#endif

#define OV5640_PID_VALUE 0x5640

static const char *TAG = "clawcam_camera";
static bool s_initialized = false;
static clawcam_camera_config_t s_config = {0};

esp_err_t clawcam_camera_default_esp32_s3_eye_config(clawcam_camera_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(config, 0, sizeof(*config));
    config->jpeg_quality = 12;
    config->frame_size = CLAWCAM_CAMERA_FRAME_SIZE_UXGA;
    config->flash_gpio = CLAWCAM_CAMERA_GPIO_NC;
    config->flash_enabled = false;
    config->xclk_hz = 16000000;
    config->fb_count = 1;
    config->use_psram = true;
    config->grab_latest = true;
    config->vflip = true;
    config->hflip = false;
    config->ir_cut = (clawcam_camera_ir_cut_t){
        .gpio_a = CONFIG_CLAWCAM_IRCUT_GPIO_A,
        .gpio_b = CONFIG_CLAWCAM_IRCUT_GPIO_B,
        .engage_on_a = CONFIG_CLAWCAM_IRCUT_ENGAGE_ON_A,
        .pulse_ms = CONFIG_CLAWCAM_IRCUT_PULSE_MS,
    };
    config->pins = (clawcam_camera_pins_t){
        .pwdn = CLAWCAM_CAMERA_GPIO_NC,
        .reset = CLAWCAM_CAMERA_GPIO_NC,
        .xclk = 15,
        .siod = 4,
        .sioc = 5,
        .d0 = 11,
        .d1 = 9,
        .d2 = 8,
        .d3 = 10,
        .d4 = 12,
        .d5 = 18,
        .d6 = 17,
        .d7 = 16,
        .vsync = 6,
        .href = 7,
        .pclk = 13,
    };
    return ESP_OK;
}

esp_err_t clawcam_camera_init(const clawcam_camera_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config = *config;

    /* The IR-cut pins do not depend on the camera driver, so set them up in
     * scaffold mode too. Both inputs low is "coast": no current in the coil.
     * The filter is NOT moved here: after deep sleep it is still where the
     * last wake left it, and only the caller knows which case this is. */
    if (clawcam_camera_has_ir_cut()) {
        gpio_config_t ir_conf = {
            .pin_bit_mask = (1ULL << s_config.ir_cut.gpio_a) | (1ULL << s_config.ir_cut.gpio_b),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&ir_conf));
        gpio_set_level(s_config.ir_cut.gpio_a, 0);
        gpio_set_level(s_config.ir_cut.gpio_b, 0);
    }

#if CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA && CLAWCAM_HAVE_ESP_CAMERA
    camera_config_t camera_config = {
        .pin_pwdn = s_config.pins.pwdn,
        .pin_reset = s_config.pins.reset,
        .pin_xclk = s_config.pins.xclk,
        .pin_sccb_sda = s_config.pins.siod,
        .pin_sccb_scl = s_config.pins.sioc,
        .pin_d7 = s_config.pins.d7,
        .pin_d6 = s_config.pins.d6,
        .pin_d5 = s_config.pins.d5,
        .pin_d4 = s_config.pins.d4,
        .pin_d3 = s_config.pins.d3,
        .pin_d2 = s_config.pins.d2,
        .pin_d1 = s_config.pins.d1,
        .pin_d0 = s_config.pins.d0,
        .pin_vsync = s_config.pins.vsync,
        .pin_href = s_config.pins.href,
        .pin_pclk = s_config.pins.pclk,
        .xclk_freq_hz = s_config.xclk_hz > 0 ? s_config.xclk_hz : 16000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = (framesize_t)s_config.frame_size,
        .jpeg_quality = s_config.jpeg_quality,
        .fb_count = s_config.fb_count > 0 ? s_config.fb_count : 1,
        .fb_location = s_config.use_psram ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM,
        .grab_mode = s_config.grab_latest ? CAMERA_GRAB_LATEST : CAMERA_GRAB_WHEN_EMPTY,
    };

    esp_err_t err = esp_camera_init(&camera_config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init failed: 0x%x", err);
        s_initialized = false;
        return err;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor != NULL) {
        sensor->set_vflip(sensor, s_config.vflip ? 1 : 0);
        sensor->set_hmirror(sensor, s_config.hflip ? 1 : 0);
    }

    if (s_config.flash_gpio >= 0) {
        gpio_config_t io_conf = {
            .pin_bit_mask = 1ULL << s_config.flash_gpio,
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&io_conf));
        gpio_set_level(s_config.flash_gpio, s_config.flash_enabled ? 1 : 0);
    }

    s_initialized = true;
    ESP_LOGI(TAG, "esp32-camera initialized: quality=%d frame_size=%d xclk=%d",
             s_config.jpeg_quality, s_config.frame_size, s_config.xclk_hz);
    return ESP_OK;
#else
    s_initialized = true;
    ESP_LOGW(TAG, "camera initialized in scaffold mode; set CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA with esp32-camera to enable hardware capture");
    return ESP_OK;
#endif
}

esp_err_t clawcam_camera_capture(clawcam_camera_capture_t *capture)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (capture == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(capture, 0, sizeof(*capture));
    capture->mime_type = "image/jpeg";

#if CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA && CLAWCAM_HAVE_ESP_CAMERA
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb == NULL) {
        return ESP_FAIL;
    }
    capture->data = fb->buf;
    capture->length = fb->len;
    capture->width = fb->width;
    capture->height = fb->height;
    capture->captured_at_unix_ms = 0;
    capture->mime_type = "image/jpeg";
    capture->driver_frame = fb;
    return ESP_OK;
#else
    ESP_LOGW(TAG, "camera capture is a scaffold; hardware capture is not enabled in this build");
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

void clawcam_camera_release(clawcam_camera_capture_t *capture)
{
    if (capture == NULL) {
        return;
    }
#if CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA && CLAWCAM_HAVE_ESP_CAMERA
    if (capture->driver_frame != NULL) {
        esp_camera_fb_return((camera_fb_t *)capture->driver_frame);
    }
#endif
    memset(capture, 0, sizeof(*capture));
}

esp_err_t clawcam_camera_set_quality(int jpeg_quality)
{
    if (jpeg_quality < 1 || jpeg_quality > 63) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config.jpeg_quality = jpeg_quality;
#if CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA && CLAWCAM_HAVE_ESP_CAMERA
    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor != NULL) {
        sensor->set_quality(sensor, jpeg_quality);
    }
#endif
    return ESP_OK;
}

esp_err_t clawcam_camera_set_flash(bool enabled)
{
    s_config.flash_enabled = enabled;
    if (s_config.flash_gpio >= 0) {
        gpio_set_level(s_config.flash_gpio, enabled ? 1 : 0);
    }
    ESP_LOGI(TAG, "flash set to %s", enabled ? "on" : "off");
    return ESP_OK;
}

bool clawcam_camera_has_ir_cut(void)
{
    return s_config.ir_cut.gpio_a >= 0 && s_config.ir_cut.gpio_b >= 0;
}

esp_err_t clawcam_camera_set_ir_cut(bool engaged)
{
    if (!clawcam_camera_has_ir_cut()) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    const bool pulse_a = (engaged == s_config.ir_cut.engage_on_a);
    const int pulse = pulse_a ? s_config.ir_cut.gpio_a : s_config.ir_cut.gpio_b;
    const int rest = pulse_a ? s_config.ir_cut.gpio_b : s_config.ir_cut.gpio_a;
    const int pulse_ms = s_config.ir_cut.pulse_ms > 0 ? s_config.ir_cut.pulse_ms : 150;

    gpio_set_level(rest, 0);
    gpio_set_level(pulse, 1);
    vTaskDelay(pdMS_TO_TICKS(pulse_ms));
    gpio_set_level(pulse, 0);
    ESP_LOGI(TAG, "IR-cut filter %s", engaged ? "in (day)" : "out (night)");
    return ESP_OK;
}

esp_err_t clawcam_camera_read_light(uint32_t *light)
{
    if (light == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
#if CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA && CLAWCAM_HAVE_ESP_CAMERA
    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor == NULL || sensor->get_reg == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    if (sensor->id.PID != OV5640_PID_VALUE) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    /* OV5640: AVG READOUT 0x56A1, AEC PK REAL GAIN 0x350A/0x350B (1/16),
     * AEC PK EXPOSURE 0x3500..0x3502 (1/16 line). The capture is JPEG, so the
     * sensor's own average stands in for a mean computed from pixels. */
    static const int regs[6] = {0x56A1, 0x350A, 0x350B, 0x3500, 0x3501, 0x3502};
    int v[6];
    for (int i = 0; i < 6; i++) {
        v[i] = sensor->get_reg(sensor, regs[i], 0xff);
        if (v[i] < 0) {
            return ESP_FAIL;
        }
    }
    const uint64_t mean = (uint64_t)v[0];
    const uint64_t gain_x16 = ((uint64_t)(v[1] & 0x03) << 8) | (uint64_t)v[2];
    const uint64_t exposure_x16 = ((uint64_t)(v[3] & 0x0f) << 16) | ((uint64_t)v[4] << 8) | (uint64_t)v[5];
    if (gain_x16 == 0 || exposure_x16 == 0) {
        return ESP_FAIL;
    }
    *light = (uint32_t)((1000ULL * 256ULL * mean) / (gain_x16 * exposure_x16));
    ESP_LOGI(TAG, "light=%lu (avg=%d gain_x16=%llu exposure_x16=%llu)",
             (unsigned long)*light, v[0],
             (unsigned long long)gain_x16, (unsigned long long)exposure_x16);
    return ESP_OK;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

bool clawcam_camera_day_night_observe(clawcam_camera_day_night_t *state, uint32_t light,
                                      uint32_t night_below, uint32_t day_above, uint8_t dwell)
{
    if (state == NULL || day_above <= night_below) {
        return false;
    }
    const bool wants_other = state->night ? (light > day_above) : (light < night_below);
    if (!wants_other) {
        state->run = 0;
        return false;
    }
    if (state->run < UINT8_MAX) {
        state->run++;
    }
    if (state->run < (dwell > 0 ? dwell : 1)) {
        return false;
    }
    state->night = state->night ? 0 : 1;
    state->run = 0;
    return true;
}

bool clawcam_camera_is_initialized(void)
{
    return s_initialized;
}

esp_err_t clawcam_camera_deinit(void)
{
#if CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA && CLAWCAM_HAVE_ESP_CAMERA
    if (s_initialized) {
        esp_camera_deinit();
    }
#endif
    s_initialized = false;
    return ESP_OK;
}
