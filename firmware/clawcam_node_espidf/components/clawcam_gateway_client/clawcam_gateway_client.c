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

#ifndef CONFIG_CLAWCAM_GATEWAY_API_TOKEN
#define CONFIG_CLAWCAM_GATEWAY_API_TOKEN ""
#endif

static const char *TAG = "clawcam_gateway_client";

esp_err_t clawcam_gateway_client_default_config(clawcam_gateway_client_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    config->base_url = CONFIG_CLAWCAM_GATEWAY_BASE_URL;
    config->api_token = CONFIG_CLAWCAM_GATEWAY_API_TOKEN[0] != '\0'
                            ? CONFIG_CLAWCAM_GATEWAY_API_TOKEN : NULL;
    config->timeout_ms = CONFIG_CLAWCAM_GATEWAY_HTTP_TIMEOUT_MS;
    return ESP_OK;
}

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT
/* Gateway auth accepts 'Authorization: Bearer <token>' (or X-Api-Key); a raw
 * token without the Bearer prefix is rejected when auth is enabled. */
static void set_auth_header(esp_http_client_handle_t client,
                            const clawcam_gateway_client_config_t *config)
{
    if (config->api_token == NULL || config->api_token[0] == '\0') {
        return;
    }
    char auth[192];
    int n = snprintf(auth, sizeof(auth), "Bearer %s", config->api_token);
    if (n > 0 && (size_t)n < sizeof(auth)) {
        esp_http_client_set_header(client, "Authorization", auth);
    } else {
        ESP_LOGW(TAG, "api token too long for auth header; request sent unauthenticated");
    }
}
#endif

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
    set_auth_header(client, config);
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

esp_err_t clawcam_gateway_client_post_health(const clawcam_gateway_client_config_t *config, const char *health_json)
{
    return post_wrapped_payload(config, "/api/v1/health", health_json);
}

esp_err_t clawcam_gateway_client_upload_media(
    const clawcam_gateway_client_config_t *config,
    const char *event_id,
    const uint8_t *data,
    size_t length)
{
    if (config == NULL || config->base_url == NULL || event_id == NULL ||
        data == NULL || length == 0) {
        return ESP_ERR_INVALID_ARG;
    }

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT
    /* POST /api/v1/media/{event_id} is the sole trigger for gateway-side
     * inference, alert evaluation, and cloud sync — event JSON alone only
     * records that a capture happened. Streamed multipart so the JPEG is
     * never duplicated in RAM. */
    char url[256];
    int url_len = snprintf(url, sizeof(url), "%s/api/v1/media/%s", config->base_url, event_id);
    if (url_len < 0 || (size_t)url_len >= sizeof(url)) {
        return ESP_ERR_INVALID_SIZE;
    }

    static const char *BOUNDARY = "clawcam7f3a9c1b2d";
    char head[256];
    int head_len = snprintf(head, sizeof(head),
        "--%s\r\n"
        "Content-Disposition: form-data; name=\"file\"; filename=\"%s.jpg\"\r\n"
        "Content-Type: image/jpeg\r\n\r\n",
        BOUNDARY, event_id);
    char tail[64];
    int tail_len = snprintf(tail, sizeof(tail), "\r\n--%s--\r\n", BOUNDARY);
    if (head_len < 0 || (size_t)head_len >= sizeof(head) ||
        tail_len < 0 || (size_t)tail_len >= sizeof(tail)) {
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
    char content_type[80];
    snprintf(content_type, sizeof(content_type), "multipart/form-data; boundary=%s", BOUNDARY);
    esp_http_client_set_header(client, "Content-Type", content_type);
    set_auth_header(client, config);

    int total_len = head_len + (int)length + tail_len;
    esp_err_t err = esp_http_client_open(client, total_len);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        ESP_LOGW(TAG, "media upload connect failed: %s", esp_err_to_name(err));
        return err;
    }

    bool write_ok =
        esp_http_client_write(client, head, head_len) == head_len;
    size_t sent = 0;
    while (write_ok && sent < length) {
        int chunk = esp_http_client_write(client, (const char *)data + sent, (int)(length - sent));
        if (chunk <= 0) {
            write_ok = false;
            break;
        }
        sent += (size_t)chunk;
    }
    write_ok = write_ok && esp_http_client_write(client, tail, tail_len) == tail_len;

    int status = -1;
    if (write_ok) {
        esp_http_client_fetch_headers(client);
        status = esp_http_client_get_status_code(client);
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (!write_ok) {
        ESP_LOGW(TAG, "media upload body write failed after %u bytes", (unsigned)sent);
        return ESP_FAIL;
    }
    if (status < 200 || status >= 300) {
        ESP_LOGW(TAG, "media upload returned HTTP %d", status);
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "media uploaded for %s (%u bytes)", event_id, (unsigned)length);
    return ESP_OK;
#else
    ESP_LOGI(TAG, "gateway upload disabled; would upload %u media bytes for %s",
             (unsigned)length, event_id);
    return ESP_ERR_NOT_SUPPORTED;
#endif
}
