---
id: 0076
title: Demo Video and LinkedIn Post
stage: misc
date: 2026-10-19
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["demo-video", "linkedin", "showcase", "hugging-face-spaces"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .gitignore
 - history/prompts/001-verified-fix-agent/0076-demo-video-and-linkedin-post.misc.prompt.md
 - media/fixproof-demo.mp4 (local, git-ignored)
 - media/fixproof-demo-voice.mp4 (local, git-ignored)
 - media/fixproof-thumbnail.png (local, git-ignored)
 - media/linkedin-post.txt (local, git-ignored)
 - media/video-source/ (local, git-ignored; the scripts that render the video)
tests:
 - none (QA of the final video: frame contact sheets at about 40 points, full-resolution frames, stream check, narration timing with silencedetect)
---

## Prompt

```text
achaaa ab bat sunoo merii jo project abhii nvidiaa walaa deployy kiaa haiii us ki videoo banoo record karoo recording mayy batoo ya kis liaa haii kia kartaa haii kuch miss mat karnaaaa phir sath mujayy professional english mayy text bhii denaaaa dono linkedinn mayyy past karnaaa haiii kiaa haii ya project kis liaaa haiiiiii shuruuu karooooo
```

## Response snapshot

Claude recorded a 2:37 demo video of the live Hugging Face showcase
(https://ms5373268-fixproof.static.hf.space) and wrote a LinkedIn post in English.

- **Content, checked against README.md and the three recorded runs**: the problem (AI tools
  claim fixes without tests), the rule (no proof, no "Verified"; the harness labels results),
  the inputs (public GitHub repository plus an issue link, failing test, or plain-English
  description), the samples, why the public page plays labeled replays, then the real Flask run
  step by step (plan, set up with a baseline, reproduce with the source code locked until the
  test fails, fix, verify 3/3 with no regressions, report with file and line citations), safety,
  other features (CLI, web UI, parallel mode, benchmark runner), real results (3 bugs Verified
  with NVIDIA Nemotron 3 Super at $0 on a 4-CPU laptop; 2 of 3 confirmed by the official hidden
  tests), and the links. The runs are labeled as replays of real runs in personal mode, sped up.
- **How**: headless Chrome via Playwright opened the live page; an injected overlay added
  captions, a spotlight, a cursor, title cards, and a 1.25x "camera"; the recorded Flask events
  were played unchanged, at the video's pace. Chrome's screencast was too slow for smooth 1080p,
  so the page ran 3x slower and the frames were sped back up; a tiny invisible change every
  200 ms made sure the settled state of each animation was captured. Narration: the built-in
  Windows voice "Microsoft Zira Desktop", one clip per scene, placed at each scene's start.
- **Deliverables** in `media/` (git-ignored): `fixproof-demo.mp4` (1920x1080, 30 fps, H.264,
  burned-in captions, silent audio track), `fixproof-demo-voice.mp4` (the same with narration),
  `fixproof-thumbnail.png`, `linkedin-post.txt`, and `video-source/` with the scripts.
- **QA**: contact sheets and full-resolution frames of the final video, the stream check, and
  silencedetect (every narration clip starts within about 0.25 s of its scene). Two earlier
  renders were discarded: one at 1536x864 with lost end frames of animations, and a later one
  that stuttered while the machine was busy. Claude could not listen to the narration itself.

## Outcome

- ✅ Impact: a professional, captioned demo video and a ready-to-paste LinkedIn post that
  explain what FixProof is, why it exists, and what it does, with honest labels.
- 🧪 Tests: none; the video was checked frame by frame and its narration timing was measured.
- 📁 Files: `.gitignore` (adds `media/`), this PHR; the media files stay local.
- 🔁 Next prompts: the user posts on LinkedIn; a re-render could add short pauses at each
  spotlighted line (already in the scripts), when the machine is idle.
- 🧠 Reflection: check the capture's real resolution and frame timing before polishing visuals;
  screencast frames come at the viewport size in CSS pixels and can drop an animation's end.

## Evaluation notes (flywheel)

- Failure modes observed: screencast resolution ignored the device scale factor; final frames of
  animations were lost; a render stuttered under memory pressure (about 0.4 GB free).
- Graders run and results (PASS/FAIL): frame QA PASS; stream check PASS; narration timing PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): render with the user's other apps closed.
