#pragma once

/*
 * clawcam_ota — OTA firmware update via gateway HTTP download.
 *
 * Downloads the binary from the gateway, verifies SHA256, writes to the OTA
 * partition, and reboots. Uses the same compile gate as the gateway client so
 * the component compiles cleanly in host/CI builds without ESP-IDF headers.
 *
 * Usage:
 *   esp_err_t err = clawcam_ota_update(base_url, "/api/v1/firmware/<id>/download",
 *                                       sha256_hex, "0.3.0");
 *   if (err == ESP_OK) { /* reboot is triggered automatically */ }
 */

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Download and flash a firmware update.
 *
 * base_url      Gateway base URL, e.g. "http://192.168.1.10:8080"
 * firmware_path Absolute path on gateway, e.g. "/api/v1/firmware/<id>/download"
 * expected_sha256 64-char lowercase hex SHA256 of the binary (may be NULL to skip)
 * version       Human-readable version string for log messages
 *
 * Returns ESP_OK on success (device reboots after this call).
 * Returns ESP_ERR_OTA_VALIDATE_FAILED if SHA256 does not match.
 * Returns other esp_err_t codes on HTTP or flash errors.
 */
esp_err_t clawcam_ota_update(
    const char *base_url,
    const char *firmware_path,
    const char *expected_sha256,
    const char *version);

#ifdef __cplusplus
}
#endif
