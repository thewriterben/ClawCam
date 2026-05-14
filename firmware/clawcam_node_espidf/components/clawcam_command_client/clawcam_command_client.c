#include "clawcam_command_client.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "esp_log.h"

/* Optional HTTP client — same gated pattern as gateway_client */
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

#define DEFAULT_MAX_COMMANDS   5
#define RESPONSE_BUF_SIZE      4096
#define ACK_BODY_MAX           256
#define URL_MAX                256

static const char *TAG = "clawcam_cmd_client";

/* ── Tiny JSON helpers ──────────────────────────────────────────────────── */

static const char *json_find_value(const char *json, const char *key, size_t *out_len)
{
    if (!json || !key) return NULL;
    char search[80];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char *p = strstr(json, search);
    if (!p) return NULL;
    p += strlen(search);
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (*p != ':') return NULL;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    const char *start = p;
    if (*p == '"') {
        p++;
        while (*p && *p != '"') { if (*p == '\\') p++; p++; }
        if (*p == '"') p++;
    } else if (*p == '{' || *p == '[') {
        int depth = 1; char open = *p, close = (open == '{') ? '}' : ']';
        p++;
        while (*p && depth > 0) {
            if (*p == open) depth++;
            else if (*p == close) depth--;
            p++;
        }
    } else {
        while (*p && *p != ',' && *p != '}' && *p != '\n') p++;
        while (p > start && (*(p-1) == ' ' || *(p-1) == '\t')) p--;
    }
    *out_len = (size_t)(p - start);
    return start;
}

static void json_extract_str(const char *json, const char *key, char *buf, size_t buf_len)
{
    size_t vlen = 0;
    const char *v = json_find_value(json, key, &vlen);
    if (!v || vlen < 2 || *v != '"') { buf[0] = '\0'; return; }
    size_t slen = vlen - 2 < buf_len - 1 ? vlen - 2 : buf_len - 1;
    memcpy(buf, v + 1, slen);
    buf[slen] = '\0';
}

/* ── HTTP helpers (gated) ───────────────────────────────────────────────── */

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT

static esp_err_t http_get_response(const char *url, int timeout_ms, char *buf, size_t buf_len)
{
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = timeout_ms,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) return ESP_FAIL;
    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) { esp_http_client_cleanup(client); return err; }
    int content_len = esp_http_client_fetch_headers(client);
    if (content_len < 0) content_len = (int)buf_len - 1;
    int read = esp_http_client_read(client, buf, buf_len - 1 < (size_t)content_len ? buf_len - 1 : (size_t)content_len);
    buf[read > 0 ? read : 0] = '\0';
    int status = esp_http_client_get_status_code(client);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return (status >= 200 && status < 300) ? ESP_OK : ESP_FAIL;
}

static esp_err_t http_post(const char *url, const char *body, int timeout_ms)
{
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = timeout_ms,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) return ESP_FAIL;
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, body, (int)strlen(body));
    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if (err != ESP_OK) return err;
    return (status >= 200 && status < 300) ? ESP_OK : ESP_FAIL;
}

#endif /* CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT */

/* ── Ack ────────────────────────────────────────────────────────────────── */

static void send_ack(const clawcam_command_client_config_t *cfg,
                     const char *command_id,
                     const char *status,
                     const char *message)
{
    char url[URL_MAX];
    snprintf(url, sizeof(url), "%s/api/v1/commands/%s/ack",
             cfg->gateway_config->base_url, command_id);

    char body[ACK_BODY_MAX];
    snprintf(body, sizeof(body),
             "{\"status\":\"%s\",\"result\":{\"message\":\"%s\",\"node\":\"%s\"}}",
             status, message ? message : "", cfg->device_id);

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT
    esp_err_t err = http_post(url, body, cfg->gateway_config->timeout_ms);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "ack POST failed for %s: %s", command_id, esp_err_to_name(err));
    } else {
        ESP_LOGI(TAG, "acked command %s as %s", command_id, status);
    }
#else
    ESP_LOGI(TAG, "ack (stub): %s → %s | %s", command_id, status, body);
#endif
}

/* ── Command handlers ───────────────────────────────────────────────────── */

static void handle_capture_now(const clawcam_command_client_config_t *cfg,
                                const char *command_id,
                                const char *command_json)
{
    char reason[128];
    json_extract_str(command_json, "reason", reason, sizeof(reason));
    if (reason[0] == '\0') strncpy(reason, "gateway command", sizeof(reason) - 1);

    ESP_LOGI(TAG, "executing capture_now: id=%s reason=%s", command_id, reason);
    if (cfg->capture_cb != NULL) {
        cfg->capture_cb(command_id, reason);
        send_ack(cfg, command_id, "executed", "capture completed");
    } else {
        ESP_LOGW(TAG, "no capture_cb registered; cannot execute capture_now");
        send_ack(cfg, command_id, "failed", "no capture handler registered");
    }
}

