#pragma once

#include <stddef.h>
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

#ifdef __cplusplus
}
#endif
