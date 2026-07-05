#pragma once

#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *base_url;
    const char *api_token;
    int timeout_ms;
} clawcam_gateway_client_config_t;

esp_err_t clawcam_gateway_client_default_config(clawcam_gateway_client_config_t *config);
esp_err_t clawcam_gateway_client_register_device(const clawcam_gateway_client_config_t *config, const char *device_json);
esp_err_t clawcam_gateway_client_upload_event(const clawcam_gateway_client_config_t *config, const char *event_json);

/* POST health JSON to /api/v1/health (wrapped in {"data": ...}). */
esp_err_t clawcam_gateway_client_post_health(const clawcam_gateway_client_config_t *config, const char *health_json);

/* Streamed multipart upload of a JPEG to /api/v1/media/{event_id}; this is
 * what triggers gateway-side inference, alerts, and cloud sync. */
esp_err_t clawcam_gateway_client_upload_media(
    const clawcam_gateway_client_config_t *config,
    const char *event_id,
    const uint8_t *data,
    size_t length);

#ifdef __cplusplus
}
#endif
