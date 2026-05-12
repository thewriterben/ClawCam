#include "clawcam_storage.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include "esp_check.h"
#include "esp_log.h"

#if defined(__has_include)
#  if __has_include("esp_vfs_fat.h") && __has_include("sdmmc_cmd.h")
#    include "esp_vfs_fat.h"
#    include "sdmmc_cmd.h"
#    include "driver/sdmmc_host.h"
#    define CLAWCAM_HAVE_FATFS_SDMMC 1
#  else
#    define CLAWCAM_HAVE_FATFS_SDMMC 0
#  endif
#else
#  define CLAWCAM_HAVE_FATFS_SDMMC 0
#endif

#ifndef CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC
#define CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC 0
#endif

#ifndef CONFIG_CLAWCAM_STORAGE_MAX_FILES
#define CONFIG_CLAWCAM_STORAGE_MAX_FILES 5
#endif

#ifndef CONFIG_CLAWCAM_STORAGE_FORMAT_IF_MOUNT_FAILED
#define CONFIG_CLAWCAM_STORAGE_FORMAT_IF_MOUNT_FAILED 0
#endif

static const char *TAG = "clawcam_storage";
static bool s_initialized = false;
static bool s_mounted = false;
static clawcam_storage_config_t s_config = {0};
#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
static sdmmc_card_t *s_card = NULL;
#endif

static const char *media_dir(void)
{
    return s_config.media_dir ? s_config.media_dir : "media";
}

static const char *metadata_dir(void)
{
    return s_config.metadata_dir ? s_config.metadata_dir : "metadata";
}

static const char *events_dir(void)
{
    return s_config.events_dir ? s_config.events_dir : "events";
}

static esp_err_t mkdir_if_needed(const char *path)
{
    if (path == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (mkdir(path, 0775) == 0 || errno == EEXIST) {
        return ESP_OK;
    }
    ESP_LOGE(TAG, "failed to create directory %s: errno=%d", path, errno);
    return ESP_FAIL;
}

static esp_err_t ensure_storage_dirs(void)
{
    char path[192];
    int written = snprintf(path, sizeof(path), "%s/%s", s_config.mount_point, media_dir());
    if (written < 0 || (size_t)written >= sizeof(path)) {
        return ESP_ERR_INVALID_SIZE;
    }
    ESP_RETURN_ON_ERROR(mkdir_if_needed(path), TAG, "create media directory");
    written = snprintf(path, sizeof(path), "%s/%s", s_config.mount_point, metadata_dir());
    if (written < 0 || (size_t)written >= sizeof(path)) {
        return ESP_ERR_INVALID_SIZE;
    }
    ESP_RETURN_ON_ERROR(mkdir_if_needed(path), TAG, "create metadata directory");
    written = snprintf(path, sizeof(path), "%s/%s", s_config.mount_point, events_dir());
    if (written < 0 || (size_t)written >= sizeof(path)) {
        return ESP_ERR_INVALID_SIZE;
    }
    return mkdir_if_needed(path);
}

esp_err_t clawcam_storage_default_esp32_s3_eye_config(clawcam_storage_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(config, 0, sizeof(*config));
    config->mount_point = "/sdcard";
    config->media_dir = "media";
    config->metadata_dir = "metadata";
    config->events_dir = "events";
    config->min_free_bytes = 128 * 1024 * 1024;
    config->auto_cleanup_enabled = false;
    config->bus = CLAWCAM_STORAGE_BUS_SDMMC_1BIT;
    config->pins = (clawcam_storage_pins_t){
        .d0 = 40,
        .d1 = CLAWCAM_STORAGE_GPIO_NC,
        .d2 = CLAWCAM_STORAGE_GPIO_NC,
        .d3 = CLAWCAM_STORAGE_GPIO_NC,
        .cmd = 38,
        .clk = 39,
        .detect = CLAWCAM_STORAGE_GPIO_NC,
    };
    return ESP_OK;
}

esp_err_t clawcam_storage_init(const clawcam_storage_config_t *config)
{
    if (config == NULL || config->mount_point == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    s_config = *config;
    s_initialized = true;

#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
    if (s_config.bus != CLAWCAM_STORAGE_BUS_SDMMC_1BIT) {
        ESP_LOGE(TAG, "only SDMMC 1-bit is implemented in the first storage port");
        return ESP_ERR_NOT_SUPPORTED;
    }

    esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = CONFIG_CLAWCAM_STORAGE_FORMAT_IF_MOUNT_FAILED,
        .max_files = CONFIG_CLAWCAM_STORAGE_MAX_FILES,
        .allocation_unit_size = 16 * 1024,
    };
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    sdmmc_slot_config_t slot_config = SDMMC_SLOT_CONFIG_DEFAULT();
    slot_config.width = 1;
#if SOC_SDMMC_USE_GPIO_MATRIX
    slot_config.clk = s_config.pins.clk;
    slot_config.cmd = s_config.pins.cmd;
    slot_config.d0 = s_config.pins.d0;
#endif

    esp_err_t err = esp_vfs_fat_sdmmc_mount(s_config.mount_point, &host, &slot_config, &mount_config, &s_card);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "failed to mount SD/FATFS at %s: %s", s_config.mount_point, esp_err_to_name(err));
        s_mounted = false;
        return err;
    }
    s_mounted = true;
    ESP_RETURN_ON_ERROR(ensure_storage_dirs(), TAG, "create storage directories");
    ESP_LOGI(TAG, "SD/FATFS mounted at %s", s_config.mount_point);
    return ESP_OK;
