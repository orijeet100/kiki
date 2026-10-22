/* LVGL settings for Kiki on the Tab5. build.ps1 puts this folder on the compiler's include
 * path, so LVGL finds this file; anything not set here keeps LVGL's default. */
#ifndef LV_CONF_H
#define LV_CONF_H

#define LV_COLOR_DEPTH 16

/* malloc instead of LVGL's fixed 64 KB pool: 50 run cards in History need more, and the
 * ESP32-P4's malloc puts big blocks in PSRAM. */
#define LV_USE_STDLIB_MALLOC LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_CLIB

#define LV_DEF_REFR_PERIOD 16       /* ~60 fps for the orb */
#define LV_DPI_DEF 294              /* 5" at 1280x720 */
#define LV_USE_FONT_COMPRESSED 1    /* the Inter fonts in src/ are compressed by lv_font_conv */
#define LV_FONT_MONTSERRAT_24 1     /* the keyboard's symbols: inter_24 falls back to it */
#define LV_THEME_DEFAULT_DARK 1

#endif
