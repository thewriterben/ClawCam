idf_component_register(
    SRCS "clawcam_ota.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_client esp_https_ota mbedtls
)
