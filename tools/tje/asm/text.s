| ToeJam & Earl Korean text renderer. Replaces the three glyph renderers:
|   0x27BF6  text strip, palette-remapped copy   -> render_remap
|   0x27CE4  text strip, verbatim copy           -> render_raw
|   0x1DED8  12-column speech bubble with a tail -> render_bubble
| A text strip is ceil(columns/4) sprite pieces of 4x2 tiles; the print
| routines call fixup_text_object so the object's piece list, VRAM tile
| count and hardware sprite count match (PIECE_LISTS holds lists for 1..8
| pieces, 84 bytes each). Keeping strips short keeps the per-frame tile
| staging buffer (8KB) from overflowing.
| C-style args after the movem (8 regs = 32 bytes + return address):
|   0x24(sp) string, 0x2A(sp) columns (word), 0x2E(sp) vram tile (word)
| Symbols NARROW_FONT, WIDE_FONT, BLANK_GLYPH, PIECE_LISTS come from --defsym.

	.text
	.globl	render_remap, render_raw, render_bubble
	.globl	fixup_text_object, fixup_text_object_alt

	.equ	COPY_REMAP, 0x27B54	| copies tiles, remapping palette 8/9/A/B
	.equ	COPY_RAW, 0xCAFC	| copies tiles verbatim
	.equ	TAIL_TILE, 0xAFEA0	| original glyph 27: speech bubble tail
	.equ	QUEUE_COUNT, 0xFFD92E
	.equ	QUEUE, 0xFFD8DC
	.equ	PIECE_LIST_SIZE, 84
	.equ	BUBBLE_STRIP, (25 << 16) | 12	| tiles queued : columns

| pieces = max(1, ceil(columns/4)); in: d5.w columns, a2 object.
| The _alt entry selects the second set of lists (piece flag byte 3, as the
| original 0xAFAEC list used by the third print routine).
fixup_text_object_alt:
	move.l	#PIECE_LISTS + 8 * PIECE_LIST_SIZE,%d1
	bra	1f
fixup_text_object:
	move.l	#PIECE_LISTS,%d1
1:	move.w	%d5,%d0
	addq.w	#3,%d0
	lsr.w	#2,%d0
	bne	2f
	moveq	#1,%d0
2:	move.b	%d0,0x2e(%a2)		| hardware sprites
	subq.w	#1,%d0
	mulu	#PIECE_LIST_SIZE,%d0
	add.l	%d1,%d0
	move.l	%d0,0x22(%a2)
	move.w	%d5,%d0
	addq.w	#3,%d0
	lsr.w	#2,%d0
	bne	3f
	moveq	#1,%d0
3:	lsl.w	#3,%d0
	move.b	%d0,0x2b(%a2)		| VRAM tiles
	rts

render_remap:
	movem.l	%d2-%d7/%a2-%a3,-(%sp)
	lea	COPY_REMAP,%a3
	moveq	#0,%d3			| strip size derived from the column count
	bra	render_body
render_raw:
	movem.l	%d2-%d7/%a2-%a3,-(%sp)
	lea	COPY_RAW,%a3
	moveq	#0,%d3
	bra	render_body
render_bubble:
	movem.l	%d2-%d7/%a2-%a3,-(%sp)
	lea	COPY_RAW,%a3
	move.l	#BUBBLE_STRIP,%d3
	pea	1
	pea	TAIL_TILE
	jsr	COPY_RAW
	addq.l	#8,%sp
render_body:
	movea.l	0x24(%sp),%a2
	move.w	0x2a(%sp),%d2
	move.w	0x2e(%sp),%d4
	tst.l	%d3
	bne	0f
	move.w	%d2,%d3			| pieces = max(1, ceil(columns/4))
	addq.w	#3,%d3
	lsr.w	#2,%d3
	bne	8f
	moveq	#1,%d3
8:	move.w	%d3,%d7
	lsl.w	#3,%d7			| tiles = pieces * 8
	swap	%d7
	lsl.w	#2,%d3			| columns = pieces * 4
	move.w	%d3,%d7
	move.l	%d7,%d3
0:	move.w	%d3,%d7
	sub.w	%d2,%d7			| total padding
	bge	1f
	moveq	#0,%d7
1:	move.w	%d7,%d6
	lsr.w	#1,%d6			| left pad
	sub.w	%d6,%d7			| right pad
	move.w	%d6,%d5
	bsr	emit_blanks
	move.w	%d2,%d5			| columns left
	bra	next_char
