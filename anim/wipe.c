/*
 * Example: a white wipe across the whole keyboard, one column per step (Esc column -> Pause column).
 * Preset: patch_firmware.py --boot-anim wipe (--boot-step 6 --boot-fade 2)
 */
#define XB(a)      (*(volatile __xdata unsigned char *)(a))
#define POS        XB(0x0EC2)
#define RUN        XB(0x0EC4)
#define COLOUR_BUF 0x0424u
#define LEVEL_BUF  0x0017u

#define NCOLS      17
#define TAIL_STEPS 12

void boot_step(void)
{
    unsigned char pos, row, off;
    volatile __xdata unsigned char *col_colours;

    if (RUN == 0)
        return;
    pos = POS;
    if (pos >= NCOLS + TAIL_STEPS) {
        RUN = 0;
        return;
    }
    POS = pos + 1;
    if (pos >= NCOLS)
        return;

    /* pos * 18 doesn't fit in a byte for columns >= 15, so build the column pointer with 16-bit
       pointer arithmetic in two byte-sized steps (pos * 9 <= 144) instead of an int multiply,
       which would pull in SDCC's __mulint library routine. */
    off = pos * 9;                              /* byte-sized product: stays an 8-bit MUL */
    col_colours = (volatile __xdata unsigned char *)COLOUR_BUF;
    col_colours += off;
    col_colours += off;

    for (row = 0; row < 6; row++) {             /* all six rows of this column */
        off = row * 3;
        col_colours[off + 0] = 0xFF;
        col_colours[off + 1] = 0xFF;
        col_colours[off + 2] = 0xFF;
        XB(LEVEL_BUF + pos * 6 + row) = 0x20;   /* pos * 6 <= 96: fits in a byte */
    }
}