#else
    s_mounted = false;
    ESP_LOGW(TAG, "storage initialized in scaffold mode; enable CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC for SD/FATFS writes");
    return ESP_OK;
#endif
}

esp_err_t clawcam_storage_save_media(const clawcam_storage_media_t *media, char *out_path, size_t out_path_len)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (media == NULL || out_path == NULL || out_path_len == 0 || media->media_id == NULL || media->data == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const char *extension = media->extension ? media->extension : "jpg";
    int written = snprintf(out_path, out_path_len, "%s/%s/%s.%s", s_config.mount_point, media_dir(), media->media_id, extension);
    if (written < 0 || (size_t)written >= out_path_len) {
        return ESP_ERR_INVALID_SIZE;
    }

#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
    if (!s_mounted) {
        return ESP_ERR_INVALID_STATE;
    }
    FILE *file = fopen(out_path, "wb");
    if (file == NULL) {
        ESP_LOGE(TAG, "failed to open media path %s: errno=%d", out_path, errno);
        return ESP_FAIL;
    }
    size_t bytes_written = fwrite(media->data, 1, media->length, file);
    fclose(file);
    if (bytes_written != media->length) {
        ESP_LOGE(TAG, "short media write to %s: %u/%u", out_path, (unsigned)bytes_written, (unsigned)media->length);
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "saved media %s (%u bytes)", out_path, (unsigned)media->length);
    return ESP_OK;
#else
    ESP_LOGW(TAG, "media save is scaffolded; would write %u bytes to %s", (unsigned)media->length, out_path);
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t clawcam_storage_save_metadata(const char *media_path, const char *json_metadata)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (media_path == NULL || json_metadata == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    const char *base = strrchr(media_path, '/');
    base = base ? base + 1 : media_path;
    char metadata_path[256];
    int written = snprintf(metadata_path, sizeof(metadata_path), "%s/%s/%s.json", s_config.mount_point, metadata_dir(), base);
    if (written < 0 || (size_t)written >= sizeof(metadata_path)) {
        return ESP_ERR_INVALID_SIZE;
    }

#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
    if (!s_mounted) {
        return ESP_ERR_INVALID_STATE;
    }
    FILE *file = fopen(metadata_path, "w");
    if (file == NULL) {
        ESP_LOGE(TAG, "failed to open metadata path %s: errno=%d", metadata_path, errno);
        return ESP_FAIL;
    }
    int rc = fputs(json_metadata, file);
    fclose(file);
    if (rc < 0) {
        ESP_LOGE(TAG, "failed to write metadata path %s", metadata_path);
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "saved metadata %s", metadata_path);
    return ESP_OK;
#else
    ESP_LOGW(TAG, "metadata save is scaffolded for media path %s", media_path);
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t clawcam_storage_save_event_json(const char *event_id, const char *json_event, char *out_path, size_t out_path_len)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (event_id == NULL || json_event == NULL || out_path == NULL || out_path_len == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    int written = snprintf(out_path, out_path_len, "%s/%s/%s.json", s_config.mount_point, events_dir(), event_id);
    if (written < 0 || (size_t)written >= out_path_len) {
        return ESP_ERR_INVALID_SIZE;
    }

#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
    if (!s_mounted) {
        return ESP_ERR_INVALID_STATE;
    }
    FILE *file = fopen(out_path, "w");
    if (file == NULL) {
        ESP_LOGE(TAG, "failed to open event path %s: errno=%d", out_path, errno);
        return ESP_FAIL;
    }
    int rc = fputs(json_event, file);
    fclose(file);
    if (rc < 0) {
        ESP_LOGE(TAG, "failed to write event path %s", out_path);
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "saved event artifact %s", out_path);
    return ESP_OK;
#else
    ESP_LOGW(TAG, "event save is scaffolded for event %s", event_id);
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t clawcam_storage_get_health(clawcam_storage_health_t *health)
{
    if (health == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(health, 0, sizeof(*health));
    health->mounted = s_mounted;
#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
    if (s_card != NULL) {
        uint64_t total_bytes = ((uint64_t)s_card->csd.capacity) * s_card->csd.sector_size;
        health->total_bytes = total_bytes;
    }
#endif
    return ESP_OK;
}

esp_err_t clawcam_storage_deinit(void)
{
#if CONFIG_CLAWCAM_STORAGE_USE_FATFS_SDMMC && CLAWCAM_HAVE_FATFS_SDMMC
    if (s_mounted) {
        esp_vfs_fat_sdcard_unmount(s_config.mount_point, s_card);
    }
    s_card = NULL;
#endif
    s_mounted = false;
    s_initialized = false;
    return ESP_OK;
}
