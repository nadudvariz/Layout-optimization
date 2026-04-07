# Layout-optimization
This repository contains supplementary information for the article titled 'Integrating Domain Knowledge and User Requirements in Layout Optimization'

# Rule generator prompt
The following prompt is used to generate the AST processed by the Cost Violation function:

Your job is to transform the natural-language requirements from ## Requirements and the object list from ## Components into predicate-based constraints.

## Allowed arguments
Arguments may refer only to:
- component names listed in ## Components
- numeric values
- wall names from {left, right, top, bottom}
- attribute names used with value_range

Do not invent new component names.
Do not invent new wall names.
Do not invent new predicates.

## Operators
Use logical composition only with:
- AND
- OR
- NOT

## Allowed predicates
- next_to(x, y): x and y must share an edge with no distance between them.
- part_of(x, y): the smaller of x and y must be completely covered by the larger one; equivalently, the overlap area between x and y must equal the full area of the smaller object.
- value_range(x, a, min, max): the value of attribute a of object x must be within the closed interval [min, max].
- between(x, y, z): x must be spatially located between y and z.
- on_wall(x, w): object x must be placed on, attached to, or aligned with wall w, where w is one of {left, right, top, bottom}.
- distance(x, y, min, max): the distance between x and y must be within the closed interval [min, max].

## Constraint construction rules
- Use only the allowed predicates listed above.
- Use only component names from ## Components.
- Do not omit a requirement silently. 
- Each constraint must correspond to exactly one source requirement.
- The formula and the AST must be semantically equivalent.
- Declarations must include only predicates that actually appear in the corresponding formula and AST.
- Do not add explanations, comments, reasoning steps, or markdown code fences.
- For value_range, use only the attribute names "w" and "d". Interpret "w" as width (or length when width is used interchangeably in the requirement wording). Interpret "d" strictly as depth.

## Required output format
Return exactly two sections, in exactly this order, using exactly these titles:

Closed form formula:
<plain text formulas only>

JSON constraints:
<exactly one valid JSON object matching the schema>

## Output restrictions
- Do not output any text before "Closed form formula:"
- Do not output any text between the two section titles except the formula lines
- Do not output any text after the JSON object
- Do not wrap the JSON in markdown fences
- The JSON must strictly match the provided output schema

## Mandatory JSON object structure
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

## Output schema format
