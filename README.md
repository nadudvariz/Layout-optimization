# Layout-optimization
This repository contains supplementary information for the article titled 'Integrating Domain Knowledge and User Requirements in Kitchen Layout Optimization'
[![DOI](https://zenodo.org/badge/1203833238.svg)](https://doi.org/10.5281/zenodo.22177804)

# Abstract
Layout design data sources exhibit a fundamental asymmetry: the challenge lies in processing structured, high-quality domain knowledge alongside task-specific natural language user requirements. To address this, we propose a hybrid evaluation framework for evolutionary algorithms (EAs) that quantifies constraint violations as virtual displacement costs. The framework is evaluated in the present study on four kitchen-layout optimization scenarios with task-specific user requirements and component sets. By integrating hard-coded domain rules with a fuzzy-logic-driven Abstract Syntax Tree (AST), the system enables a flexible yet explainable scoring mechanism. This approach allows for a granular penalty system for individuals, while also guiding local search heuristics through component-level diagnostic logging. The implementation of the AST results in a marginal reduction in convergence cost while significantly improving the relative dispersion of the algorithms. Within this kichen-layout benchmark, the evolutionary algorithms achieved lower execution times and aggregate penalty scores than the selected LLM chat applications. The six non-expert human-generated layouts were included only as an exploratory reference because of the small and demographically homogeneous participant sample.

## Supplementary materials

### LLM prompts

- [Predicate Generator Prompt](docs/predicate-generator-prompt.md)
- [Requirement-Driven Component Selection Prompt](docs/requirement-driven-component-selection.md)
- [Component Selector Prompt Using Predicates](docs/component-selector-predicates.md)

### Experimental materials

- [Instructions for Human Participants](docs/human-participant-instructions.md)
- [System Specification](docs/system-specification.md)
- [Evolutionary Algorithm Configurations](docs/evolutionary-algorithm-configurations.md)

### Algorithm Source Code

- [Genetic Algorithm](algorithms/genetic_algorithm.py)
- [Differential Evolution Algorithm](algorithms/differential_evolution_algorithm.py)
- [Bacterial Evolutionary Algorithm](algorithms/bacterial_algorithm_with_partitions.py)
- [Evolution Strategy Algorithm](algorithms/evolution_strategy_algorithm.py)
- [AST and Cost function](algorithms/algorithms_common.py)

### Sample Output 

The following files were generated during the execution of the Differential Evolution algorithm using Problemset1 and the heuristic-free case,
- while evaluating user requirements. [Results: DE, PS1, HF, with UR](DE_PS1_HF_withUR)
- without evaluating user requirements. [Results: DE, PS1, HF, without UR](DE_PS1_HF_withoutUR)

The original JSON files were subsequently converted to Parquet format to ensure manageable file sizes. The numerical prefix in the file names represents the initial population ID, while the suffix 'b' indicates that it contains the best solutions.

### Parquet output structure

The experimental output is provided in Parquet format. The Parquet files were generated from the original JSON result files to reduce storage requirements while preserving the information required for subsequent analysis.

Each `*_individuals_b.parquet` file contains the best solutions recorded during one optimization run. Each row represents one component of a recorded solution at a given generation. Consequently, a complete solution is represented by multiple consecutive rows, one for each component of the layout.

The main columns are organized as follows:

| Column(s) | Description |
|---|---|
| `run_rep` | Identifier of the optimization run, extracted from the original result filename. |
| `suffix` | Result-file suffix. The value `b` denotes files containing the recorded best solutions. |
| `gen` | Generation index of the recorded solution. |
| `indiv` | Rank of the recorded solution within the generation. For files containing one best solution per generation, this value is `0`. |
| `comp_idx` | Index of the component within the solution. |
| `component_json` | Serialized JSON representation of the original component object. The same component attributes are also provided as separate columns to facilitate tabular analysis. |
| `metric_0` | Total fitness (weighted penalty) value minimized by the evolutionary algorithm. |
| `metric_1` | Generation at which the corresponding fitness value was evaluated. |
| `metric_2` | Cumulative number of fitness-function evaluations at the time of the evaluation. |
| `name` | Name of the layout component. |
| `rel_x`, `rel_y` | Position of the component in the local coordinate system of its parent/container. |
| `rel_o` | Orientation of the component relative to its parent/container. |
| `x`, `y`, `orientation` | Derived global position and orientation of the component. |
| `w`, `d` | Width and depth of the component. |
| `a_name` | Name of the parent/container relative to which the component is positioned. |
| `fixed` | Indicates whether the component has a fixed position. |
| `wall_flag` | Wall-placement requirement: `1` = the component should be placed against a wall, `0` = it should be kept away from walls, and `-1` = no wall-placement restriction. |
| `res_location`, `res_w`, `res_d` | Definition of the reserved zone associated with the component. |
| `preferred_side`, `rel_preferred_side`, `connection_side` | Attributes describing the preferred component-to-container/wall relationship. |
| `overlaps`, `forbidden_overlaps` | Required and forbidden overlap relationships specified for the component. |
| `x_min`, `y_min`, `x_max`, `y_max` | Global bounding box of the component. |
| `res_x_min`, `res_y_min`, `res_x_max`, `res_y_max` | Global bounding box of the component's reserved zone. |
| `overlaps_points` | Penalty assigned for violating component-overlap requirements, including insufficient required overlap or undesired overlap. |
| `overlaps_reserved_points` | Penalty assigned when the component overlaps the reserved zone of another component. |
| `connection_points` | Penalty arising from violation of wall-placement requirements. |
| `llm_points` | Component-level share of the penalty arising from LLM-derived user-requirement constraints. |
| `coord` | Coordinate-system annotation used for the room component; not populated for the other components. |
| `changed` | Internal status flag initialized to `0`; it is not used by the Differential Evolution procedure. |

The total fitness value (`metric_0`) is obtained by accumulating the enabled penalty components, including penalties related to component overlap, reserved-zone intrusion, wall-placement requirements, and LLM-derived user-requirement constraints. The individual `*_points` columns provide the corresponding component-level penalty contributions.

## Repository structure

- docs/ – supplementary documentation, including the LLM prompts, instructions for human participants, the system specification, and the evolutionary algorithm configurations.
- algorithms/ – source code of the evolutionary algorithms and the common functions used for AST-based constraint evaluation and cost calculation.
- DE_PS1_HF_withUR/ – sample output of the Differential Evolution algorithm for Problem Set 1 in the heuristic-free setting, with user requirements included in the evaluation.
- DE_PS1_HF_withoutUR/ – corresponding sample output without user requirements included in the evaluation.
