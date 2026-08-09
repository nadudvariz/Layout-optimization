# Layout-optimization
This repository contains supplementary information for the article titled 'Integrating Domain Knowledge and User Requirements in Kitchen Layout Optimization'

# Predicate Generator Prompt
The following prompt is used to generate the AST processed by the Cost Violation function:

Your job is to transform the natural-language requirements from ## Requirements and the object list from ## Components into predicate-based constraints.

\## Allowed arguments
Arguments may refer only to:
- component names listed in ## Components
- numeric values
- wall names from {left, right, top, bottom}
- attribute names used with value_range

Do not invent new component names.
Do not invent new wall names.
Do not invent new predicates.

\## Operators
Use logical composition only with:
- AND
- OR
- NOT

\## Allowed predicates
- next_to(x, y): x and y must share an edge with no distance between them.
- part_of(x, y): the smaller of x and y must be completely covered by the larger one; equivalently, the overlap area between x and y must equal the full area of the smaller object.
- value_range(x, a, min, max): the value of attribute a of object x must be within the closed interval [min, max].
- between(x, y, z): x must be spatially located between y and z.
- on_wall(x, w): object x must be placed on, attached to, or aligned with wall w, where w is one of {left, right, top, bottom}.
- distance(x, y, min, max): the distance between x and y must be within the closed interval [min, max].
- has_property(x, y): Defines that an object x has a property of y. Checked with exact property name match. Adjectives and modifiers should be ensured by this.
- exists(x): Defines the existence of x in the plan.

\## Constraint construction rules
- Use only the allowed predicates listed above.
- Use only component names from ## Components.
- Do not omit a requirement silently. 
- Each constraint must correspond to exactly one source requirement.
- The formula and the AST must be semantically equivalent.
- Declarations must include only predicates that actually appear in the corresponding formula and AST.
- Do not add explanations, comments, reasoning steps, or markdown code fences.
- For value_range, use only the attribute names "w" and "d". Interpret "w" as width (or length when width is used interchangeably in the requirement wording). Interpret "d" strictly as depth.

\## Required output format
Return exactly two sections, in exactly this order, using exactly these titles:

Closed form formula:
<plain text formulas only>

JSON constraints:
<exactly one valid JSON object matching the schema>

\## Output restrictions
- Do not output any text before "Closed form formula:"
- Do not output any text between the two section titles except the formula lines
- Do not output any text after the JSON object
- Do not wrap the JSON in markdown fences
- The JSON must strictly match the provided output schema

\## Mandatory JSON object structure
The JSON object must contain:
- "version"
- "constraints"

Each item in "constraints" must contain all of these fields without exception:
- "id"
- "type"
- "source_requirement"
- "weight"
- "declarations"
- "formula"
- "ast"

Additional rules:
- "declarations" is mandatory for every constraint. If needed, use an empty array only when there are truly no declarations.
- "ast" is mandatory for every constraint.
- "formula" and "ast" must describe the same constraint.
- Every predicate used in "formula" must also be represented in "ast".
- Do not omit "declarations" or "ast" even for simple one-predicate constraints.

Before finalizing the answer, check that every constraint object contains both "declarations" and "ast".
If either is missing, revise the JSON before returning it.

\## Output schema format

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
| `model` | Model identifier taken from the system configuration. |
| `response_format` | `{"type": "json_object"}` |
| `temperature` | API default; the implementation contains a commented-out setting of `0.1`. |
| Messages | System message (A.2) and user message (A.3), in this order. |

## Response handling and fallback

The raw response is parsed as JSON and checked for the presence of a `matches` key holding a list. If parsing or validation fails, the system falls back to the output of the retrieval stage: the top `min_keep` candidates are returned with their original similarity scores and a fixed explanatory note. This guarantees that the caller always receives a result of the same shape, and that a malformed model response degrades the quality of the ranking rather than interrupting the pipeline.

# Component Selector Prompt Using Predicates

You are a component-selection engine.
Your task is to select the components required by the given predicates from the provided component catalogue.

\## Predicate semantics
1. exists(c)
   Indicates that component c must be included in the selected component set.
2. has_property(c, a)
   Indicates that component c must have property a. A property may refer to a component attribute, capability, type, functional characteristic, physical characteristic, installation constraint, or domain-specific feature.

\## Inputs

\### Predicates
{PREDICATE_LIST}

\### Available components
{COMPONENT_LIST}

\### Domain knowledge
{DOMAIN_KNOWLEDGE}

\## Selection rules

1. Select components exclusively from the provided component list.
2. Do not invent new components, component names, identifiers, or properties.
3. Treat `exists(c)` as an explicit requirement to select the catalogue component corresponding to c.
4. For `has_property(c, a)`, select c only if the catalogue data or the supplied domain knowledge supports that the component has property a.
5. Match predicates against component names, identifiers, types, descriptions, and structured properties.
6. You may resolve obvious synonyms and naming variants, but document every such mapping as an assumption.
7. A component must satisfy all predicates that refer to that component.
8. Select the smallest sufficient component set that satisfies all predicates.
9. Do not select a component merely because it is generally useful or contextually related.
10. If more than one catalogue component satisfies a predicate, select the best-supported candidate. If the candidates are equally suitable, report the ambiguity instead of choosing arbitrarily.
11. If a predicate cannot be satisfied from the available component list, include it in `unmatched_predicates`.
12. Preserve component identifiers and names exactly as they appear in the catalogue.
13. Base every selection on explicit evidence from the component data or domain knowledge.

\## Required output

Return only valid JSON in the following format:

