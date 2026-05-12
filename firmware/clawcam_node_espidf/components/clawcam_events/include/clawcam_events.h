#pragma once

#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *event_id;
    const char *event_type;
    const char *device_id;
    const char *deployment_id;
    const char *timestamp;
    const char *time_source;
    const char *media_id;
    const char *media_path;
    const char *mime_type;
    size_t size_bytes;
    uint32_t width;
    uint32_t height;
    const char *trigger;
    const char *board_profile;
    const char *capture_profile;
} clawcam_event_capture_t;

esp_err_t clawcam_event_build_capture_json(const clawcam_event_capture_t *event, char *out_json, size_t out_json_len);

#ifdef __cplusplus
}
#endif
