#include "clawcam_camera.h"

#include "esp_log.h"

static const char *TAG = "clawcam_camera";
static bool s_initialized = false;
static clawcam_camera_config_t s_config = {0};

esp_err_t clawcam_camera_init(const clawcam_camera_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config = *config;
    s_initialized = true;
    ESP_LOGI(TAG, "camera scaffold initialized: quality=%d frame_size=%d flash_gpio=%d",
             s_config.jpeg_quality, s_config.frame_size, s_config.flash_gpio);
    return ESP_OK;
}

esp_err_t clawcam_camera_capture(clawcam_camera_capture_t *capture)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (capture == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    capture->data = NULL;
    capture->length = 0;
    capture->width = 0;
    capture->height = 0;
    capture->captured_at_unix_ms = 0;
    capture->mime_type = "image/jpeg";
    ESP_LOGW(TAG, "camera capture is a scaffold; hardware capture not ported yet");
    return ESP_ERR_NOT_SUPPORTED;
}

void clawcam_camera_release(clawcam_camera_capture_t *capture)
{
    if (capture == NULL) {
        return;
    }
    capture->data = NULL;
    capture->length = 0;
}

esp_err_t clawcam_camera_set_quality(int jpeg_quality)
{
    if (jpeg_quality < 1 || jpeg_quality > 63) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config.jpeg_quality = jpeg_quality;
    return ESP_OK;
}

esp_err_t clawcam_camera_set_flash(bool enabled)
{
    s_config.flash_enabled = enabled;
    ESP_LOGI(TAG, "flash scaffold set to %s", enabled ? "on" : "off");
    return ESP_OK;
}

bool clawcam_camera_is_initialized(void)
{
    return s_initialized;
}

esp_err_t clawcam_camera_deinit(void)
{
    s_initialized = false;
    return ESP_OK;
}