static void handle_apply_config_patch(const clawcam_command_client_config_t *cfg,
                                       const char *command_id,
                                       const char *command_json)
{
    size_t patch_len = 0;
    const char *patch_v = json_find_value(command_json, "patch", &patch_len);
    if (patch_v == NULL || patch_len == 0) {
        ESP_LOGW(TAG, "apply_config_patch missing 'patch' field; skipping");
        send_ack(cfg, command_id, "failed", "missing patch field");
        return;
    }

    char patch_buf[512];
    size_t copy_len = patch_len < sizeof(patch_buf) - 1 ? patch_len : sizeof(patch_buf) - 1;
    memcpy(patch_buf, patch_v, copy_len);
    patch_buf[copy_len] = '\0';

    ESP_LOGI(TAG, "applying config patch: %s", patch_buf);
    esp_err_t err = clawcam_config_apply_patch_json(patch_buf, cfg->node_config);
    if (err == ESP_OK) {
        send_ack(cfg, command_id, "executed", "config patch applied and saved to NVS");
    } else if (err == ESP_ERR_NOT_FOUND) {
        send_ack(cfg, command_id, "skipped", "patch contained no recognised keys");
    } else {
        send_ack(cfg, command_id, "failed", esp_err_to_name(err));
    }
}

/* ── Poll ───────────────────────────────────────────────────────────────── */

int clawcam_command_client_poll(const clawcam_command_client_config_t *cfg)
{
    if (cfg == NULL || cfg->gateway_config == NULL || cfg->device_id == NULL) {
        return -ESP_ERR_INVALID_ARG;
    }

    int max = cfg->max_commands_per_wake > 0 ? cfg->max_commands_per_wake : DEFAULT_MAX_COMMANDS;

    char url[URL_MAX];
    snprintf(url, sizeof(url), "%s/api/v1/commands/%s/pending?limit=%d",
             cfg->gateway_config->base_url, cfg->device_id, max);

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_ESP_HTTP_CLIENT
    static char response[RESPONSE_BUF_SIZE];
    esp_err_t err = http_get_response(url, cfg->gateway_config->timeout_ms, response, sizeof(response));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "command poll GET failed: %s", esp_err_to_name(err));
        return -err;
    }

    /* Parse "count" field */
    size_t count_len = 0;
    const char *count_v = json_find_value(response, "count", &count_len);
    int count = count_v ? (int)strtol(count_v, NULL, 10) : 0;
    if (count <= 0) {
        ESP_LOGI(TAG, "no pending commands");
        return 0;
    }

    ESP_LOGI(TAG, "%d pending command(s) received", count);

    /*
     * Walk the "commands" array. Each element is a JSON object; we look for
     * "command_id" and "command_type" then dispatch to the right handler.
     * This is a simple linear scan — command arrays are small (≤ 5).
     */
    const char *p = strstr(response, "\"commands\"");
    if (!p) return 0;
    p = strchr(p, '[');
    if (!p) return 0;
    p++;

    int handled = 0;
    while (*p && *p != ']' && handled < max) {
        /* Skip whitespace and commas between objects */
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ',') p++;
        if (*p != '{') break;

        /* Find the matching closing brace */
        int depth = 1;
        const char *obj_start = p;
        p++;
        while (*p && depth > 0) {
            if (*p == '{') depth++;
            else if (*p == '}') depth--;
            p++;
        }
        /* obj_start .. p is one complete JSON command object */
        size_t obj_len = (size_t)(p - obj_start);
        char obj_buf[1024];
        if (obj_len >= sizeof(obj_buf)) {
            ESP_LOGW(TAG, "command object too large (%zu bytes); skipping", obj_len);
            continue;
        }
        memcpy(obj_buf, obj_start, obj_len);
        obj_buf[obj_len] = '\0';

        char command_id[64];
        char command_type[48];
        json_extract_str(obj_buf, "command_id",   command_id,   sizeof(command_id));
        json_extract_str(obj_buf, "command_type", command_type, sizeof(command_type));

        if (command_id[0] == '\0' || command_type[0] == '\0') {
            ESP_LOGW(TAG, "command missing id or type; skipping");
            continue;
        }

        if (strcmp(command_type, "capture_now") == 0) {
            handle_capture_now(cfg, command_id, obj_buf);
            handled++;
        } else if (strcmp(command_type, "apply_config_patch") == 0) {
            handle_apply_config_patch(cfg, command_id, obj_buf);
            handled++;
        } else {
            ESP_LOGW(TAG, "unknown command type '%s'; acking as skipped", command_type);
            send_ack(cfg, command_id, "skipped", "unknown command type");
        }
    }

    return handled;

#else
    ESP_LOGI(TAG, "command poll stub: would GET %s", url);
    return 0;
#endif
}
