/*
 * "TMTCO" boot animation: T, M, T, C, O light up one after another, then a ripple spreads out
 * from O across the whole keyboard.
 *
 * Preset: patch_firmware.py --boot-anim tmtco (--boot-step 4 --boot-fade 2)
 *
 * Timing is counted in calls of boot_step() (one call per step period):
 *   - every letter is lit at full and fades out on its own (so the second T flashes again),
 *     LETTER_GAP calls apart
 *   - after O, one ripple ring per RING_GAP calls, radius 1..MAX_R around O; on every ring step
 *     everything inside the ring is halved, so the ripple stays a tight band
 *   - then TAIL_RINGS more ring periods so the outer rings can fade
 *   - then every LED is switched off and the keyboard stays dark for BLACK_GAP calls before the
 *     normal lighting starts
 *
 * Size tricks (the code area is only 384 bytes and the 8051 has 8 registers):
 *   - the whole colour buffer is painted once on the first call; afterwards only levels change
 *   - the level buffer is one run of 17 x 6 = 102 bytes, so a byte index (col*6 + row) reaches
 *     every LED
 *   - each LED's distance from O is precomputed in a table, so the ripple is one compare per LED
 *
 * State: 0x0EC1 = SUB (calls left to wait, starts at 0), 0x0EC2 = POS (phase), 0x0EC4 = RUN.
 */

#define XB(a)      (*(__xdata unsigned char *)(a))
#define SUB        XB(0x0EC1)
#define POS        XB(0x0EC2)
#define RUN        XB(0x0EC4)

#define COLOUR_BUF ((__xdata unsigned char *)0x0424)
#define LEVEL_BUF  ((__xdata unsigned char *)0x0017)
#define FULL       0x20
#define NLEDS      102

#ifndef LETTER_GAP
#define LETTER_GAP   10     /* calls between letters */
#endif
#ifndef RING_GAP
#define RING_GAP     3      /* calls between ripple rings (smaller = faster ripple) */
#endif
#ifndef TAIL_RINGS
#define TAIL_RINGS   4      /* extra ring periods so the outer rings can fade out */
#endif
#ifndef BLACK_GAP
#define BLACK_GAP    20     /* calls to stay completely dark before the normal lighting starts */
#endif
#ifndef COLOUR_R            /* colour of the letters and the ripple */
#define COLOUR_R     0xFF
#endif
#ifndef COLOUR_G
#define COLOUR_G     0xFF
#endif
#ifndef COLOUR_B
#define COLOUR_B     0xFF
#endif

/* Level-buffer index (col * 6 + row) of T, M, T, C, O.
   T (5,2) and O (9,2) are on row 2, where LED position = keymap position. M and C are on the
   Shift row, which the firmware remaps (table at 0x2B5F, the same one the stock snake uses):
   keymap (4,7) M -> LED (6,4), keymap (4,3) C -> LED (2,4). */
#define NLETTERS 5
static __code const unsigned char letters[NLETTERS] = { 32, 40, 32, 16, 56 };

/* Distance of every LED from O at (9,2), as max(dc,dr) + min(dc,dr)/2 (roughly a circle).
   One line per LED column, six rows each. On the Shift row (5th value) the distance is taken from
   the key's keymap column, i.e. where the key physically is, not from its remapped LED column. */
#define MAX_R 10
static __code const unsigned char dist[NLEDS] = {
    10,  9,  9,  9, 10, 10,   /* col  0 */
     9,  8,  8,  8,  8,  9,   /* col  1 */
     8,  7,  7,  7,  7,  8,   /* col  2 */
     7,  6,  6,  6,  6,  7,   /* col  3 */
     6,  5,  5,  5,  5,  6,   /* col  4 */
     5,  4,  4,  4,  4,  5,   /* col  5 */
     4,  3,  3,  3,  3,  4,   /* col  6 */
     3,  2,  2,  2,  2,  4,   /* col  7 */
     2,  1,  1,  1,  2,  3,   /* col  8 */
     2,  1,  0,  1,  2,  3,   /* col  9 */
     2,  1,  1,  1,  3,  3,   /* col 10 */
     3,  2,  2,  2,  4,  4,   /* col 11 */
     4,  3,  3,  3,  9,  4,   /* col 12 */
     5,  4,  4,  4,  5,  5,   /* col 13 */
     6,  5,  5,  5,  6,  6,   /* col 14 */
     7,  6,  6,  6,  7,  7,   /* col 15 */
     8,  7,  7,  7,  8,  8,   /* col 16 */
};

void boot_step(void)
{
    unsigned char ring, i;
    __xdata unsigned char *p;

    if (RUN == 0)
        return;
    if (SUB) {                          /* waiting for the next event */
        SUB = SUB - 1;
        return;
    }
    ring = POS;
    POS = ring + 1;

    if (ring == 0) {                    /* first call: give every LED the colour (all still dark) */
        p = COLOUR_BUF;
        for (i = NLEDS; i; i--) {
            *p++ = COLOUR_R;
            *p++ = COLOUR_G;
            *p++ = COLOUR_B;
        }
    }

    /* phase 1: the letters */
    if (ring < NLETTERS) {
        LEVEL_BUF[letters[ring]] = FULL;
        SUB = LETTER_GAP - 1;
        return;
    }

    /* phase 2: the ripple */
    ring = ring - NLETTERS + 1;        /* radius 1, 2, ... */
    if (ring <= MAX_R + TAIL_RINGS) {
        SUB = RING_GAP - 1;
        for (i = 0; i < NLEDS; i++) {
            if (dist[i] == ring)
                LEVEL_BUF[i] = FULL;   /* the new ring (nothing matches during the tail) */
            else if (dist[i] < ring)
                LEVEL_BUF[i] >>= 1;    /* everything inside it dims fast: a tight wave front */
        }
        return;
    }

    /* phase 3: blackout, hold, then hand over to the normal lighting */
    if (ring == MAX_R + TAIL_RINGS + 1) {
        for (i = 0; i < NLEDS; i++)
            LEVEL_BUF[i] = 0;          /* every LED off: the renderer now sends black */
        SUB = BLACK_GAP - 1;
        return;
    }
    RUN = 0;                           /* the firmware ends boot mode on the next step */
}
