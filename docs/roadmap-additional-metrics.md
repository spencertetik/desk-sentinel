# Desk Sentinel — Additional Metrics Roadmap

Running list of things we *could* track and surface on the dashboard, beyond
what's already built (live posture, coach nudges, presence insights). Each entry
notes the sensor, rough feasibility, and value. Not commitments — a menu to pull
from. Ordered roughly by value-for-effort.

## From the main camera (your desk camera) — already have the data

1. **Posture quality trends over time** *(easy, high value)*
   We already log `posture` per second. Add daily/weekly charts: % good vs
   forward-head vs slouching, best/worst hours, trend lines. Pure analytics on
   existing `metrics_samples`, same pattern as Presence Insights. Strong next
   step after presence.
2. **Time in good vs bad posture per session** *(easy)* — overlay posture quality
   onto the presence timeline (a session bar tinted by how upright you were).
3. **Slouch-onset timing** *(easy)* — how long into a sitting session before
   posture degrades (do you start slouching after ~30 min?). Behavioral insight.
4. **Away/return rhythm & break quality** *(easy)* — already have left/return
   events; surface average break length, longest unbroken stretch.

## From the main camera — needs new sensing (fuzzier)

5. **Screen-activity ROI** *(medium, low fidelity)* — frame-diff over the monitor
   regions (Mac Mini / MacBook displays) for a rough active/idle signal. Honest
   caveat: glare + oblique angle make this weak; the Leap gives a better
   active-work signal (see below).
6. **Eating/drinking** *(medium, fuzzy on camera)* — hand-to-mouth proximity from
   pose landmarks. Fuzzy from the overhead angle; the Leap's grab/reach detection
   is more reliable for the "reached for the mug" half.
7. **Look-at-screen vs look-away** *(medium)* — head/face orientation from pose to
   estimate focus vs distraction. Privacy-sensitive; derived numbers only.
8. **Fidget / movement level** *(easy-ish)* — variance of landmark positions as a
   restlessness/energy proxy.
9. **Second-person detection** *(easy)* — pose detects >1 person (someone stopped
   by); could pause tracking or log interruptions.

## From the Leap Motion (now working — original LMC via Gemini 5.20)

Confirmed streaming at ~130fps: palm/wrist/elbow/fingertip 3D positions, palm
velocity, grab & pinch. See [leap-motion-macos memory] for setup.

10. **Wrist ergonomics** *(high value, Leap-unique)* — wrist extension/deviation
    angle from wrist+elbow+palm geometry; flag sustained poor wrist posture (RSI).
    The camera cannot see this.
11. **Typing vs idle (true active-work)** *(high value)* — palm present in the
    keyboard zone + finger/palm velocity. Far better than the camera screen-ROI.
12. **Hand micro-breaks** *(high value)* — continuous hand-activity duration →
    "rest your hands" nudge, complementing the sit-break reminder.
13. **Reach / hydration** *(medium)* — grab events + hand leaving the zone →
    reaching for mug/can; could pair with a hydration nudge.

## Cross-cutting

- **Posture × activity correlation** — e.g. "your posture is worst during long
  uninterrupted typing stretches" (combine camera posture + Leap typing).
- **Daily/weekly digest** — a spoken or notification end-of-day summary.
- **Data retention / rollups** — if `metrics_samples` grows large, add an hourly
  rollup table so all these analytics stay fast.

## Privacy invariant (applies to everything)

No raw video or raw IR frames are ever persisted — only derived numbers and
events. Any new metric follows this rule.
