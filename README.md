# hermes-a3-skills

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill tap published for
CSCI 599 (Agentic AI), Assignment 3. Original work by Vindhya Srinivasan.

| Skill | What it does |
|---|---|
| `ics-schedule-doctor` | Reads an `.ics` file or iCal URL; lists events, detects overlapping meetings, finds free slots, suggests the best slot for a task length. Helper script uses only the Python standard library; a synthetic sample calendar is included. |

## Install

```bash
hermes skills tap add vindhya-srinivasan/hermes-a3-skills
hermes skills install vindhya-srinivasan/hermes-a3-skills/ics-schedule-doctor
```

## Try it

```bash
hermes -z "Use the ics-schedule-doctor skill on its bundled sample calendar for 2026-11-16, 2 days, and find a 90-minute slot."
```

Contains no credentials or personal data; the sample calendar is synthetic. MIT licensed.
