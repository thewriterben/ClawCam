#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CLAWCAM_STORAGE_GPIO_NC (-1)

typedef enum {
    CLAWCAM_STORAGE_BUS_SDMMC_1BIT = 0,
    CLAWCAM_STORAGE_BUS_SPI = 1,
} clawcam_storage_bus_t;

typedef struct {
    int d0;
    int d1;
    int d2;
    int d3;
    int cmd;
    int clk;
    int detect;
} clawcam_storage_pins_t;

typedef struct {
    const char *mount_point;
    const char *media_dir;
    const char *metadata_dir;
    const char *events_dir;
    uint64_t min_free_bytes;
    bool auto_cleanup_enabled;
    clawcam_storage_bus_t bus;
    clawcam_storage_pins_t pins;
} clawcam_storage_config_t;

typedef struct {
    bool mounted;
    uint64_t total_bytes;
    uint64_t used_bytes;
    uint64_t free_bytes;
    uint32_t media_count;
    float error_rate;
} clawcam_storage_health_t;

typedef struct {
    const uint8_t *data;
    size_t length;
    const char *media_id;
    const char *extension;
} clawcam_storage_media_t;

esp_err_t clawcam_storage_default_esp32_s3_eye_config(clawcam_storage_config_t *config);
esp_err_t clawcam_storage_init(const clawcam_storage_config_t *config);
esp_err_t clawcam_storage_save_media(const clawcam_storage_media_t *media, char *out_path, size_t out_path_len);
esp_err_t clawcam_storage_save_metadata(const char *media_path, const char *json_metadata);
esp_err_t clawcam_storage_save_event_json(const char *event_id, const char *json_event, char *out_path, size_t out_path_len);
esp_err_t clawcam_storage_get_health(clawcam_storage_health_t *health);
esp_err_t clawcam_storage_deinit(void);

#ifdef __cplusplus
}
#endif
