; Conway's Game of Life lighting effect for the AULA F87 base firmware (base_f87_decrypted.bin).
;
; Lighting effect 9 (empty in the stock firmware). The keys are the cells, in their physical positions
; (the Shift row's LED order is remapped); positions without a key are always dead. One generation per
; frame period; a new random board when nothing changes any more, or after GEN_MAX generations.
; build.py prepends the settings (FRAME_P0..4, COL_R/G/B, DENSITY, GEN_MAX, STILL).
;
; Effect blob header (see docs/CUSTOM_EFFECTS.md), installed by patch_firmware.py --effect / --life:
;   +0 LJMP init    +3 LJMP frame    +6 LJMP next (patched: next effect's init, or 0x1B0E)    +9 mode
;
; Cell state lives in the firmware's key level buffer (0x0017 + led_col*6 + row): non-zero = alive.
; A generation is computed in place: bit 7 marks "alive next", then a second pass commits it.
; XRAM state: 0x0EC1 generation count, 0x0EC2/0x0EC3 16-bit random generator (borrowed from the boot snake).

        .module life
        .area   LIFE (ABS,CODE)
        .org    0xEE40

LEVEL   = 0x0017
COLOUR  = 0x0424
NKEYS   = 102
FULL    = 32
GEN     = 0x0EC1
RNG     = 0x0EC2
TICKH   = 0x0300
TICKL   = 0x0301
SPEED   = 0x0D94
MODE    = 0x0EC7
OURMODE = 9
RENDER  = 0x63E5

        ljmp    init
        ljmp    frame
next:   ljmp    0x1B0E
        .db     OURMODE

; ---- effect init (every mode change; acts only for our mode) ----
init:
        mov     dptr,#MODE
        movx    a,@dptr
        cjne    a,#OURMODE,1$
        jnb     0x21,1$
        clr     0x21
        setb    0x22
        clr     0x32
        clr     0x55
        mov     dptr,#TICKL     ; random seed from the tick counter
        movx    a,@dptr
        orl     a,#1
        mov     r6,a
        clr     a
        mov     dptr,#TICKH     ; frame clock from 0
        movx    @dptr,a
        inc     dptr
        movx    @dptr,a
        mov     dptr,#RNG
        mov     a,#0xAC
        movx    @dptr,a
        inc     dptr
        mov     a,r6
        movx    @dptr,a
        lcall   getcol
        mov     dptr,#COLOUR
        mov     r5,#NKEYS
2$:     mov     a,r2
        movx    @dptr,a
        inc     dptr
        mov     a,r3
        movx    @dptr,a
        inc     dptr
        mov     a,r4
        movx    @dptr,a
        inc     dptr
        djnz    r5,2$
        lcall   seed
1$:     ljmp    next

; ---- effect colour from the palette the app/WebHID set: r2,r3,r4 = R,G,B ----
; config byte of this effect (XRAM 0x0309 + 0x3B + 2*(id-1)) low nibble = palette slot 0..6, 7 = rainbow.
; Palette lives in flash at 0xC800 + 21*id + 3*slot. Rainbow can't be shown by a single-colour effect,
; so it uses slot 0.
CFG     = 0x0309 + 0x3B + 2*(OURMODE-1)
PALBASE = 0xC800 + 21*OURMODE
getcol:
        mov     dptr,#CFG
        movx    a,@dptr
        anl     a,#0x0F
        cjne    a,#7,2$
        clr     a               ; rainbow: use slot 0
2$:     mov     b,#3
        mul     ab
        add     a,#<PALBASE
        mov     dpl,a
        clr     a
        addc    a,#>PALBASE
        mov     dph,a
        clr     a
        movc    a,@a+dptr
        mov     r2,a
        inc     dptr
        clr     a
        movc    a,@a+dptr
        mov     r3,a
        inc     dptr
        clr     a
        movc    a,@a+dptr
        mov     r4,a
        ret

; ---- new random board ----
seed:
        mov     dptr,#GEN
        clr     a
        movx    @dptr,a
        inc     dptr
        movx    a,@dptr
        mov     r2,a
        inc     dptr
        movx    a,@dptr
        mov     r3,a
        mov     dptr,#LEVEL
        mov     r5,#NKEYS
3$:     mov     a,r2            ; 16-bit Galois LFSR, taps 0xB400
        clr     c
        rrc     a
        mov     r2,a
        mov     a,r3
        rrc     a
        mov     r3,a
        jnc     4$
        mov     a,r2
        xrl     a,#0xB4
        mov     r2,a
4$:     mov     a,r3
        clr     c
        subb    a,#DENSITY      ; alive with probability DENSITY/256
        clr     a
        jnc     5$
        mov     a,#FULL
5$:     movx    @dptr,a
        inc     dptr
        djnz    r5,3$
        mov     dptr,#RNG
        mov     a,r2
        movx    @dptr,a
        inc     dptr
        mov     a,r3
        movx    @dptr,a
        ljmp    RENDER

; ---- frame handler (called continuously while our mode is active) ----
frame:
        mov     dptr,#SPEED     ; period = periods[min(speed, 4)]
        movx    a,@dptr
        cjne    a,#5,6$
6$:     jc      7$
        mov     a,#4
7$:     rl      a
        mov     r4,a
        mov     dptr,#periods
        movc    a,@a+dptr
        mov     r6,a
        mov     a,r4
        inc     a
        movc    a,@a+dptr
        mov     r7,a
        mov     dptr,#TICKL     ; ticks -= period, unless ticks < period
        movx    a,@dptr
        clr     c
        subb    a,r7
        mov     r5,a
        mov     dptr,#TICKH
        movx    a,@dptr
        subb    a,r6
        jnc     8$
        ret
8$:     movx    @dptr,a
        inc     dptr
        mov     a,r5
        movx    @dptr,a

        ; pass 1: for every key cell, count the live cells in its 3x3 block (itself included);
        ; total 3 -> alive next, total 4 -> keeps its state, anything else -> dead
        mov     r6,#0           ; physical column
9$:     mov     r7,#0           ; row
10$:    mov     a,r6
        mov     r4,a
        mov     a,r7
        mov     r5,a
        lcall   lookup
        jnc     16$             ; no key here
        mov     r0,#0
        mov     a,r6
        dec     a
        mov     r4,a
        mov     r1,#3
11$:    mov     a,r7
        dec     a
        mov     r5,a
        mov     r3,#3
12$:    lcall   lookup
        jnc     13$
        movx    a,@dptr
        anl     a,#0x7F
        jz      13$
        inc     r0
13$:    inc     r5
        djnz    r3,12$
        inc     r4
        djnz    r1,11$
        mov     a,r6
        mov     r4,a
        mov     a,r7
        mov     r5,a
        lcall   lookup
        movx    a,@dptr
        cjne    r0,#3,14$
        sjmp    15$
14$:    cjne    r0,#4,16$
        anl     a,#0x7F
        jz      16$
        movx    a,@dptr
15$:    orl     a,#0x80
        movx    @dptr,a
16$:    inc     r7
        cjne    r7,#6,10$
        inc     r6
        cjne    r6,#17,9$

        ; pass 2: commit (bit 7 -> level 32 or 0), note whether anything changed
        mov     r0,#0
        mov     dptr,#LEVEL
        mov     r7,#NKEYS
17$:    movx    a,@dptr
        mov     r6,a
        anl     a,#0x7F
        jz      18$
        mov     a,#1
18$:    mov     r5,a            ; alive now
        mov     a,r6
        rlc     a
        clr     a
        rlc     a               ; alive next
        mov     r4,a
        xrl     a,r5
        orl     a,r0
        mov     r0,a
        mov     a,r4
        jz      19$
        mov     a,#FULL
19$:    movx    @dptr,a
        inc     dptr
        djnz    r7,17$

        ; new board after GEN_MAX generations, or STILL generations after it stopped changing
        mov     dptr,#GEN
        movx    a,@dptr
        inc     a
        movx    @dptr,a
        cjne    a,#GEN_MAX,20$
        ljmp    seed
20$:    mov     r1,a
        mov     a,r0
        jnz     21$
        mov     a,r1
        clr     c
        subb    a,#GEN_MAX-STILL
        jnc     21$
        mov     a,#GEN_MAX-STILL
        movx    @dptr,a
21$:    ljmp    RENDER

; ---- physical cell (r4 = column, r5 = row) -> C = 1 and DPTR = its level byte if it's a key ----
lookup:
        mov     a,r4
        cjne    a,#17,22$
22$:    jnc     26$
        mov     a,r5
        cjne    a,#6,23$
23$:    jnc     26$
        mov     a,r4
        mov     b,#6
        mul     ab
        add     a,r5
        mov     b,a             ; cell index
        rr      a
        rr      a
        rr      a
        anl     a,#0x1F
        mov     dptr,#keys
        movc    a,@a+dptr
        xch     a,b
        anl     a,#7
        inc     a
        mov     r2,a
        mov     a,b
24$:    rrc     a               ; C = bit (index & 7) of the key mask byte
        djnz    r2,24$
        jnc     26$
        mov     a,r4            ; LED column: the Shift row is wired in a different order
        cjne    r5,#4,25$
        jz      25$
        cjne    a,#13,27$
27$:    jnc     25$
        dec     a               ; physical 2..12 -> LED 1..11
        jnz     25$
        mov     a,#12           ; physical 1 (Z) -> LED 12
25$:    mov     b,#6
        mul     ab
        add     a,r5
        add     a,#LEVEL
        mov     dpl,a
        mov     dph,#0
        setb    c
        ret
26$:    clr     c
        ret

periods:
        .db     >FRAME_P0, <FRAME_P0, >FRAME_P1, <FRAME_P1, >FRAME_P2, <FRAME_P2
        .db     >FRAME_P3, <FRAME_P3, >FRAME_P4, <FRAME_P4
keys:                           ; bit (col*6 + row): there's a key at physical (col, row)