char_loop:
	moveq	#0,%d0
	move.b	(%a2)+,%d0
	bmi	wide_char
	subi.w	#0x20,%d0
	bcs	bad_narrow
	cmpi.w	#94,%d0
	bhi	bad_narrow
	lsl.l	#6,%d0			| 64 bytes per narrow glyph
	addi.l	#NARROW_FONT,%d0
	pea	2
	move.l	%d0,-(%sp)
	jsr	(%a3)
	addq.l	#8,%sp
	subq.w	#1,%d5
	bra	next_char
bad_narrow:
	bsr	blank_column
	subq.w	#1,%d5
	bra	next_char
wide_char:
	cmpi.w	#2,%d5
	blt	bad_wide
	andi.w	#0x7f,%d0
	mulu	#255,%d0
	moveq	#0,%d1
	move.b	(%a2)+,%d1
	subq.w	#1,%d1
	add.l	%d1,%d0
	lsl.l	#7,%d0			| 128 bytes per wide glyph
	addi.l	#WIDE_FONT,%d0
	pea	4
	move.l	%d0,-(%sp)
	jsr	(%a3)
	addq.l	#8,%sp
	subq.w	#2,%d5
	bra	next_char
bad_wide:
	addq.l	#1,%a2
	bsr	blank_column
	subq.w	#1,%d5
next_char:
	tst.w	%d5
	bgt	char_loop
	move.w	%d7,%d5
	bsr	emit_blanks
	lea	QUEUE_COUNT,%a0
	lea	QUEUE,%a1
	moveq	#0,%d0
	move.b	(%a0),%d0
	addq.b	#1,(%a0)
	add.w	%d0,%d0
	move.w	%d4,(%a1,%d0.w)
	moveq	#0,%d0
	move.b	(%a0),%d0
	addq.b	#1,(%a0)
	add.w	%d0,%d0
	swap	%d3
	move.w	%d3,(%a1,%d0.w)		| tiles queued for this strip
	movem.l	(%sp)+,%d2-%d7/%a2-%a3
	rts

emit_blanks:				| d5 = number of blank columns
	bra	2f
1:	bsr	blank_column
	subq.w	#1,%d5
2:	tst.w	%d5
	bgt	1b
	rts

blank_column:
	pea	2
	pea	BLANK_GLYPH
	jsr	COPY_RAW
	addq.l	#8,%sp
	rts

| ---------------------------------------------------------------------------
| Plane text (menus, level messages, game over). Replaces 0x9F6A(str), which
| wrote one name-table word per character at the VDP address the caller had
| just set. Every caller's control-port write is redirected to a set_cmd_*
| stub that records the address in PT_CMD and selects a mode:
|   0  legacy: original one-row 8x8 font (in-game HUD, present list)
|   1  Korean two-row text, glyph tiles streamed into the menu ring
|   2  Korean two-row text, glyph tiles streamed into the HUD ring
| ---------------------------------------------------------------------------
	.globl	plane_text, menu_begin
	.globl	set_cmd_d0_m0, set_cmd_d1_m0, set_cmd_imm_m0
	.globl	set_cmd_d0_m1, set_cmd_d1_m1, set_cmd_imm_m1
	.globl	set_cmd_d0_m2, set_cmd_d1_m2, set_cmd_imm_m2

	.equ	VDP_DATA, 0xC00000
	.equ	VDP_CTRL, 0xC00004
	.equ	CHAR_TO_GLYPH, 0x9E0E	| original ASCII -> 8x8 glyph index
	.equ	PT_CMD, 0xFFEFE0	| long: shadow of the name-table write command
	.equ	PT_CURSOR, 0xFFEFE4	| word: next free tile in the ring
	.equ	PT_MODE, 0xFFEFE6	| byte: see above
	.equ	PT_COUNT, 0xFFEFE8	| word: glyph cache entries in use
	.equ	PT_CACHE, 0xFFE800	| CACHE_MAX x (key.w, tile.w)
	.equ	PT_ROWBUF, 0xFFEA00	| 64 words top row, then 64 words bottom row
	.equ	CACHE_MAX, 96
	.equ	MENU_RING_START, 0x080	| free in menu scenes only
	.equ	MENU_RING_END, 0x200
	.equ	HUD_RING_START, 0x480	| top 16 blocks of the sprite VRAM pool,
	.equ	HUD_RING_END, 0x500	| withheld from the allocator by the build
	.equ	BLANK_WORD, 0x85B4	| original font tile 0: blank, priority, pal 0
	.equ	TILE_ATTR, 0x8000
	.equ	ROW_STEP, 0x800000	| +0x80 bytes of VRAM in the command's address field
	.equ	MENU_DRAW_RESUME, 0x23A4C

