idf_component_register(
    SRCS "clawcam_storage.c"
    INCLUDE_DIRS "include"
    REQUIRES fatfs sdmmc driver
)
