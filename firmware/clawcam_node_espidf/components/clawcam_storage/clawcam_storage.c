#include "clawcam_storage.h"

#include <stdio.h>
#include <string.h>
#include "esp_log.h"

static const char *TAG = "clawcam_storage";
static bool s_initialized = false;
static clawcam_storage_config_t s_config = {0};

esp_err_t clawcam_storage_init(const clawcam_storage_config_t *config)
{
    if (config == NULL || config->mount_point == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config = *config;
    s_initialized = true;
    ESP_LOGI(TAG, "storage scaffold initialized: mount=%s media=%s metadata=%s",
             s_config.mount_point,
             s_config.media_dir ? s_config.media_dir : "media",
             s_config.metadata_dir ? s_config.metadata_dir : "metadata");
    return ESP_OK;
}

esp_err_t clawcam_storage_save_media(const clawcam_storage_media_t *media, char *out_path, size_t out_path_len)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (media == NULL || out_path == NULL || out_path_len == 0 || media->media_id == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const char *dir = s_config.media_dir ? s_config.media_dir : "media";
    const char *extension = media->extension ? media->extension : "jpg";
    int written = snprintf(out_path, out_path_len, "%s/%s/%s.%s", s_config.mount_point, dir, media->media_id, extension);
    if (written < 0 || (size_t)written >= out_path_len) {
        return ESP_ERR_INVALID_SIZE;
    }
    ESP_LOGW(TAG, "storage save is a scaffold; would write %u bytes to %s",
             (unsigned)media->length, out_path);
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t clawcam_storage_save_metadata(const char *media_path, const char *json_metadata)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (media_path == NULL || json_metadata == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_LOGW(TAG, "metadata save is a scaffold for media path %s", media_path);
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t clawcam_storage_get_health(clawcam_storage_health_t *health)
{
    if (health == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(health, 0, sizeof(*health));
    health->mounted = s_initialized;
    return ESP_OK;
}

esp_err_t clawcam_storage_deinit(void)
{
    s_initialized = false;
    return ESP_OK;
}
