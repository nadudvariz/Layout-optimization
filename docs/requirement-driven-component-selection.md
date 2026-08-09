# Requirement-Driven Component Selection Prompt

## Overview

For every requirement, the system issues a separate API call to the language model. Each call consists of two messages:

- a **constant system message**, which defines the task, the selection constraint and the output schema;
- a **user message generated at runtime**, which carries the text of the current requirement and the list of pre-filtered candidate components.

The syntactic validity of the response is enforced by the `response_format` parameter of the API rather than by the prompt text alone. The semantic validity of the returned identifiers is verified afterwards by the calling code.

## System message

```text
You are an assistant that assigns components to kitchen requirements.
You must choose exclusively from the provided candidates (multi-label).
Provide the output in STRICT JSON format based on this schema:
{"matches": [{"component_id": str, "component_name": str,
              "score": float, "reason": str}]}.
The score must be a value between 0 and 1.
```

## User message template

Placeholders marked with `‹…›` are substituted at runtime.

```text
Requirement:
‹requirement_text›

Candidates:
‹candidates_json›

Choose the relevant ones (at least ‹min_keep›), and give a reason.
```

| Placeholder | Content |
| --- | --- |
| `‹requirement_text›` | Natural-language text of the requirement being processed. |
| `‹candidates_json›` | JSON array of the pre-filtered candidates, containing the fields `id`, `name`, `score`, `description` and `capabilities`; serialised with two-space indentation and without ASCII escaping. |
| `‹min_keep›` | Minimum number of matches the model is asked to return. |

The `score` field passed to the model is the similarity value produced by the preceding retrieval stage, rounded to four decimal places. It is provided as a hint only; the model is asked to return its own confidence value.

## Worked example

The candidate list is abridged to two entries for readability; in production runs the list typically contains a larger number of candidates.

```text
Requirement:
Hot food must be held at a minimum of 63 °C in the kitchen before it is served.

Candidates:
[
  {
    "id": "C-014",
    "name": "Bain-marie hot holding counter",
    "score": 0.8231,
    "description": "Water-bath hot holding unit for GN containers.",
    "capabilities": ["hot_holding", "gn_compatible"]
  },
  {
    "id": "C-027",
    "name": "Blast chiller",
    "score": 0.4110,
    "description": "Rapid cooling appliance for HACCP compliance.",
    "capabilities": ["blast_chilling"]
  }
]

Choose the relevant ones (at least 1), and give a reason.
```

## Call parameters

| Parameter | Value |
| --- | --- |
| `model` | GPT-5-mini--2025-08-07 |
| `response_format` | `{"type": "json_object"}` |
| `temperature` | 1 |
| Messages | System message and user message, in this order. |
