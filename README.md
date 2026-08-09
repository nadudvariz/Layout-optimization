# Layout-optimization
This repository contains supplementary information for the article titled 'Integrating Domain Knowledge and User Requirements in Kitchen Layout Optimization'

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

### Sample Output 

The following files were generated during the execution of the Differential Evolution algorithm using Problemset1 and the heuristic-free case,
- while evaluating user requirements. [Results: DE, PS1, HF, with UR](DE_PS1_HF_withUR,
- without evaluating user requirements. [Results: DE, PS1, HF, without UR](DE_PS1_HF_withoutUR)

The original JSON files were subsequently converted to Parquet format to ensure manageable file sizes. The numerical prefix in the file names represents the initial population ID, while the suffix 'b' indicates that it contains the best solutions.
