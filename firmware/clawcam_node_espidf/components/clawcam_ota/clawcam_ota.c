#include "clawcam_ota.h"

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

#if defined(__has_include)
#  if __has_include("esp_ota_ops.h")
#    include "esp_ota_ops.h"
#    include "esp_partition.h"
#    define CLAWCAM_HAVE_ESP_OTA 1
#  else
#    define CLAWCAM_HAVE_ESP_OTA 0
#  endif
#else
#  define CLAWCAM_HAVE_ESP_OTA 0
#endif

#if defined(__has_include)
#  if __has_include("mbedtls/sha256.h")
#    include "mbedtls/sha256.h"
#    define CLAWCAM_HAVE_MBEDTLS 1
#  else
#    define CLAWCAM_HAVE_MBEDTLS 0
#  endif
#else
#  define CLAWCAM_HAVE_MBEDTLS 0
#endif

#ifndef CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
#define CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED 0
#endif

static const char *TAG = "clawcam_ota";

#define OTA_BUF_SIZE   4096
#define OTA_URL_MAX     512

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT && CLAWCAM_HAVE_ESP_OTA

/* Convert binary SHA256 digest to lowercase hex string (65 bytes incl. NUL). */
static void sha256_to_hex(const uint8_t *digest, char *out_hex)
{
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        out_hex[i * 2]     = hex[(digest[i] >> 4) & 0xf];
        out_hex[i * 2 + 1] = hex[digest[i] & 0xf];
    }
    out_hex[64] = '\0';
}

esp_err_t clawcam_ota_update(
    const char *base_url,
    const char *firmware_path,
    const char *expected_sha256,
    const char *version)
{
    char url[OTA_URL_MAX];
    snprintf(url, sizeof(url), "%s%s", base_url, firmware_path);
    ESP_LOGI(TAG, "starting OTA: version=%s url=%s", version ? version : "?", url);

    esp_ota_handle_t ota_handle = 0;
    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        ESP_LOGE(TAG, "no OTA partition found");
        return ESP_ERR_NOT_FOUND;
    }

    esp_err_t err = esp_ota_begin(update_partition, OTA_SIZE_UNKNOWN, &ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin failed: %s", esp_err_to_name(err));
        return err;
    }

#if CLAWCAM_HAVE_MBEDTLS
    mbedtls_sha256_context sha_ctx;
    mbedtls_sha256_init(&sha_ctx);
    mbedtls_sha256_starts(&sha_ctx, 0 /* SHA-256, not SHA-224 */);
#endif

    esp_http_client_config_t http_cfg = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = 30000,
        .buffer_size = OTA_BUF_SIZE,
    };
    esp_http_client_handle_t client = esp_http_client_init(&http_cfg);
    if (!client) {
        esp_ota_abort(ota_handle);
        return ESP_FAIL;
    }

    err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP open failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        esp_ota_abort(ota_handle);
        return err;
    }

    esp_http_client_fetch_headers(client);
    int status_code = esp_http_client_get_status_code(client);
    if (status_code != 200) {
        ESP_LOGE(TAG, "HTTP status %d for firmware download", status_code);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        esp_ota_abort(ota_handle);
        return ESP_FAIL;
    }

    static uint8_t ota_buf[OTA_BUF_SIZE];
    int total_written = 0;

    while (true) {
        int read_len = esp_http_client_read(client, (char *)ota_buf, sizeof(ota_buf));
        if (read_len == 0) break;
        if (read_len < 0) {
            ESP_LOGE(TAG, "HTTP read error");
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            esp_ota_abort(ota_handle);
            return ESP_FAIL;
        }

        err = esp_ota_write(ota_handle, ota_buf, read_len);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_ota_write failed: %s", esp_err_to_name(err));
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            esp_ota_abort(ota_handle);
            return err;
        }

#if CLAWCAM_HAVE_MBEDTLS
        mbedtls_sha256_update(&sha_ctx, ota_buf, read_len);
#endif
        total_written += read_len;
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    ESP_LOGI(TAG, "downloaded %d bytes", total_written);

#if CLAWCAM_HAVE_MBEDTLS
    uint8_t digest[32];
    mbedtls_sha256_finish(&sha_ctx, digest);
    mbedtls_sha256_free(&sha_ctx);

    if (expected_sha256 && expected_sha256[0] != '\0') {
        char actual_hex[65];
        sha256_to_hex(digest, actual_hex);
        if (strncasecmp(actual_hex, expected_sha256, 64) != 0) {
            ESP_LOGE(TAG, "SHA256 mismatch: expected %.16s... got %.16s...",
                     expected_sha256, actual_hex);
            esp_ota_abort(ota_handle);
            return ESP_ERR_OTA_VALIDATE_FAILED;
        }
        ESP_LOGI(TAG, "SHA256 verified: %.16s...", actual_hex);
    }
#endif

    err = esp_ota_end(ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end failed: %s", esp_err_to_name(err));
        return err;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition failed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "OTA complete — rebooting to version %s", version ? version : "?");
    esp_restart();
    return ESP_OK; /* unreachable */
}

#else /* stub */

esp_err_t clawcam_ota_update(
    const char *base_url,
    const char *firmware_path,
    const char *expected_sha256,
    const char *version)
{
    ESP_LOGI(TAG, "OTA stub: would download %s%s (version=%s sha256=%.16s...)",
             base_url ? base_url : "",
             firmware_path ? firmware_path : "",
             version ? version : "?",
             expected_sha256 ? expected_sha256 : "");
    return ESP_OK;
}

#endif /* CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && ... */
