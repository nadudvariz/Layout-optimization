from __future__ import annotations
from typing import List, Dict, Any, Tuple
import random, time, copy
from schemas.heuristic_schema import HEURISTICS_REGISTRY
from models import ModelParams, Room
from util.io_evolution import save_the_indiv
from algorithms.algorithms_common import (create_relation_df, _effective_size_for_individual, random_center_in_container,
    preferred_container_side_for_component, compute_reserved_zone, build_structure_graph,)

Individual = List[Dict]

class bacterial_algorithm:
    def __init__(
        self,
        objects: List[Dict[str, Any]],
        room: Room,
        project_name: str,
        solution_name: str,
        heuristics: List[Dict[str, Any]] | None = None,
        constraints: List[Dict[str, Any]] | None = None,
        init_population: List[Individual] | None = None,
        init_population_file: str | None = None,
        fitness=None,
        overlap_enabled: bool = False,
        wallfit_enabled: bool = False,
        log_mode: bool = False,
        results_dir: str | None = None,
    ):
        self.objects = objects
        self.room = room
        self.project_name = project_name
        self.solution_name = solution_name
        self.heuristics = heuristics or HEURISTICS_REGISTRY
        self.constraints = constraints
        self.init_population = init_population
        self.init_population_file = init_population_file
        self.fitness_obj = fitness
        self.fitness = fitness.calculate_weight_sum
        self.fitness_count = fitness.get_usages
        self.log_mode = log_mode
        self.overlap_enabled = overlap_enabled
        self.wallfit_enabled = wallfit_enabled
        self.results_dir = results_dir

        # create_relation_df may overwrite wall flags; we cache them by component name
        self._wall_by_name: dict[str, int] = {}

        # graph used for hierarchical (overlaps) structures
        self.structure_graph = build_structure_graph(self.objects)

    # ---------------------------------------------------------------------
    # Helpers for the new schema
    # ---------------------------------------------------------------------
    def _get_wall_flag(self, p: Dict[str, Any]) -> int:
        """Wall flag with create_relation_df overrides (same logic as GA)."""
        name = p.get("name")
        if name in self._wall_by_name:
            return int(self._wall_by_name[name])
        return int(p.get("wall_flag", 0))

    def recalculate_globals(self, indiv: Individual) -> None:
        """Recomputes global geometry fields from rel_x/rel_y and hierarchy.

        This is a line-by-line compatible copy of the logic in genetic_algorithm.py
        (minor refactors only). The BEA relies on it after any mutation/gene-transfer.
        """
        indiv_dict = {p["name"]: p for p in indiv}
        for comp in indiv:
            if comp.get("fixed"):
                continue

            parent = indiv_dict[comp["a_name"]]

            # effective container size (in its own orientation)
            a_w = parent["w"]
            a_d = parent["d"]
            a_w, a_d = (a_w, a_d) if (parent.get("orientation", 0) % 180) == 0 else (a_d, a_w)

            # global center of parent
            a_x, a_y = parent["x"], parent["y"]
            a_preferred_side = parent.get("preferred_side", "top")

            # component orientation is relative+parent (mod 180)
            orientation = (int(comp.get("rel_o", 0)) + int(parent.get("orientation", 0))) % 180
            comp["orientation"] = orientation

            eff_w, eff_d = _effective_size_for_individual(comp)
            rel_x, rel_y = float(comp.get("rel_x", 0.0)), float(comp.get("rel_y", 0.0))

            # Global x,y from container coordinate system, based on parent's preferred_side
            if a_preferred_side == "top":
                x = a_x - a_w / 2 + rel_x
                y = a_y - a_d / 2 + rel_y
            elif a_preferred_side == "right":
                x = a_x + a_w / 2 - rel_y
                y = a_y - a_d / 2 + rel_x
            elif a_preferred_side == "bottom":
                x = a_x + a_w / 2 - rel_x
                y = a_y + a_d / 2 - rel_y
            elif a_preferred_side == "left":
                x = a_x - a_w / 2 + rel_y
                y = a_y + a_d / 2 - rel_x
            else:
                # fallback
                x = a_x - a_w / 2 + rel_x
                y = a_y - a_d / 2 + rel_y

            x_min = x - eff_w / 2.0
            y_min = y - eff_d / 2.0
            x_max = x + eff_w / 2.0
            y_max = y + eff_d / 2.0

            rel_preferred_side = preferred_container_side_for_component(
                (a_x - a_w / 2, a_y - a_d / 2, a_x + a_w / 2, a_y + a_d / 2),
                (x_min, y_min, x_max, y_max),
                comp.get("connection_side"),
            )
            preferred_side = rel_preferred_side

            comp["x"] = x
            comp["y"] = y
            comp["x_min"] = x_min
            comp["y_min"] = y_min
            comp["x_max"] = x_max
            comp["y_max"] = y_max
            comp["rel_preferred_side"] = rel_preferred_side
            comp["preferred_side"] = preferred_side

            rz = compute_reserved_zone(comp, (x_min, y_min, x_max, y_max), preferred_side)
            res_x_min, res_y_min, res_x_max, res_y_max = 0, 0, 0, 0
            if rz is not None:
                res_x_min, res_y_min, res_x_max, res_y_max = rz
            comp["res_x_min"] = res_x_min
            comp["res_y_min"] = res_y_min
            comp["res_x_max"] = res_x_max
            comp["res_y_max"] = res_y_max

    # ---------------------------------------------------------------------
    # Mutation + gene transfer in new schema
    # ---------------------------------------------------------------------
    def _random_deltas_for_individual(
        self, indiv: Individual, step_frac: float
    ) -> List[Tuple[float, float]]:
        """Creates per-component (dx,dy) deltas in the container coordinate system.

        rel_x/rel_y are measured from the container's top-left in a container-dependent
        axis system (see GA). We keep that and perturb rel_x/rel_y directly.
        """
        indiv_dict = {p["name"]: p for p in indiv}
        deltas: List[Tuple[float, float]] = []
        for p in indiv:
            if p.get("fixed"):
                deltas.append((0.0, 0.0))
                continue

            parent = indiv_dict[p["a_name"]]
            a_w = parent["w"]
            a_d = parent["d"]
            a_w, a_d = (a_w, a_d) if (parent.get("orientation", 0) % 180) == 0 else (a_d, a_w)

            # allow a small fraction of container span
            max_dx = step_frac * a_w
            max_dy = step_frac * a_d
            deltas.append((random.uniform(-max_dx, max_dx), random.uniform(-max_dy, max_dy)))
        return deltas

    def _mutate_inplace(self, indiv: Individual, step_frac: float, orient_flip_prob: float,) -> None:
        """In-place mutation aligned with the new schema.

        - Perturbs rel_x/rel_y within container bounds.
        - With probability orient_flip_prob, rotates by 90 degrees if it fits.
        - Optionally handles wall-fit placement if enabled.
        """
        indiv_dict = {p["name"]: p for p in indiv}
        deltas = self._random_deltas_for_individual(indiv, step_frac)

        for idx, p in enumerate(indiv):
            if p.get("fixed"):
                continue

            parent = indiv_dict[p["a_name"]]
            a_w = parent["w"]
            a_d = parent["d"]
            a_w, a_d = (a_w, a_d) if (parent.get("orientation", 0) % 180) == 0 else (a_d, a_w)
            a_pside = parent.get("preferred_side", "top")

            # current effective size
            w_eff, d_eff = _effective_size_for_individual(p)
            rel_x = float(p.get("rel_x", w_eff / 2))
            rel_y = float(p.get("rel_y", d_eff / 2))

            # orientation flip
            if random.random() < orient_flip_prob:
                # try 90deg rotation only if fits
                if (d_eff <= a_w) and (w_eff <= a_d):
                    # orientation field is global; rel_o is relative to parent
                    p["orientation"] = (int(p.get("orientation", 0)) + 90) % 180
                    p["rel_o"] = (int(p.get("rel_o", 0)) + 90) % 180
                    w_eff, d_eff = d_eff, w_eff

                    # keep within bounds after rotation
                    if a_pside in ("top", "bottom"):
                        rx_min, rx_max = w_eff / 2, a_w - w_eff / 2
                        ry_min, ry_max = d_eff / 2, a_d - d_eff / 2
                    else:
                        # axes are swapped under left/right preferred side
                        rx_min, rx_max = d_eff / 2, a_d - d_eff / 2
                        ry_min, ry_max = w_eff / 2, a_w - w_eff / 2

                    rel_x = min(max(rel_x, rx_min), rx_max)
                    rel_y = min(max(rel_y, ry_min), ry_max)

            # location mutation
            dx, dy = deltas[idx]
            wall_flag = self._get_wall_flag(p)
            if self.wallfit_enabled and wall_flag == 1:
                # wall-fit placement (consistent with GA mutate)
                rel_x, rel_y = random_center_in_container(
                    a_w,
                    a_d,
                    w_eff,
                    d_eff,
                    wall_fit_enable=True,
                    wall_flag=1,
                    connection_side=p.get("connection_side"),
                    rng=random,
                    preferred_side=a_pside,
                )
            else:
                rel_x += dx
                rel_y += dy

                if a_pside in ("top", "bottom"):
                    rx_min, rx_max = w_eff / 2, a_w - w_eff / 2
                    ry_min, ry_max = d_eff / 2, a_d - d_eff / 2
                else:
                    rx_min, rx_max = d_eff / 2, a_d - d_eff / 2
                    ry_min, ry_max = w_eff / 2, a_w - w_eff / 2

                rel_x = min(max(rel_x, rx_min), rx_max)
                rel_y = min(max(rel_y, ry_min), ry_max)

            p["rel_x"] = rel_x
            p["rel_y"] = rel_y

        # recompute global fields after all local modifications
        self.recalculate_globals(indiv)

    def _gene_transfer(self, donor: Individual, target: Individual, block_len: int = 1) -> Individual:
        """Copies a small gene block from donor to target (new schema).

        We copy only *source-of-truth* fields and then recompute derived geometry.
        """
        child = copy.deepcopy(target)
        donor_map = {p["name"]: p for p in donor}
        child_map = {p["name"]: p for p in child}

        names = list(donor_map.keys())
        random.shuffle(names)
        block_len = max(1, min(int(block_len), len(names)))

        gene_keys = [
            "rel_x",
            "rel_y",
            "rel_o",
            "orientation",
            "connection_side",
            "wall_flag",
            "fixed",
        ]

        for name in names[:block_len]:
            if name not in child_map:
                continue
            src = donor_map[name]
            dst = child_map[name]
            for k in gene_keys:
                if k in src:
                    dst[k] = copy.deepcopy(src[k])

        # keep original order
        child_ordered = [child_map[p["name"]] for p in target]
        self.recalculate_globals(child_ordered)
        return child_ordered

    def _split_init_population(
        self,
        population: List[Individual],
        subpopulation_size: int,
    ) -> List[List[Individual]]:
        if not population:
            raise ValueError("bacterial_algorithm.run(): init_population is empty")

        if subpopulation_size <= 0:
            raise ValueError("bacterial_algorithm.run(): model_params.population_size must be > 0")

        if len(population) < subpopulation_size:
            raise ValueError(
                f"bacterial_algorithm.run(): init_population size ({len(population)}) "
                f"is smaller than model_params.population_size ({subpopulation_size})"
            )

        if len(population) % subpopulation_size != 0:
            raise ValueError(
                f"bacterial_algorithm.run(): init_population size ({len(population)}) "
                f"must be divisible by model_params.population_size ({subpopulation_size})"
            )

        shuffled = copy.deepcopy(population)
        random.shuffle(shuffled)

        return [
            shuffled[i:i + subpopulation_size]
            for i in range(0, len(shuffled), subpopulation_size)
        ]

    def _run_single_population(
            self,
            population: List[Individual],
            model_params: ModelParams,
            subrun_idx: int,
    ):
        def _evaluate_population(
                population: List[Individual],
                generation: int,
                overlaps_mandatory,
                wall,
        ):
            scored = []
            for ind in population:
                score = self.fitness(ind, generation, overlaps_mandatory, wall)
                scored.append((copy.deepcopy(ind), score))

            scored.sort(key=lambda x: x[1][0])

            if self.log_mode:
                for ind, score in scored:
                    indiv_for_anal.append((copy.deepcopy(ind), score))

            gen_best_ind = copy.deepcopy(scored[0][0])
            gen_best_score_tuple = scored[0][1]

            return scored, gen_best_ind, gen_best_score_tuple

        t0 = time.perf_counter()
        bests_for_save: list[tuple[Individual, tuple]] = []
        indiv_for_anal: list[Any] = []

        self.fitness_obj.reset_usages()

        overlaps_mandatory, wall = create_relation_df(population[0])
        self._wall_by_name = dict(wall)

        fitness_start = self.fitness_count()

        def _used_budget() -> int:
            return self.fitness_count() - fitness_start

        scored, gen_best_ind, gen_best_score_tuple = _evaluate_population(
            population, 0, overlaps_mandatory, wall
        )

        # not unnecessarily evaluate generation 0 again: the scores are already in the scored list.
        population_scores: list[tuple] = [score_tuple for _, score_tuple in scored]

        best_ind = copy.deepcopy(gen_best_ind)
        best_score = gen_best_score_tuple[0]

        # The bests save includes the local budget and the current generation.
        bests_for_save.append((
            copy.deepcopy(gen_best_ind),
            (best_score, 0, _used_budget())
        ))

        if (_used_budget() <= model_params.fitness_budget) and (best_score != 0):
            for generation in range(1, int(model_params.generations) + 1):
                for i in range(len(population)):
                    base = population[i]
                    base_score_tuple = population_scores[i]

                    clones = [copy.deepcopy(base) for _ in range(int(model_params.Nclones))]
                    clone_score_tuples: list[tuple] = []

                    for k, clone in enumerate(clones):
                        if k == 0:
                            score_tuple = base_score_tuple
                        else:
                            self._mutate_inplace(
                                clone,
                                step_frac=float(model_params.step_frac),
                                orient_flip_prob=float(model_params.orient_mut_prob),
                            )
                            score_tuple = self.fitness(
                                clone, generation, overlaps_mandatory, wall
                            )

                        clone_score_tuples.append(score_tuple)

                    best_clone_idx = min(
                        range(len(clones)),
                        key=lambda idx: clone_score_tuples[idx][0]
                    )

                    population[i] = copy.deepcopy(clones[best_clone_idx])
                    population_scores[i] = clone_score_tuples[best_clone_idx]

                order = sorted(
                    range(len(population)),
                    key=lambda idx: population_scores[idx][0]
                )
                half = len(order) // 2
                superior = order[:half] if half > 0 else order
                inferior = order[half:] if half > 0 else []

                if inferior:
                    for _ in range(int(model_params.Ninf)):
                        donor_idx = random.choice(superior)
                        target_idx = random.choice(inferior)

                        child = self._gene_transfer(
                            population[donor_idx],
                            population[target_idx],
                            block_len=int(getattr(model_params, "gt_block_len", 1)),
                        )
                        child_score_tuple = self.fitness(
                            child, generation, overlaps_mandatory, wall
                        )

                        if child_score_tuple[0] < population_scores[target_idx][0]:
                            population[target_idx] = copy.deepcopy(child)
                            population_scores[target_idx] = child_score_tuple

                scored = [
                    (copy.deepcopy(population[i]), population_scores[i])
                    for i in range(len(population))
                ]
                scored.sort(key=lambda x: x[1][0])

                if self.log_mode:
                    for ind, score in scored:
                        indiv_for_anal.append((copy.deepcopy(ind), score))

                best_idx = min(
                    range(len(population_scores)),
                    key=lambda idx: population_scores[idx][0]
                )
                gen_best_ind = copy.deepcopy(population[best_idx])
                gen_best_score_value = population_scores[best_idx][0]

                # The saved tuple reflects the current generation and local fitness budget usage.
                current_score_tuple = (gen_best_score_value, generation, _used_budget())
                bests_for_save.append((copy.deepcopy(gen_best_ind), current_score_tuple))

                if gen_best_score_value < best_score:
                    best_ind = copy.deepcopy(gen_best_ind)
                    best_score = gen_best_score_value

                if (_used_budget() > model_params.fitness_budget) or (best_score == 0):
                    break

        dt = time.perf_counter() - t0

        orig_solution_name = self.solution_name
        orig_init_population_file = self.init_population_file

        try:
            suffix = f"_subrun_{subrun_idx:03d}"
            self.solution_name = f"{orig_solution_name}{suffix}"
            if orig_init_population_file:
                self.init_population_file = f"{orig_init_population_file}{suffix}"

            if self.log_mode:
                save_the_indiv(
                    "indiv",
                    self.project_name,
                    self.solution_name,
                    model_params,
                    indiv_for_anal,
                    "Bacterial evolutionary algorithm",
                    dt,
                    self.init_population_file,
                    _used_budget(),
                    self.overlap_enabled,
                    self.wallfit_enabled,
                    out_dir=self.results_dir,
                )

            save_the_indiv(
                "bests",
                self.project_name,
                self.solution_name,
                model_params,
                bests_for_save,
                "Bacterial evolutionary algorithm",
                dt,
                self.init_population_file,
                _used_budget(),
                self.overlap_enabled,
                self.wallfit_enabled,
                out_dir=self.results_dir,
            )
        finally:
            self.solution_name = orig_solution_name
            self.init_population_file = orig_init_population_file

        return best_ind, best_score, dt
    # ---------------------------------------------------------------------
    # Main entry
    # ---------------------------------------------------------------------
    def run(self, model_params: ModelParams):
        """Runs BEA on randomly partitioned initial subpopulations."""

        if model_params.seed is not None:
            random.seed(model_params.seed)

        full_population: List[Individual] = copy.deepcopy(self.init_population or [])
        if not full_population:
            raise ValueError("bacterial_algorithm.run(): init_population is empty")

        subpopulation_size = int(model_params.population_size)
        subpopulations = self._split_init_population(full_population, subpopulation_size)

        global_best_ind = None
        global_best_score = None
        total_dt = 0.0

        for subrun_idx, subpopulation in enumerate(subpopulations, start=1):
            best_ind, best_score, dt = self._run_single_population(
                population=copy.deepcopy(subpopulation),
                model_params=model_params,
                subrun_idx=subrun_idx,
            )

            total_dt += dt

            if (global_best_score is None) or (best_score < global_best_score):
                global_best_score = best_score
                global_best_ind = copy.deepcopy(best_ind)

        return global_best_ind, global_best_score, total_dt
