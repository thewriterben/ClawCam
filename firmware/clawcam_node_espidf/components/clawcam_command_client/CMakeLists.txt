idf_component_register(
    SRCS "clawcam_command_client.c"
    INCLUDE_DIRS "include"
    REQUIRES clawcam_config clawcam_gateway_client esp_http_client
)