| Mode switch, register-preserving. A change of mode restarts that mode's ring.
.macro	ENTER_MODE mode, start
	cmpi.b	#\mode,PT_MODE
	beq	9f
	move.b	#\mode,PT_MODE
	move.w	#\start,PT_CURSOR
	clr.w	PT_COUNT
9:
.endm

.macro	SET_CMD_REG name, reg, mode, start
\name:
	move.l	\reg,PT_CMD
	move.l	\reg,VDP_CTRL
	ENTER_MODE \mode, \start
	rts
.endm

.macro	SET_CMD_IMM name, mode, start
\name:					| the command follows the jsr as a .long
	move.l	%a0,-(%sp)
	movea.l	4(%sp),%a0
	move.l	(%a0)+,PT_CMD
	move.l	PT_CMD,VDP_CTRL
	move.l	%a0,4(%sp)
	movea.l	(%sp)+,%a0
	ENTER_MODE \mode, \start
	rts
.endm

	SET_CMD_REG set_cmd_d0_m0, %d0, 0, 0
	SET_CMD_REG set_cmd_d1_m0, %d1, 0, 0
	SET_CMD_IMM set_cmd_imm_m0, 0, 0
	SET_CMD_REG set_cmd_d0_m1, %d0, 1, MENU_RING_START
	SET_CMD_REG set_cmd_d1_m1, %d1, 1, MENU_RING_START
	SET_CMD_IMM set_cmd_imm_m1, 1, MENU_RING_START
	SET_CMD_REG set_cmd_d0_m2, %d0, 2, HUD_RING_START
	SET_CMD_REG set_cmd_d1_m2, %d1, 2, HUD_RING_START
	SET_CMD_IMM set_cmd_imm_m2, 2, HUD_RING_START

menu_begin:				| hook at 0x23A44: a menu is being drawn
	move.b	#1,PT_MODE
	move.w	#MENU_RING_START,PT_CURSOR
	clr.w	PT_COUNT
	movem.l	%d2-%d4/%a2,-(%sp)	| displaced instructions
	movea.l	0x14(%sp),%a2
	jmp	MENU_DRAW_RESUME

plane_text:				| 4(sp) = string
	tst.b	PT_MODE
	bne	pt_korean
	move.l	%a2,-(%sp)		| legacy: exactly what 0x9F6A did
	movea.l	8(%sp),%a2
	bra	2f
1:	move.l	%d0,-(%sp)
	jsr	CHAR_TO_GLYPH
	addq.l	#4,%sp
	addi.w	#BLANK_WORD,%d0
	move.w	%d0,VDP_DATA
2:	moveq	#0,%d0
	move.b	(%a2)+,%d0
	bne	1b
	movea.l	(%sp)+,%a2
	rts

pt_korean:
	movem.l	%d2-%d7/%a2-%a4,-(%sp)
	movea.l	0x28(%sp),%a2
	lea	PT_ROWBUF,%a3
	lea	PT_ROWBUF+128,%a4
	moveq	#0,%d7			| columns written
pt_loop:
	moveq	#0,%d0
	move.b	(%a2)+,%d0
	beq	pt_done
	bmi	pt_wide
	subi.w	#0x20,%d0
	beq	pt_space
	bcs	pt_space
	cmpi.w	#94,%d0
	bhi	pt_space
	move.w	%d0,%d2			| cache key 0..94
	lsl.l	#6,%d0
	addi.l	#NARROW_FONT,%d0
	moveq	#2,%d1
	bsr	alloc_glyph
	move.w	%d3,%d0
	ori.w	#TILE_ATTR,%d0
	move.w	%d0,(%a3)+
	addq.w	#1,%d0
	move.w	%d0,(%a4)+
	addq.w	#1,%d7
	bra	pt_loop
pt_space:
	move.w	#BLANK_WORD,(%a3)+
	move.w	#BLANK_WORD,(%a4)+
	addq.w	#1,%d7
	bra	pt_loop
