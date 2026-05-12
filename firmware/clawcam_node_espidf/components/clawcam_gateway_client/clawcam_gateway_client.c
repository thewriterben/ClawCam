#include "clawcam_gateway_client.h"

#include <stdio.h>
#include <string.h>
#include "esp_log.h"

#if defined(__has_include)
#  if __has_include("esp_http_client.h")
#    include "esp_http_client.h"
#    define CLAWCAM_HAVE_ESP_HTTP_CLIENT 1
#  else
#    define CLAWCAM_HAVE_ESP_HTTP_CLIENT 0
#  endif
#else
#  define CLAWCAM_HAVE_ESP_HTTP_CLIENT 0
#endif

#ifndef CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
#define CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED 0
#endif

#ifndef CONFIG_CLAWCAM_GATEWAY_BASE_URL
#define CONFIG_CLAWCAM_GATEWAY_BASE_URL "http://192.168.4.1:8080"
#endif

#ifndef CONFIG_CLAWCAM_GATEWAY_HTTP_TIMEOUT_MS
#define CONFIG_CLAWCAM_GATEWAY_HTTP_TIMEOUT_MS 5000
#endif

static const char *TAG = "clawcam_gateway_client";

esp_err_t clawcam_gateway_client_default_config(clawcam_gateway_client_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    config->base_url = CONFIG_CLAWCAM_GATEWAY_BASE_URL;
    config->api_token = NULL;
    config->timeout_ms = CONFIG_CLAWCAM_GATEWAY_HTTP_TIMEOUT_MS;
    return ESP_OK;
}

static esp_err_t post_wrapped_payload(const clawcam_gateway_client_config_t *config, const char *path, const char *json)
{
    if (config == NULL || config->base_url == NULL || path == NULL || json == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT
    char url[256];
    int url_len = snprintf(url, sizeof(url), "%s%s", config->base_url, path);
    if (url_len < 0 || (size_t)url_len >= sizeof(url)) {
        return ESP_ERR_INVALID_SIZE;
    }

    char body[2048];
    int body_len = snprintf(body, sizeof(body), "{\"data\":%s}", json);
    if (body_len < 0 || (size_t)body_len >= sizeof(body)) {
        ESP_LOGE(TAG, "payload too large for upload wrapper");
        return ESP_ERR_INVALID_SIZE;
    }

    esp_http_client_config_t http_config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = config->timeout_ms > 0 ? config->timeout_ms : CONFIG_CLAWCAM_GATEWAY_HTTP_TIMEOUT_MS,
    };
    esp_http_client_handle_t client = esp_http_client_init(&http_config);
    if (client == NULL) {
        return ESP_FAIL;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");
    if (config->api_token != NULL) {
        esp_http_client_set_header(client, "Authorization", config->api_token);
    }
    esp_http_client_set_post_field(client, body, body_len);
    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "upload to %s failed: %s", url, esp_err_to_name(err));
        return err;
    }
    if (status < 200 || status >= 300) {
        ESP_LOGW(TAG, "upload to %s returned HTTP %d", url, status);
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "uploaded payload to %s", url);
    return ESP_OK;
#else
    ESP_LOGI(TAG, "gateway upload disabled; would POST %s to %s", path, config->base_url);
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t clawcam_gateway_client_register_device(const clawcam_gateway_client_config_t *config, const char *device_json)
{
    return post_wrapped_payload(config, "/api/v1/devices", device_json);
}

esp_err_t clawcam_gateway_client_upload_event(const clawcam_gateway_client_config_t *config, const char *event_json)
{
    return post_wrapped_payload(config, "/api/v1/events", event_json);
}
