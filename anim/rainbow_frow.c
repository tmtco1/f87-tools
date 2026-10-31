/*
 * Example: F1..F12 light up one by one, each in its own colour from a table in flash.
 * Preset: patch_firmware.py --boot-anim rainbow_frow (--boot-step 8 --boot-fade 1)
 */
#define XB(a)      (*(volatile __xdata unsigned char *)(a))
#define POS        XB(0x0EC2)
#define RUN        XB(0x0EC4)
#define COLOUR_BUF 0x0424u
#define LEVEL_BUF  0x0017u

#define FIRST_COL  2
#define NKEYS      12
#define TAIL_STEPS 6

/* R, G, B per key -- __code puts the table in flash next to the code, not in RAM */
static __code const unsigned char colours[NKEYS * 3] = {
    0xFF, 0x00, 0x00,   0xFF, 0x40, 0x00,   0xFF, 0x80, 0x00,   0xFF, 0xFF, 0x00,
    0x80, 0xFF, 0x00,   0x00, 0xFF, 0x00,   0x00, 0xFF, 0x80,   0x00, 0xFF, 0xFF,
    0x00, 0x80, 0xFF,   0x00, 0x00, 0xFF,   0x80, 0x00, 0xFF,   0xFF, 0x00, 0xFF,
};

void boot_step(void)
{
    unsigned char pos, col, off, c;

    if (RUN == 0)
        return;
    pos = POS;
    if (pos >= NKEYS + TAIL_STEPS) {
        RUN = 0;
        return;
    }
    POS = pos + 1;
    if (pos >= NKEYS)
        return;

    col = FIRST_COL + pos;
    off = col * 18;                              /* row 0 */
    c = pos * 3;
    XB(COLOUR_BUF + off + 0) = colours[c + 0];
    XB(COLOUR_BUF + off + 1) = colours[c + 1];
    XB(COLOUR_BUF + off + 2) = colours[c + 2];
    XB(LEVEL_BUF + col * 6) = 0x20;
}
