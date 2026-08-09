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
| Population size | 50 |
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