pt_wide:
	andi.w	#0x7f,%d0
	mulu	#255,%d0
	moveq	#0,%d1
	move.b	(%a2)+,%d1
	beq	pt_done			| malformed: NUL as trail byte
	subq.w	#1,%d1
	add.l	%d1,%d0
	move.w	%d0,%d2
	addi.w	#0x100,%d2		| cache key 0x100 + wide index
	lsl.l	#7,%d0
	addi.l	#WIDE_FONT,%d0
	moveq	#4,%d1
	bsr	alloc_glyph
	move.w	%d3,%d0
	ori.w	#TILE_ATTR,%d0
	move.w	%d0,(%a3)+		| TL
	addq.w	#1,%d0
	move.w	%d0,(%a4)+		| BL
	addq.w	#1,%d0
	move.w	%d0,(%a3)+		| TR
	addq.w	#1,%d0
	move.w	%d0,(%a4)+		| BR
	addq.w	#2,%d7
	bra	pt_loop
pt_done:
	move.l	PT_CMD,%d0
	move.l	%d0,%d1
	addi.l	#ROW_STEP,%d1
	move.l	%d1,VDP_CTRL		| bottom row first
	lea	PT_ROWBUF+128,%a4
	move.w	%d7,%d5
	subq.w	#1,%d5
	bmi	2f
1:	move.w	(%a4)+,VDP_DATA
	dbra	%d5,1b
2:	move.l	%d0,VDP_CTRL		| top row last: leaves the address after it
	lea	PT_ROWBUF,%a3
	move.w	%d7,%d5
	subq.w	#1,%d5
	bmi	4f
3:	move.w	(%a3)+,VDP_DATA
	dbra	%d5,3b
4:	moveq	#0,%d1
	move.w	%d7,%d1
	add.l	%d1,%d1			| 2 bytes per column
	swap	%d1			| into the command's address field
	add.l	%d1,%d0
	move.l	%d0,PT_CMD
	movem.l	(%sp)+,%d2-%d7/%a2-%a4
	rts

| alloc_glyph: d2.w = cache key, d1.w = tile count, d0.l = tile data in ROM.
| Returns d3.w = first VRAM tile. Uploads the tiles on a cache miss.
alloc_glyph:
	lea	PT_CACHE,%a0
	move.w	PT_COUNT,%d4
	subq.w	#1,%d4
	bmi	ag_miss
1:	cmp.w	(%a0),%d2
	beq	ag_hit
	addq.l	#4,%a0
	dbra	%d4,1b
	bra	ag_miss
ag_hit:
	move.w	2(%a0),%d3
	rts
ag_miss:
	move.w	PT_CURSOR,%d3
	move.w	#HUD_RING_END,%d4
	move.w	#HUD_RING_START,%d5
	cmpi.b	#1,PT_MODE
	bne	2f
	move.w	#MENU_RING_END,%d4
	move.w	#MENU_RING_START,%d5
2:	cmp.w	%d5,%d3
	bhs	7f
	move.w	%d5,%d3			| cursor below the ring: start over
7:	move.w	%d3,%d6
	add.w	%d1,%d6
	cmp.w	%d4,%d6
	bls	3f
	move.w	%d5,%d3			| ring full: wrap and forget the cache
	clr.w	PT_COUNT
3:	move.w	%d3,%d6
	add.w	%d1,%d6
	move.w	%d6,PT_CURSOR
	move.w	PT_COUNT,%d4
	cmpi.w	#CACHE_MAX,%d4
	bhs	4f
	lea	PT_CACHE,%a0
	add.w	%d4,%d4
	add.w	%d4,%d4
	move.w	%d2,(%a0,%d4.w)
	move.w	%d3,2(%a0,%d4.w)
	addq.w	#1,PT_COUNT
4:	moveq	#0,%d4			| VRAM write command for tile*32
	move.w	%d3,%d4
	lsl.l	#5,%d4
	move.l	%d4,%d5
	andi.l	#0x3fff,%d5
	swap	%d5
	move.l	%d4,%d6
	lsr.l	#8,%d6
	lsr.l	#6,%d6
	or.l	%d6,%d5
	ori.l	#0x40000000,%d5
	move.l	%d5,VDP_CTRL
	movea.l	%d0,%a1
	move.w	%d1,%d4
	lsl.w	#3,%d4			| 8 longs per tile
	subq.w	#1,%d4
5:	move.l	(%a1)+,VDP_DATA
	dbra	%d4,5b
	rts
