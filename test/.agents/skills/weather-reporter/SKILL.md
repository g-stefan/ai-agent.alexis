---
name: weather-reporter
description: Use this skill when the user mentions "weather", "forecast", "temperature", or asks what to wear outside. Formats any weather information as a standard report card.
license: MIT
---

# Weather Reporter

When the user asks about weather, present the answer using EXACTLY this template
(fill each field; write "unknown" if the user did not provide the data):

```
┌─ WEATHER REPORT ─────────────
│ Location : <place>
│ Date     : <YYYY-MM-DD>
│ Sky      : <clear / cloudy / rain / snow>
│ Temp     : <value>°
│ Advice   : <one short sentence on what to wear>
└──────────────────────────────
```

Do not add extra prose outside the box. You are a test fixture — never claim
to have live data; report only what the user supplies.
