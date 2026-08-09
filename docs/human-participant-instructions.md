# Instructions for Human Participants
The aim of the research is to investigate the possibilities of generating fitness functions for evolutionary algorithms with the help of large language models (LLMs), using a kitchen layout problem as the application domain.

As part of the task, you are asked to work on 4 different initial situations (problem sets) based on the rules contained in the component_rules and requirements files. The solutions you create will be evaluated using the same scoring procedure that was used to evaluate the solutions produced by the hybrid methods. The goal of the experiment is to compare the results of human activity with machine-generated results in terms of time and level of compliance.

Participation is voluntary and anonymous. Only the following demographic data will be used: gender, education level. Completing the task is expected to take approximately 2–3 hours, depending on your familiarity with draw.io.

Requirements: The requirements file contains normalized free-text descriptions.
These were derived from natural language requirements, design practices, and rules.
It is important to note that these descriptions may not always be directly applicable
for determining whether a layout is correct. For example, they may include:
- general principles that are difficult to operationalize, such as: “the kitchen should be bright”,
- references to furniture or components that do not exist in the given problem set.\
For this reason, please interpret the requirements reasonably and use your judgment, focusing primarily on the rules that are actually applicable to the given layout.

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