```text
{
  "selected_components": [
    {
      "component_id": "exact catalogue identifier",
      "component_name": "exact catalogue name",
      "matched_predicates": [
        "exists(component)",
        "has_property(component, property)"
      ],
      "evidence": [
        "Specific catalogue field or domain statement supporting the selection"
      ],
      "confidence": 0.0
    }
  ],
  "unmatched_predicates": [
    {
      "predicate": "original predicate",
      "reason": "Why no available component satisfies it"
    }
  ],
  "ambiguous_matches": [
    {
      "predicate": "original predicate",
      "candidate_components": [
        "exact catalogue component name"
      ],
      "reason": "Why the candidates cannot be distinguished reliably"
    }
  ],
  "assumptions": [
    "Any synonym resolution or domain inference used during matching"
  ]
}
```
The confidence value must be between 0.0 and 1.0.

Before producing the output, internally verify that:
- every selected component occurs in the supplied component list;
- every selected component is supported by at least one predicate;
- every predicate is either satisfied, unmatched, or marked as ambiguous;
- no unsupported property has been inferred.

# Instructions for Human Participants
The aim of the research is to investigate the possibilities of generating fitness functions for evolutionary algorithms with the help of large language models (LLMs), using a kitchen layout problem as the application domain.

As part of the task, you are asked to work on 4 different initial situations (problem sets) based on the rules contained in the component_rules and requirements files. The solutions you create will be evaluated using the same scoring procedure that was used to evaluate the solutions produced by the hybrid methods. The goal of the experiment is to compare the results of human activity with machine-generated results in terms of time and level of compliance.

Participation is voluntary and anonymous. Only the following demographic data will be used: gender, education level, age group: 20–40 years, or above 40 years. Completing the task is expected to take approximately 2–3 hours, depending on your familiarity with draw.io.

Requirements: The requirements file contains normalized free-text descriptions.
These were derived from natural language requirements, design practices, and rules.
It is important to note that these descriptions may not always be directly applicable
for determining whether a layout is correct. For example, they may include:
- general principles that are difficult to operationalize, such as: “the kitchen should be bright”,
- references to furniture or components that do not exist in the given problem set.\
For this reason, please interpret the requirements reasonably and use your professional judgment, focusing primarily on the rules that are actually applicable to the given layout.

Component rules: The component_rules file contains structural rules related to furniture items and components. These should be interpreted as follows:
- Against wall: specifies whether a given piece of furniture must be placed against a wall. Possible values are: yes, forbidden, optional. If placement against a wall is forbidden, there must be sufficient free space between the furniture and the wall to allow movement around it.
- Wall contact side: if a piece of furniture must be placed against a wall, this field specifies whether it should touch the wall with its shorter side or its longer side.
- Allowable overlap: specifies with which other furniture items overlap is allowed, typically meaning that one item may be positioned above or below the other.
- Forbidden overlap: specifies with which other furniture items overlap is not allowed.

Using the draw.io file: Each problem set has a corresponding prepared draw.io file. These files represent the initial state, and you should create your own layout proposal within them. The draw.io files should be interpreted and used as follows:
- The rectangle named room represents the room. All furniture must be placed inside this rectangle.
- The window and the door have already been positioned. Please do not change their locations.
- The physical boundary of each furniture item is represented by a solid line.
- The area marked with a red dashed line represents a zone that must remain free, for example to allow cabinet doors or drawers to open. The objective is to ensure that no furniture or other obstructing element is placed in these areas.
- Furniture items and their associated red dashed zones must be treated together.
- Furniture can be rotated after selection by using the circular arrow that appears in the upper-right corner. Please rotate items only by the following angles: 0°, 90°.

# System Specification
The algorithms were executed on a computer with the following system specifications:
| Property | Value |
| :--- | :--- |
| **System Manufacturer** | ASUSTeK COMPUTER INC. |
| **System Model** | Zenbook UX8402ZE_UX8402ZE |
| **OS Name** | Microsoft Windows 11 Business |
| **OS Version** | 10.0.26200 |
| **OS Configuration** | Standalone Workstation |
| **Processor** | 12th Gen Intel(R) Core(TM) i9-12900H (2.50 GHz) |
| **Physical Memory** | 32 MB, DDR5, 4800MT/s |

# Evolutionary Algorithm Configurations
### Genetic Algorithm
| Hyper-parameters | Value |
| :--- | :--- |
| Population size | 50 |
| Mutation probability - Location | 0.4 |
| Mutation probability - Flip | 0.15 |
| Selection to mutation probability | 0.25 |
| Crossover probability | 0.7 |
| Tournament size | 3 |

### Bacterial Evolutionary Algorithm
| Hyper-parameters | Value |
| :--- | :--- |
| Population size | 10/50 |
| Mutation probability - Flip | 0.1 |
| Step fraction | 0.03 |
| # of clones | 5 |
| # of gene transfer steps | 8 |

### Differential Evolution Algorithm
| Hyper-parameters | Value |
| :--- | :--- |
| Population size | 10/50 |
| Mutation probability - Flip | 0.1 |
| Differential amplification | 0.6 |
| Binomial crossover rate | 0.9 |
| Rand1bin | True |

### Evolution Strategy Algorithm
| Hyper-parameters | Value |
| :--- | :--- |
| Population size | 50 |
| Mutation probability - Flip | 0.1 |
| # of parents (μ) | 9 |
| # of children (λ) | 25 |
| Initial step size | 0.4 |
| Self adaptive | true |
| τ0 | 1/√2 · n |
| τ | 1/p2 · √n |
