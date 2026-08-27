# SoundType — Roadmap (expert council synthesis 2026-08-21)

Synthesis of six independent reports: research (silero-VAD in practice,
Parakeet P&C, Spokenly reverse engineering) + experts (architect, ASR/ML,
mobile Linux UX). Full reports live in the session logs; this is the action
plan.

## Key council findings

1. **OpenStore accepts unconfined FOSS through manual review** (precedents:
   UT Tweak Tool, Waydroid Helper). The "integration install button in the
   app with a PIN popup" idea is an accepted pattern on UT (QProcess
   `sudo -S`).
2. **Hotwords are already in our sherpa-onnx 1.13.6** (PR #3077, TDT
   supported): a custom term dictionary = configuration, not an upgrade.
   Cost: beam search drops RTFx 2-4x — measure first.
3. **Pinning the language on Parakeet v3 is fundamentally impossible**
   (NVIDIA issue closed) — the defenses against "drifting into English" are
   long segments (done in 08b5204), hotwords, and post-replacements.
4. **Paths from /etc/system-image/writable-paths survive OTA** — the
   foundation for auto-restoring the keyboard patch.
5. **Upstream is realistic**: lomiri-keyboard is alive (release 18.08.2026),
   no voice threads in the tracker, demand is documented (the SOTY author
   asked for integration). The winning shape is a neutral D-Bus "dictation
   provider", not "SoundType into upstream". Both experts arrived at this
   independently.
6. **Our streaming goes deeper than the benchmark**: Spokenly's local models
   insert text only after the button is released. Streaming is the killer
   feature, but it needs a "trust package" (undo, preedit).
7. **silero_te has no official ONNX** (torch.package only) → R&D export on
   the desktop before integration. Alternative/complement: GigaAM-v3 e2e
   (SOTA on pure Russian, built-in punctuation+normalization, sherpa
   conversions on HF) as a switchable profile.

## Phases

### Phase 1 — "Trust in streaming" (our code, no migrations)
- [ ] **Undo last phrase**: a button/gesture that rolls back the last
      committed segment with backspaces (we know the length). Removes the
      main fear of streaming. (M)
- [ ] **Smart spacing**: space/capitalization from the surrounding text when
      inserting mid-text, after punctuation, after emoji. (S)
- [ ] **Password/URL fields**: force-disable dictation in `ImhHiddenText`;
      a glitch-free mode in url/search. Bonus: a security argument for the
      OpenStore review. (S)
- [ ] "New line" by voice + inhibit screen dimming while recording. (S)

### Phase 2 — "Quality" (one change at a time)
- [x] **Eval harness FIRST** (#6): corpus of real dictations (ru + mixed),
      reference transcripts, WER/CER + term-accuracy on jiwer, whole|vad
      runners on sherpa-onnx. Done — multiplies everything else. (S)
- [x] **Model profiles + GigaAM-v3** (#12, v0.9.0): selectable Russian
      (GigaAM-v3 e2e int8) / multilingual (Parakeet) profiles. GigaAM is the
      daily driver and gives **punctuation and ё out of the box** — which
      retires several items below. (M)
- [ ] **Post-replacement module** (#8): a transliteration glossary
      («депло»→«deploy») + "add replacement" with a tap from history;
      case-insensitivity via casefold, Cyrillic word boundaries. The one
      remaining P2 — the real remaining quality value. (S-M)
- [~] **Hotwords + modified_beam_search** (#7): downgraded — ~80% covered by
      the post-replacement glossary (#8) at zero decode cost, vs beam search
      2-4x greedy on the N10. Pursue only if #8 proves insufficient. (M)
- [x] ~~**Yoficator** (#9)~~ — **dropped**: premise was "Parakeet lacks ё";
      GigaAM (the primary Russian profile) restores ё natively. Parakeet-only
      concern, not worth it.
- [x] ~~AGC/gain before VAD (#10)~~ — **dropped (measured negative)**: agg WER
      +1.70pp, quiet clips +5.18pp; gain doesn't change SNR and amplified
      noise moves VAD boundaries.
- [x] ~~silero_te → ONNX for Russian punctuation (#11)~~ — **dropped**: GigaAM
      punctuates natively; silero_te is a torch.package + CC BY-NC dead-end.
- [x] ~~GTCRN denoise before VAD (#13)~~ — **dropped**: same class as #10
      (pre-VAD processing), high regression risk on clean audio; revisit only
      with a real noisy-environment A/B win.
- [x] ~~v1.2 overlap+LCS at segment boundaries (#14)~~ — **dropped (measured
      negative)**: per-phrase cold decode re-transcribes the overlap
      differently → LCS misses → garbage; agg WER +0.58..+2.12pp, boundary
      damage up to 81%. Infra kept behind OVERLAP=0.0.

### Phase 3 — "Architecture" (architect's order: API → shim → engine → OTA)
- [ ] **D-Bus API `org.soundtype.Engine1`**: a versioned contract
      (StartSession/StopSession/GetState + signals). Gives a CLI for
      free. (S)
- [ ] **Loader shim**: the keyboard patch shrinks to a Loader + SpaceKey
      hooks; all logic in ~/.soundtype/kbd/ — updates without root, OTA
      barely a threat. (M)
- [ ] **Single engine**: the app becomes a D-Bus client of the daemon (no
      second ~1 GB copy, one audio path). Requires unconfined (phase 4). (M)
- [ ] **OTA survival**: a user unit checks system file hashes on boot →
      notification → "restore with one button"; level C (fully automatic via
      writable-paths) — after on-device verification, with strict
      self-checks (root-owned, immutable, hash manifest). (M)
- [ ] Preedit instead of per-character commit (Maliit composing text):
      partials shown as an underlined draft, commit on the final; the
      per-character mode stays as a fallback setting. (M)

### Phase 4 — "People" (distribution)
- [ ] **Unconfined + in-app integration installer** (the UT Tweak Tool
      pattern: "what will change" screen → PIN → patch → done). (M)
- [ ] **OpenStore**: apply via the admins' TG group (repo + build +
      privilege justification); the store page sells the confined value
      (clipboard+history), integration is an optional wizard inside. "Local
      Only / works in airplane mode" — first paragraph. (M)
- [ ] Download onboarding: warning on cellular, resume, free-space
      indicator. (S-M)
- [ ] Announcement on forums.ubports.com: "the first keyboard dictation on
      UT". (S)

### Phase 5 — "Strategy"
- [ ] **RFC to lomiri-keyboard**: issue + Matrix — a generic D-Bus dictation
      provider (a microphone button + a thin client in the keyboard, any
      provider; SOTY is an ally). Our patches are the working prototype and
      the bridge until the merge. (M to propose / L to land)
- [ ] Call/BT routing: auto-stop on an incoming call, default source =
      phone microphone (SCO 8/16 kHz ruins recognition). (M)
- [ ] Convergence: a dictation toggle in the top panel indicator (hold-space
      is physically unavailable with a hardware keyboard,
      oskEnabled=false). (S)

### Not doing (council decision)
- The full spoken-punctuation set (the model punctuates on its own;
  homonymy); double-tap activation (no demand); re-dictating a phrase (v2+);
  cloud engines/BYOK (against the positioning).
