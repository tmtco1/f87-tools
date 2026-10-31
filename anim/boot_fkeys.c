/*
 * AULA F87 custom boot animation: a full-white light sweeps across F1..F12.
 *
 * Called by the firmware's boot-mode frame handler (0x1D0B) in place of the original snake step
 * (LCALL 0x8B26 at 0x1D52), once every "step period" ticks (byte at 0x1D25). The firmware keeps
 * doing the rest: every "fade period" ticks (byte at 0x1D11) its renderer (0x63E5) pushes all keys
 * to the LEDs and dims each lit key by 1/32, and when RUN becomes 0 it ends boot mode and restores
 * the user's lighting mode.
 *
 * Firmware state used (XRAM), all set up by the firmware when boot mode starts (0xB1B3):
 *   0x0EC2  POS  step counter, starts at 0      (the snake's column variable, unused by us otherwise)
 *   0x0EC4  RUN  0xFF while running, 0 = done  (the firmware ends boot mode when it reads 0)
 *   0x0424 + col*18 + row*3   per-key colour  R,G,B
 *   0x0017 + col*6  + row     per-key level   0..32 (32 = full)
 *
 * Recommended timing (patch_firmware.py --boot-anim fkeys applies it): step period 8, fade period 1
 * -> a running light with a ~4-key trail. Trail length ~= 32 * fade / step keys.
 *
 * Constraints: no globals, no library calls, no internal RAM -- everything lives in registers or in
 * the firmware's XRAM, so nothing of the Keil-built firmware is disturbed.
 */

#define XB(a)      (*(volatile __xdata unsigned char *)(a))
#define POS        XB(0x0EC2)
#define RUN        XB(0x0EC4)

#define COLOUR_BUF 0x0424u
#define LEVEL_BUF  0x0017u
#define FULL       0x20

#ifndef FIRST_COL
#define FIRST_COL  2        /* F1 */
#endif
#ifndef NKEYS
#define NKEYS      12       /* F1..F12 */
#endif
#ifndef TAIL_STEPS
#define TAIL_STEPS 6        /* steps to wait after F12 so the trail can fade out before boot ends
                               (fade-out takes 32 x fade period ticks; with fade 1 / step 8 that's 4 steps) */
#endif
#ifndef ROW
#define ROW        0        /* LED row of the F-keys */
#endif
#ifndef R_VAL
#define R_VAL      0xFF
#endif
#ifndef G_VAL
#define G_VAL      0xFF
#endif
#ifndef B_VAL
#define B_VAL      0xFF
#endif

void boot_step(void)
{
    unsigned char pos, col, off;
    volatile __xdata unsigned char *p;

    if (RUN == 0)
        return;

    pos = POS;
    if (pos >= (unsigned char)(NKEYS + TAIL_STEPS)) {
        RUN = 0;                       /* firmware sees this on the next tick and ends boot mode */
        return;
    }
    POS = pos + 1;
    if (pos >= NKEYS)
        return;                        /* tail: just let the renderer fade the keys out */

    col = FIRST_COL + pos;

    off = col * 18 + ROW * 3;          /* col <= 16 -> fits in a byte */
    p = (volatile __xdata unsigned char *)(COLOUR_BUF + off);
    p[0] = R_VAL;
    p[1] = G_VAL;
    p[2] = B_VAL;

    off = col * 6 + ROW;
    XB(LEVEL_BUF + off) = FULL;
}
