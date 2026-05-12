idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES clawcam_camera clawcam_motion clawcam_storage clawcam_power clawcam_events clawcam_gateway_client
)
