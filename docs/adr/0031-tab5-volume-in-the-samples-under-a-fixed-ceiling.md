# 0031. The Tab5's volume is applied to the samples, under a fixed ceiling, after a compressor

- Status: Accepted
- Date: 2026-10-21
- Related: FR-0.30, ADR 0030

## Context
Loud noise reached the owner twice during development, so the Tab5 must start quiet and must never clip. Read from M5Unified's source, its output is `sample × 2 × magnification × master² × channel² / 2³⁶`, clipped to 16 bits: a square law in the volume, easy to push past full scale. The speaker codec's own outputs are already at their maximum (+4.5 dB). Piper's speech already peaks at full scale (RMS 0.13–0.17), so it can't simply be scaled up. At M5Unified's default boost of 4 the top of a clean range was too quiet for the owner.

## Options considered
- M5Unified's volume (`setVolume`): square law, clips past a point, and its loudness depends on settings that are easy to get wrong.
- Volume applied to the samples by the Tab5, with M5Unified fixed where a full-scale sample just fits.
- On top of that, a compressor: boost everything, then pull the peaks back under full scale, so quiet syllables come up.

## Decision
M5Unified is fixed at magnification 8, master 255 and channel 255, where a full-scale sample comes out at 0.98 of the range. Each 40 ms chunk then goes through `makeLouderAtVolume`: a 2× boost, a limiter at 0.95 of full scale (its peak follower includes the current sample, so nothing passes it) that lets go over 60 ms, then the volume bar's linear factor. The bar is drawn by the Tab5 in the bottom 80 px of the screen, handled on the Tab5 even with the laptop off, saved on the Tab5 (`Preferences`, namespace `kiki`, key `vol`), and starts at 5%.

## Consequences
+ No bar position can clip; a new Tab5 starts nearly silent.
+ About +6 dB on quiet syllables over the earlier clean ceiling; the owner found it loud enough.
- Compressed speech can sound slightly squashed.
- The 1 W speaker is the real limit; the Tab5's headphone jack (to a powered speaker) is untried.
