; Bad Apple lighting effect for the AULA F87 base firmware (base_f87_decrypted.bin).
;
; Plays a 1-bit video stored in free flash (0xDC00-0xEBFF) as lighting effect 6, a slot the stock
; firmware leaves empty. build.py prepends the settings (FRAME_P0..4, COL_R/G/B) and appends the video data
; (label `video`); patch_firmware.py --badapple installs the hooks:
;   0x179C  effect-init switch default 0x1B0E -> ba_init   (runs on every mode change; only acts for mode 6)
;   0x1B49  frame table entry for mode 6: LJMP 0x1DC8 (RET) -> LJMP ba_frame
;   0x4F79  Fn "next effect" skip of mode 6 (CJNE A,#6) -> CJNE A,#0xFF, so Fn reaches the effect
; The header (+0 init, +3 frame, +6 next, +9 mode) is the custom effect format, see docs/CUSTOM_EFFECTS.md.
;
; Video data, one item per frame period:
;   0x00        never used
;   n  (1..87)  n key indexes follow; each one toggles that key (index = LED col * 6 + row)
;   0x80 | n    the picture stays the same for n frames (n = 1..126)
;   0xFF        end: start over from black
;
; Firmware state used (all XRAM):
;   0x0017 + col*6 + row   key level 0..32 (the renderer 0x63E5 shows colour * level / 32 and then
;                          decrements every non-zero level, so lit keys are set back to 32 each frame)
;   0x0424 + (col*6+row)*3 key colour R, G, B
;   0x0300/0x0301          tick counter (hi, lo), incremented by the timer interrupt at 0x81EF
;   0x0D94                 speed setting 0..4 of the current effect (Fn speed keys / aulaf87.py -s)
;   0x0EC1..0x0EC3         our state; borrowed from the boot snake, which only runs at power-on

        .module badapple
        .area   BADAPPLE (ABS,CODE)
        .org    0xDC00

LEVEL   = 0x0017
COLOUR  = 0x0424
NKEYS   = 102               ; 17 LED columns x 6 rows
FULL    = 32
HOLD    = 0x0EC1
PTRH    = 0x0EC2
PTRL    = 0x0EC3
TICKH   = 0x0300
TICKL   = 0x0301
SPEED   = 0x0D94
MODE    = 0x0EC7
OURMODE = 6
RENDER  = 0x63E5
INITRET = 0x1B0E

        ljmp    ba_init         ; +0 entry for the init switch
        ljmp    ba_frame        ; +3 entry for the frame table
next:   ljmp    INITRET         ; +6 where init continues (patched to chain to another custom effect)
        .db     OURMODE         ; +9 which effect slot this is

; ---- effect init: reached for every mode the stock init switch has no case for ----
ba_init:
        mov     dptr,#MODE
        movx    a,@dptr
        cjne    a,#OURMODE,1$
        jnb     0x21,1$         ; 0x21 = "mode just changed, run init"
        clr     0x21
        setb    0x22            ; 0x22 = "run the frame handler"
        clr     0x32
        clr     0x55
        mov     dptr,#TICKH     ; start the frame clock from 0
        clr     a
        movx    @dptr,a
        inc     dptr
        movx    @dptr,a
        lcall   ba_reset
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

; ---- start over: white colours, all keys off, rewind ----
ba_reset:
        mov     dptr,#PTRH
        mov     a,#>video
        movx    @dptr,a
        inc     dptr
        mov     a,#<video
        movx    @dptr,a
        mov     dptr,#HOLD
        clr     a
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
        mov     dptr,#LEVEL
        mov     r5,#NKEYS
        clr     a
3$:     movx    @dptr,a
        inc     dptr
        djnz    r5,3$
        ljmp    RENDER

; ---- frame handler: called by the lighting engine all the time while mode 6 is active ----
ba_frame:
        mov     dptr,#SPEED     ; period = periods[min(speed, 4)]
        movx    a,@dptr
        cjne    a,#5,4$
4$:     jc      5$
        mov     a,#4
5$:     rl      a
        mov     r4,a
        mov     dptr,#periods
        movc    a,@a+dptr
        mov     r6,a            ; period hi
        mov     a,r4
        inc     a
        movc    a,@a+dptr
        mov     r7,a            ; period lo
        mov     dptr,#TICKL     ; ticks -= period, unless ticks < period
        movx    a,@dptr
        clr     c
        subb    a,r7
        mov     r5,a
        mov     dptr,#TICKH
        movx    a,@dptr
        subb    a,r6
        jc      6$
        movx    @dptr,a
        inc     dptr
        mov     a,r5
        movx    @dptr,a
        mov     dptr,#HOLD      ; still holding the last picture?
        movx    a,@dptr
        jz      decode
        dec     a
        movx    @dptr,a
6$:     ret

decode:
        mov     dptr,#PTRH
        movx    a,@dptr
        mov     r6,a
        inc     dptr
        movx    a,@dptr
        mov     dpl,a
        mov     dph,r6
        clr     a
        movc    a,@a+dptr
        inc     dptr
        cjne    a,#0xFF,7$
        ljmp    ba_reset        ; end of video: loop
7$:     jnb     0xE7,toggle     ; ACC.7 clear: a frame with changes
        anl     a,#0x7F         ; 0x80|n: this frame and n-1 more stay the same
        dec     a
        mov     r5,a
        lcall   save_ptr
        mov     dptr,#HOLD
        mov     a,r5
        movx    @dptr,a
        ret

toggle:
        mov     r5,a            ; number of keys that change
8$:     clr     a
        movc    a,@a+dptr
        inc     dptr
        mov     r2,dpl
        mov     r3,dph
        add     a,#<LEVEL
        mov     dpl,a
        clr     a
        addc    a,#>LEVEL
        mov     dph,a
        movx    a,@dptr
        jz      9$
        clr     a               ; on -> off
        sjmp    10$
9$:     mov     a,#FULL         ; off -> on
10$:    movx    @dptr,a
        mov     dpl,r2
        mov     dph,r3
        djnz    r5,8$
        lcall   save_ptr
        mov     dptr,#LEVEL     ; lit keys back to full level (the renderer decremented them)
        mov     r5,#NKEYS
11$:    movx    a,@dptr
        jz      12$
        mov     a,#FULL
        movx    @dptr,a
12$:    inc     dptr
        djnz    r5,11$
        ljmp    RENDER

save_ptr:                       ; DPTR -> PTRH/PTRL
        mov     r2,dpl
        mov     r3,dph
        mov     dptr,#PTRH
        mov     a,r3
        movx    @dptr,a
        inc     dptr
        mov     a,r2
        movx    @dptr,a
        ret

periods:                        ; ticks per frame for speed 0 (slow) .. 4 (fast), hi/lo
        .db     >FRAME_P0, <FRAME_P0, >FRAME_P1, <FRAME_P1, >FRAME_P2, <FRAME_P2
        .db     >FRAME_P3, <FRAME_P3, >FRAME_P4, <FRAME_P4

video:
